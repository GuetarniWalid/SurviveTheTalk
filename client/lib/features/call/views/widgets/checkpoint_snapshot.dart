/// Story 6.7 — snapshot of the CheckpointStepper's state. Mirrors the
/// `checkpoint_advanced` data-channel envelope (server: `pipeline/
/// checkpoint_manager.py`) but stored as Dart-idiomatic fields. Pushed
/// to the Rive `.riv` file via 3 ViewModel writes on every update.
///
/// `currentIndex` is server-side 0-based (matches the wire). The
/// Phase-2 widget that consumes this translates to 1-based before
/// writing the Rive `stepsCount` property (Deviation #3 — Walid
/// authors the .riv against 1-based human-readable step numbering).
///
/// Lives in its own file so Phase 1 (server emit + data-channel
/// plumbing + reconcile) can ship + tests can pass before the Rive
/// widget itself lands in Phase 2.
class CheckpointSnapshot {
  final int currentIndex;
  final int total;
  final String hintText;

  const CheckpointSnapshot({
    required this.currentIndex,
    required this.total,
    required this.hintText,
  });

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is CheckpointSnapshot &&
          other.currentIndex == currentIndex &&
          other.total == total &&
          other.hintText == hintText;

  @override
  int get hashCode => Object.hash(currentIndex, total, hintText);

  @override
  String toString() =>
      'CheckpointSnapshot(currentIndex: $currentIndex, '
      'total: $total, hintText: $hintText)';
}
