package com.surviveTheTalk.client

import kotlin.math.PI
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Story 6.3b — JVM unit tests for [FormantVisemeAnalyzer]. No Android
 * APIs are touched inside the analyzer so we run on stock JVM — no
 * Robolectric.
 *
 * Rive viseme enum (Story 2.6): rest=0, aei=1, cdgknstxyz=2, o=3, ee=4,
 * chjsh=5, bmp=6, qwoo=7, r=8, l=9, th=10, fv=11. The analyzer emits 9
 * of these 12 (bmp, r/l, th are deliberately dropped — see analyzer
 * companion-object).
 */
class FormantVisemeAnalyzerTest {

    private val sampleRate = 48000

    @Test
    fun silence_returns_null_or_rest() {
        val analyzer = FormantVisemeAnalyzer()
        val bytes = ByteArray(960) // 480 mono frames of all-zero PCM16
        // First call from a fresh analyzer (lastEmitted = REST, target = REST):
        // emit() returns null because target == lastEmitted.
        val result = analyzer.analyze(bytes, frames = 480, channelCount = 1, sampleRate = sampleRate)
        assertNull("silence on a fresh analyzer must yield null (no change)", result)
    }

    /**
     * A high-amplitude 700 Hz tone — squarely in the F1 band of low vowels
     * — should classify as a voiced vowel (one of AEI=1, O=3, EE=4,
     * QWOO=7). Exact class depends on the F2 distribution of a pure sine
     * (no F2 → all energy bunches near F1), so we just assert "not REST"
     * and "voiced bucket".
     */
    @Test
    fun loud_tone_emits_a_voiced_viseme() {
        val analyzer = FormantVisemeAnalyzer()
        val bytes = pcm16Sine(frequencyHz = 700.0, frames = 480, amplitude = 12000)
        val result = analyzer.analyze(bytes, frames = 480, channelCount = 1, sampleRate = sampleRate)
        assertNotNull("loud tone must produce a non-null viseme transition", result)
        val voicedBucket = setOf(1 /*AEI*/, 3 /*O*/, 4 /*EE*/, 7 /*QWOO*/)
        assertTrue(
            "expected voiced viseme, got id=$result (acceptable set $voicedBucket)",
            result in voicedBucket,
        )
    }

    /** Hysteresis: after emitting a non-REST viseme, a near-instant
     *  silence chunk must NOT bounce back to REST before MIN_HOLD_MS,
     *  unless the analyzer's emit() rule allows it. The contract is:
     *  entering REST is instant — so REST after a vowel IS allowed.
     *  This pins the documented "entering REST is instant" behavior. */
    @Test
    fun rest_after_voiced_is_emitted_instantly() {
        val analyzer = FormantVisemeAnalyzer()
        val loud = pcm16Sine(frequencyHz = 700.0, frames = 480, amplitude = 12000)
        analyzer.analyze(loud, frames = 480, channelCount = 1, sampleRate = sampleRate)
        // Immediate silence — under the MIN_HOLD_MS=80 floor — must
        // still emit REST per the "entering REST is instant" contract.
        val silence = ByteArray(960)
        val result = analyzer.analyze(silence, frames = 480, channelCount = 1, sampleRate = sampleRate)
        assertEquals(0 /* REST */, result)
    }

    /** zero-frame input is a no-op. */
    @Test
    fun zero_frames_returns_null() {
        val analyzer = FormantVisemeAnalyzer()
        val result = analyzer.analyze(ByteArray(0), frames = 0, channelCount = 1, sampleRate = sampleRate)
        assertNull(result)
    }

    /** Stereo input is averaged across channels — not left-only.
     *  Build a stereo buffer where the left channel is a loud tone and
     *  the right channel is its inverse (so the average is silence).
     *  A left-only analyzer would mis-classify as a voiced viseme; a
     *  correct downmix yields silence (REST or null). */
    @Test
    fun stereo_is_downmixed_not_left_only() {
        val analyzer = FormantVisemeAnalyzer()
        val frames = 480
        val left = pcm16SineSamples(frequencyHz = 700.0, frames = frames, amplitude = 12000)
        val right = IntArray(frames) { -left[it] } // perfect cancellation
        val bytes = interleaveStereoToBytes(left, right)
        val result = analyzer.analyze(bytes, frames = frames, channelCount = 2, sampleRate = sampleRate)
        // Average is ~0 → RMS below SILENCE_RMS → target=REST → emit()
        // returns null (since fresh analyzer's lastEmitted=REST).
        assertNull("stereo cancellation must downmix to silence, got id=$result", result)
    }

    /** reset() clears emitted state so the next non-REST viseme fires. */
    @Test
    fun reset_allows_a_new_viseme_to_fire() {
        val analyzer = FormantVisemeAnalyzer()
        val loud = pcm16Sine(frequencyHz = 700.0, frames = 480, amplitude = 12000)
        val first = analyzer.analyze(loud, frames = 480, channelCount = 1, sampleRate = sampleRate)
        assertNotNull(first)
        // Without reset, re-running the same chunk yields null
        // (lastEmitted unchanged).
        assertNull(analyzer.analyze(loud, frames = 480, channelCount = 1, sampleRate = sampleRate))
        analyzer.reset()
        // After reset, the same tone fires again.
        val third = analyzer.analyze(loud, frames = 480, channelCount = 1, sampleRate = sampleRate)
        assertNotNull(third)
    }

    // ── helpers ───────────────────────────────────────────────────────

    /** Build a mono PCM16 little-endian buffer for a pure sine. */
    private fun pcm16Sine(frequencyHz: Double, frames: Int, amplitude: Int): ByteArray {
        val samples = pcm16SineSamples(frequencyHz, frames, amplitude)
        return monoSamplesToBytes(samples)
    }

    private fun pcm16SineSamples(frequencyHz: Double, frames: Int, amplitude: Int): IntArray {
        return IntArray(frames) { i ->
            (amplitude * sin(2.0 * PI * frequencyHz * i / sampleRate)).toInt()
        }
    }

    private fun monoSamplesToBytes(samples: IntArray): ByteArray {
        val bytes = ByteArray(samples.size * 2)
        for (i in samples.indices) {
            val s = samples[i]
            bytes[i * 2] = (s and 0xFF).toByte()
            bytes[i * 2 + 1] = ((s shr 8) and 0xFF).toByte()
        }
        return bytes
    }

    private fun interleaveStereoToBytes(left: IntArray, right: IntArray): ByteArray {
        require(left.size == right.size)
        val bytes = ByteArray(left.size * 4)
        for (i in left.indices) {
            val l = left[i]
            val r = right[i]
            bytes[i * 4] = (l and 0xFF).toByte()
            bytes[i * 4 + 1] = ((l shr 8) and 0xFF).toByte()
            bytes[i * 4 + 2] = (r and 0xFF).toByte()
            bytes[i * 4 + 3] = ((r shr 8) and 0xFF).toByte()
        }
        return bytes
    }
}
