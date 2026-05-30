/// Story 6.11 — typed payload for the `env_warning` data-channel envelope
/// (server-side emitter: `server/pipeline/environment_monitor.py`).
///
/// Wire format: `{type: "env_warning", data: {reason, detected_speakers}}`.
/// The server emits exactly one per call, the moment Soniox speaker
/// diarization confirms a parasitic background voice (≥2 of the last 4
/// user turns each carried a non-primary speaker). The client renders the
/// [NoisyEnvironmentBanner] on arrival so the user connects "background
/// voice detected → character is about to cut the call → it won't count".
///
/// The `data` map is validated by [DataChannelHandler] before this class
/// is constructed; consumers receive a fully-shaped, non-null instance.
class EnvWarningPayload {
  /// Detection reason. Today only `'background_voice'` (parasitic speaker);
  /// kept as a string for forward-compat with future env categories.
  final String reason;

  /// Number of distinct speakers detected recently (the user + the
  /// parasitic voice(s)) — typically 2. Informational; the banner copy
  /// does not currently surface the count.
  final int detectedSpeakers;

  const EnvWarningPayload({
    required this.reason,
    required this.detectedSpeakers,
  });
}
