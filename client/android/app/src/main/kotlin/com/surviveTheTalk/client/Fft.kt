package com.surviveTheTalk.client

import kotlin.math.cos
import kotlin.math.sin

/**
 * Story 6.3b — pure-Kotlin radix-2 Cooley–Tukey FFT used by
 * [FormantVisemeAnalyzer] to extract the magnitude spectrum of each
 * audio chunk.
 *
 * Why hand-rolled: a 512-point FFT is ~5 KB of code, runs in tens of
 * microseconds on a modern phone, and avoids dragging in an ML / DSP
 * dependency just for one usage. The twiddle factors are precomputed
 * once at construction time so per-call cost is just bit-reversal +
 * butterflies + magnitude.
 *
 * Not thread-safe: one instance per analyzer (which itself is called
 * only from the WebRTC playback callback thread).
 *
 * @param size MUST be a power of two and ≥ 2.
 */
class Fft(val size: Int) {
    init {
        require(size >= 2 && (size and (size - 1)) == 0) {
            "FFT size must be a power of two ≥ 2, got $size"
        }
    }

    private val cosTable: FloatArray
    private val sinTable: FloatArray

    init {
        val half = size / 2
        cosTable = FloatArray(half)
        sinTable = FloatArray(half)
        for (i in 0 until half) {
            val angle = -2.0 * Math.PI * i / size
            cosTable[i] = cos(angle).toFloat()
            sinTable[i] = sin(angle).toFloat()
        }
    }

    /**
     * In-place forward FFT. Input is split-complex: [real] and [imag]
     * are length [size], with imag = 0 for a real-valued time signal.
     * On return, real/imag hold the complex spectrum.
     */
    fun forward(real: FloatArray, imag: FloatArray) {
        require(real.size == size && imag.size == size) {
            "real/imag arrays must be length $size"
        }
        // 1. Bit-reversal permutation.
        var j = 0
        for (i in 1 until size) {
            var bit = size ushr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit ushr 1
            }
            j = j or bit
            if (i < j) {
                var tmp = real[i]; real[i] = real[j]; real[j] = tmp
                tmp = imag[i]; imag[i] = imag[j]; imag[j] = tmp
            }
        }

        // 2. Iterative butterflies.
        var step = 2
        while (step <= size) {
            val half = step ushr 1
            val tableStep = size / step
            var k = 0
            while (k < size) {
                var twi = 0
                var i = k
                while (i < k + half) {
                    val c = cosTable[twi]
                    val s = sinTable[twi]
                    val iH = i + half
                    val tpre = real[iH] * c - imag[iH] * s
                    val tpim = real[iH] * s + imag[iH] * c
                    real[iH] = real[i] - tpre
                    imag[iH] = imag[i] - tpim
                    real[i] += tpre
                    imag[i] += tpim
                    twi += tableStep
                    i++
                }
                k += step
            }
            step = step shl 1
        }
    }

    /**
     * Write the magnitude spectrum of an already-forward'd buffer into
     * [out]. Only the first [size]/2 bins are filled (the upper half
     * mirrors the lower for real inputs).
     */
    fun magnitude(real: FloatArray, imag: FloatArray, out: FloatArray) {
        val half = size / 2
        require(out.size >= half)
        for (i in 0 until half) {
            val re = real[i]
            val im = imag[i]
            out[i] = kotlin.math.sqrt(re * re + im * im)
        }
    }
}
