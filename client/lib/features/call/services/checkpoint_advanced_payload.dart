/// Story 6.7 — typed payload for the `checkpoint_advanced` data-channel
/// envelope (server-side emitter: `server/pipeline/checkpoint_manager.py`).
///
/// Wire format: `{type: "checkpoint_advanced", data: {checkpoint_id,
/// index, total, next_hint}}`. The `data` map is validated by
/// [DataChannelHandler] before this class is constructed; consumers
/// receive a fully-shaped, non-null instance.
///
/// `index` is the position the stepper has JUST entered (0-based, the
/// server's convention since Story 6.6). `total` is the total checkpoint
/// count. `hintText` is the hint to show for the CURRENT checkpoint
/// (server-side field name `next_hint` is retained on the wire; renamed
/// here for clarity at the consumer end).
class CheckpointAdvancedPayload {
  final String checkpointId;
  final int index;
  final int total;
  final String hintText;

  const CheckpointAdvancedPayload({
    required this.checkpointId,
    required this.index,
    required this.total,
    required this.hintText,
  });
}
