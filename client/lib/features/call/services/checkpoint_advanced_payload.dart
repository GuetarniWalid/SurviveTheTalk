/// Story 6.7 — typed payload for the `checkpoint_advanced` data-channel
/// envelope (server-side emitter: `server/pipeline/checkpoint_manager.py`).
///
/// Wire format: `{type: "checkpoint_advanced", data: {checkpoint_id,
/// index, total, next_hint}}`. The `data` map is validated by
/// [DataChannelHandler] before this class is constructed; consumers
/// receive a fully-shaped, non-null instance.
///
/// `index` is the author-order index of the goal that JUST flipped to met
/// (Story 6.10 — under goal-based dialogue goals can flip out of order, so
/// `index` is no longer monotonic; it identifies the most-recent flip for
/// the "just-lit" animation). `total` is the total objective count.
/// `hintText` is the hint of the suggested-focus pending goal (server-side
/// field name `next_hint` is retained on the wire; renamed here for clarity).
///
/// Story 6.10 — [goalsMetIndices] carries the FULL set of met-goal indices
/// (author order) so a consumer can render the exact set, including
/// out-of-order fills. The Rive stepper today is count-based
/// (`lastCheckIndex` = number of filled circles), so the call screen drives
/// it from `goalsMetIndices.length`; the full index set is carried for when
/// the `.riv` gains per-circle addressing (Walid-owned design follow-up).
/// On a pre-6.10 server envelope (no `goals_met_indices` field) the parser
/// reconstructs the linear set `[0..index-1]` so the count stays correct
/// during a rolling deploy.
///
/// Story 6.10 UI refonte — [hints] carries EVERY step's text in author
/// order (server `hints`). The Flutter step HUD renders + animates any
/// step locally from this list (including the out-of-order completion
/// choreography), so the wire stays idempotent + loss-robust (same
/// philosophy as [goalsMetIndices]). Empty when the field is absent
/// (pre-refonte server) — the HUD then falls back to [hintText].
class CheckpointAdvancedPayload {
  final String checkpointId;
  final int index;
  final int total;
  final String hintText;
  final List<int> goalsMetIndices;
  final List<String> hints;

  const CheckpointAdvancedPayload({
    required this.checkpointId,
    required this.index,
    required this.total,
    required this.hintText,
    required this.goalsMetIndices,
    required this.hints,
  });
}
