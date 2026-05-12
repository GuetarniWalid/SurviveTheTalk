package com.surviveTheTalk.client

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * Story 6.3b — JVM unit tests for [Fft]. Pure mathematical code so we
 * can assert numeric properties directly without Android.
 */
class FftTest {

    /**
     * A 440 Hz sine wave sampled at 48 kHz over a 512-point window
     * should produce a magnitude peak at bin `round(440 / (48000/512)) = 5`.
     * Spectral leakage from the rectangular-window FFT spreads energy to
     * neighbours, so we accept the peak being within ±1 bin and clearly
     * dominant.
     */
    @Test
    fun forward_peaks_at_expected_bin_for_440hz_sine() {
        val size = 512
        val sampleRate = 48000.0
        val frequency = 440.0
        val binHz = sampleRate / size
        val expectedBin = (frequency / binHz + 0.5).toInt() // ≈ 5

        val real = FloatArray(size) { i ->
            sin(2.0 * PI * frequency * i / sampleRate).toFloat()
        }
        val imag = FloatArray(size)
        val fft = Fft(size)
        fft.forward(real, imag)
        val magnitude = FloatArray(size / 2)
        fft.magnitude(real, imag, magnitude)

        val peakBin = magnitude.indices.maxByOrNull { magnitude[it] }!!
        assertTrue(
            "peak bin $peakBin must be within ±1 of expected $expectedBin",
            abs(peakBin - expectedBin) <= 1,
        )
        // Peak must dominate the rest of the spectrum by at least 5×
        // (loose check; in practice the ratio is much larger).
        val nextBest = magnitude.indices
            .filter { abs(it - peakBin) > 2 }
            .maxOfOrNull { magnitude[it] } ?: 0.0f
        assertTrue(
            "peak ${magnitude[peakBin]} must dominate $nextBest by ≥5×",
            magnitude[peakBin] > nextBest * 5.0f,
        )
    }

    /** DC input (all samples equal) has all energy in bin 0. */
    @Test
    fun forward_concentrates_dc_in_bin_zero() {
        val size = 512
        val real = FloatArray(size) { 1.0f }
        val imag = FloatArray(size)
        val fft = Fft(size)
        fft.forward(real, imag)
        val magnitude = FloatArray(size / 2)
        fft.magnitude(real, imag, magnitude)

        assertTrue("bin 0 must be the peak for DC", magnitude[0] > 0.0f)
        for (i in 1 until magnitude.size) {
            assertTrue(
                "bin $i must be ≪ bin 0 for pure DC (was ${magnitude[i]} vs ${magnitude[0]})",
                magnitude[i] < magnitude[0] * 0.01f,
            )
        }
    }

    /** Zero input → zero magnitudes everywhere. */
    @Test
    fun forward_keeps_zero_input_at_zero() {
        val size = 512
        val real = FloatArray(size)
        val imag = FloatArray(size)
        val fft = Fft(size)
        fft.forward(real, imag)
        val magnitude = FloatArray(size / 2)
        fft.magnitude(real, imag, magnitude)

        for (i in magnitude.indices) {
            assertEquals(0.0f, magnitude[i], 1e-6f)
        }
    }

    /** Construction must reject non-power-of-two sizes and sizes < 2. */
    @Test
    fun construction_rejects_invalid_sizes() {
        for (bad in intArrayOf(0, 1, 3, 5, 6, 7, 100, 513)) {
            try {
                Fft(bad)
                fail("Fft($bad) must throw IllegalArgumentException")
            } catch (e: IllegalArgumentException) {
                // expected
            }
        }
    }
}
