package com.surviveTheTalk.client

/**
 * Story 6.3b — abstract interface for client-side viseme estimation.
 *
 * Implementations receive raw PCM audio chunks (the same chunks the
 * speaker is about to play) and return one of the 12 Rive visemeId
 * enum cases (Story 2.6 §3) — or `null` when no change since the last
 * call.
 *
 * The current production implementation is [FormantVisemeAnalyzer]
 * (RMS + ZCR + 512-point FFT band-energy formant detection over the
 * F1/F2 plane). The interface is kept abstract to make swapping in a
 * future model (e.g. an ONNX phoneme classifier) a one-line change in
 * [AudioClockChannel].
 *
 * Both call sites — the production analyzer and any future drop-in —
 * are stateless from the caller's perspective: the plugin just calls
 * [analyze] per audio chunk and emits whatever comes back. Sync is
 * guaranteed because analysis runs on the audio callback thread, on
 * the exact bytes about to hit the DAC.
 */
interface VisemeAnalyzer {
    /**
     * @param data PCM 16-bit little-endian audio bytes (interleaved if
     *   [channelCount] > 1).
     * @param frames number of audio frames (samples per channel).
     * @param channelCount 1 (mono) or 2 (stereo). LiveKit audio is
     *   typically mono.
     * @param sampleRate Hz (typically 48000).
     * @return new viseme id (0..11) if it changed since the last call,
     *   null otherwise (no need to redraw mouth). REST (0) is a valid
     *   return value — used during silences.
     */
    fun analyze(
        data: ByteArray,
        frames: Int,
        channelCount: Int,
        sampleRate: Int,
    ): Int?

    /** Reset internal state (e.g. on call start). */
    fun reset()
}
