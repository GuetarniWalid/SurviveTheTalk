import 'package:flutter/foundation.dart';

/// Story 6.7 / 6.10 — snapshot of the checkpoint HUD state. Mirrors the
/// `checkpoint_advanced` data-channel envelope (server: `pipeline/
/// checkpoint_manager.py`) but stored as Dart-idiomatic fields.
///
/// Story 6.10 UI refonte (2026-05-28) — the HUD is now a Flutter widget
/// ([CheckpointStepHud]) overlaid on the Rive character; the Rive `.riv`
/// no longer renders checkpoints. The widget shows ONLY the current step
/// and animates per-flip, so the snapshot carries:
///   - [hints]            — every step's text, author order (envelope `hints`)
///   - [metIndices]       — sorted set of met-goal indices (`goals_met_indices`)
///   - [total]            — total objective count
///   - [justFlippedIndex] — the index that flipped to met in THIS update
///                          (drives the completion animation), or null on
///                          the initial state / call-end reconcile.
///
/// Derived getters compute the active (first not-yet-met, author order)
/// step locally, so the widget never needs a server round-trip to know
/// what to display next.
@immutable
class CheckpointSnapshot {
  final List<String> hints;
  final List<int> metIndices;
  final int total;
  final int? justFlippedIndex;

  const CheckpointSnapshot({
    required this.hints,
    required this.metIndices,
    required this.total,
    this.justFlippedIndex,
  });

  /// Number of objectives met so far.
  int get metCount => metIndices.length;

  /// First author-order index not yet met, or null if all met.
  int? get activeIndex {
    for (var i = 0; i < total; i++) {
      if (!metIndices.contains(i)) return i;
    }
    return null;
  }

  /// Text of the active (next not-yet-met) step, or empty if all met /
  /// hints unavailable.
  String get activeHint => hintAt(activeIndex);

  /// Text of the step at [index], or empty if out of range / null.
  String hintAt(int? index) {
    if (index == null || index < 0 || index >= hints.length) return '';
    return hints[index];
  }

  /// All objectives complete (call survived path).
  bool get allMet => total > 0 && metCount >= total;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is CheckpointSnapshot &&
          listEquals(other.hints, hints) &&
          listEquals(other.metIndices, metIndices) &&
          other.total == total &&
          other.justFlippedIndex == justFlippedIndex;

  @override
  int get hashCode => Object.hash(
    Object.hashAll(hints),
    Object.hashAll(metIndices),
    total,
    justFlippedIndex,
  );

  @override
  String toString() =>
      'CheckpointSnapshot(metIndices: $metIndices, total: $total, '
      'justFlippedIndex: $justFlippedIndex, hints: $hints)';
}
