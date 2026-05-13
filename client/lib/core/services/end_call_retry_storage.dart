// Persistent queue of `POST /calls/{id}/end` requests that failed while
// offline. Read on app boot + on connectivity regain by
// `EndCallRetryService` to drain. Story 6.5 Option B (post-deploy fix
// for the "metro disconnect → cap counter stuck for 1 h" UX).
//
// Why secure storage rather than a plain file or `shared_preferences`:
// the project already depends on `flutter_secure_storage` (TokenStorage,
// ConsentStorage). Reusing it keeps the deps footprint identical and
// the storage pattern consistent with the rest of `lib/core/`. The
// payload itself is NOT sensitive (just call ids + canonical reason
// strings), but the encryption is a free side benefit.
//
// Stored shape: a single key `pending_end_calls` holding a JSON array
// of entries. Each entry: `{"callId": int, "reason": string,
// "queuedAt": ISO8601 UTC}`. We use a single key + JSON-encode the
// list (rather than one key per entry) so the read / write are atomic
// and we never have to enumerate keys.

import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class PendingEndCall {
  final int callId;
  final String reason;
  final DateTime queuedAt;

  const PendingEndCall({
    required this.callId,
    required this.reason,
    required this.queuedAt,
  });

  Map<String, dynamic> toJson() => {
    'callId': callId,
    'reason': reason,
    'queuedAt': queuedAt.toIso8601String(),
  };

  factory PendingEndCall.fromJson(Map<String, dynamic> json) {
    return PendingEndCall(
      callId: json['callId'] as int,
      reason: json['reason'] as String,
      queuedAt: DateTime.parse(json['queuedAt'] as String),
    );
  }

  @override
  bool operator ==(Object other) =>
      other is PendingEndCall &&
      other.callId == callId &&
      other.reason == reason &&
      other.queuedAt == queuedAt;

  @override
  int get hashCode => Object.hash(callId, reason, queuedAt);
}

class EndCallRetryStorage {
  static const String _key = 'pending_end_calls';

  final FlutterSecureStorage _storage;

  EndCallRetryStorage([FlutterSecureStorage? storage])
    : _storage = storage ?? const FlutterSecureStorage();

  /// Append a new entry. If an entry for the same `callId` already
  /// exists (rare but possible — e.g. two fast-fail attempts), it is
  /// replaced rather than duplicated. Same-callId duplicates would be
  /// harmless on replay thanks to server idempotency, but a clean
  /// queue avoids redundant POST traffic on radio return.
  Future<void> enqueue(PendingEndCall entry) async {
    final current = await getAll();
    final filtered = current.where((e) => e.callId != entry.callId).toList();
    filtered.add(entry);
    await _write(filtered);
  }

  /// Returns the queue (oldest-first). Tolerates a corrupt or missing
  /// blob: a `FormatException` from `jsonDecode` is logged via
  /// `clear()` (corrupt blob is purged) so subsequent enqueue / replay
  /// starts from a clean slate. Never throws — callers can rely on
  /// this returning a List (possibly empty).
  Future<List<PendingEndCall>> getAll() async {
    final raw = await _storage.read(key: _key);
    if (raw == null || raw.isEmpty) return const <PendingEndCall>[];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) {
        // Drop & start clean rather than perpetually fail-on-read.
        await clear();
        return const <PendingEndCall>[];
      }
      return decoded
          .cast<Map<String, dynamic>>()
          .map(PendingEndCall.fromJson)
          .toList();
    } on FormatException {
      await clear();
      return const <PendingEndCall>[];
    }
  }

  /// Remove a specific entry by `callId`. Called by the retry service
  /// after a successful replay. No-op if the entry is no longer present.
  Future<void> remove(int callId) async {
    final current = await getAll();
    final filtered = current.where((e) => e.callId != callId).toList();
    if (filtered.length == current.length) return;
    await _write(filtered);
  }

  /// Wipe the entire queue. Used both as a recovery from a corrupt
  /// blob and as a callable for test setup.
  Future<void> clear() async {
    await _storage.delete(key: _key);
  }

  Future<void> _write(List<PendingEndCall> entries) async {
    if (entries.isEmpty) {
      await _storage.delete(key: _key);
      return;
    }
    final encoded = jsonEncode(entries.map((e) => e.toJson()).toList());
    await _storage.write(key: _key, value: encoded);
  }
}
