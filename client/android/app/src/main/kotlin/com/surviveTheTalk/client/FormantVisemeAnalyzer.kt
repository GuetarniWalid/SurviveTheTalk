package com.surviveTheTalk.client

import kotlin.math.cos
import kotlin.math.sqrt

/**
 * Story 6.3b — production [VisemeAnalyzer]. Classifies each PCM chunk
 * into a Rive viseme id using time-domain features (RMS, ZCR) plus a
 * 512-point FFT for spectral analysis.
 *
 * Voiced vowels are characterised by two resonance peaks of the vocal
 * tract:
 *   - **F1** (250–900 Hz) tracks vertical mouth opening.
 *   - **F2** (700–3000 Hz) tracks horizontal mouth shape (front/back).
 *
 * Locating (F1, F2) in the spectrum and reading off a standard
 * formant chart gives us a phoneme-aware viseme choice without any
 * model file, network call, or proprietary `.so`.
 *
 * Pipeline per audio chunk (~10 ms at 48 kHz):
 *   1. PCM16 → float, downmix to mono into [bufReal].
 *   2. RMS energy + zero-crossing rate (ZCR) computed in the same loop.
 *   3. If RMS < silence: emit REST.
 *   4. Else apply Hann window + FFT.
 *   5. Compute spectral magnitude + spectral centroid.
 *   6. High-ZCR branch → fricative classification (chjsh / th / fv /
 *      cdgknstxyz) by centroid bucket.
 *   7. Low-ZCR (voiced) branch → vowel classification by band-energy
 *      ratio in the F1 / F2 regions.
 *   8. Hysteresis: each non-REST viseme is held ≥ 80 ms.
 *
 * Accuracy target ~85–90 % phonetic match (vs ~80 % energy-only,
 * ~95 % OVRLipSync). Trade-offs vs OVR — see companion-object note
 * for full rationale on the 3 Rive ids we deliberately never emit
 * (`bmp`, `r`/`l`, `th`).
 *
 * Thread-safety: not safe for concurrent use; the audio callback in
 * [AudioClockChannel] is the sole caller and is serialised.
 */
class FormantVisemeAnalyzer : VisemeAnalyzer {
    companion object {
        private const val FFT_SIZE = 512

        /** Below this RMS the chunk is silence → REST. PCM16 samples
         *  are in [-32768, 32767]; speech typically lies 1000-8000 RMS,
         *  background noise <300. */
        private const val SILENCE_RMS = 350.0

        /** ZCR thresholds. ZCR above [STRONG_FRIC_ZCR] = unvoiced
         *  sibilant; above [MOD_FRIC_ZCR] = consonant-like; below =
         *  voiced (we then run the vowel branch). */
        private const val STRONG_FRIC_ZCR = 0.28
        private const val MOD_FRIC_ZCR = 0.18

        /** Minimum hold per emitted non-REST viseme. Prevents flicker
         *  on transitional chunks that straddle two phonemes. */
        private const val MIN_HOLD_MS = 80L

        // 9-of-12 Rive `visemeId` ids actually emitted by this analyzer.
        // The 3 we drop, and why:
        //   - `bmp`=6 (bilabial /b/p/m/) — too brief (~30 ms each) to
        //     catch with a 10-ms chunk + 80-ms hysteresis floor.
        //   - `r`=8 and `l`=9 — distinguished by F3, which we don't
        //     compute (we only look at F1/F2 band energies).
        //   - `th`=10 (/θ/, /ð/) — acoustically too close to `/s/` and
        //     `/f/` with a centroid-only classifier (both peak in the
        //     5-7 kHz band with similar shape — distinguishing them
        //     needs spectral tilt analysis we don't do here). Emitting
        //     `TH` on best-guess was wrong ~80 % of the time; better
        //     to absorb /θ/ /ð/ into `FV` (lip-near-teeth, visually
        //     close) and `CDGKNSTXYZ`.
        // The dropped phonemes fall through to the closest acceptable
        // viseme without ever causing wrong-frame flicker.
        private const val REST = 0
        private const val AEI = 1
        private const val CDGKNSTXYZ = 2
        private const val O = 3
        private const val EE = 4
        private const val CHJSH = 5
        private const val QWOO = 7
        private const val FV = 11
    }

    private val fft = Fft(FFT_SIZE)
    private val bufReal = FloatArray(FFT_SIZE)
    private val bufImag = FloatArray(FFT_SIZE)
    private val magnitude = FloatArray(FFT_SIZE / 2)

    /** Precomputed Hann window — multiplied with the time-domain
     *  signal before FFT to reduce spectral leakage. */
    private val hannWindow: FloatArray = FloatArray(FFT_SIZE) { i ->
        (0.5 * (1.0 - cos(2.0 * Math.PI * i / (FFT_SIZE - 1)))).toFloat()
    }

    private var lastEmittedViseme: Int = REST
    private var lastEmittedAtNanos: Long = 0L

    override fun analyze(
        data: ByteArray,
        frames: Int,
        channelCount: Int,
        sampleRate: Int,
    ): Int? {
        if (frames <= 0) return null

        // 1. PCM16 → float, downmix to mono by averaging across channels.
        //    Truncate to FFT_SIZE if the chunk is larger; zero-pad if
        //    smaller. WebRTC chunks are typically 480 samples at 48 kHz,
        //    just under FFT_SIZE. LiveKit publishes mono today so the
        //    inner loop runs once per frame in practice; the loop is
        //    forward-compat against any future stereo source.
        val usedFrames = if (frames < FFT_SIZE) frames else FFT_SIZE
        val stride = channelCount * 2
        var sumSquares = 0.0
        var zeroCrossings = 0
        var prevSample = 0
        for (i in 0 until usedFrames) {
            var channelSum = 0
            for (c in 0 until channelCount) {
                val off = i * stride + c * 2
                val lo = data[off].toInt() and 0xFF
                val hi = data[off + 1].toInt()
                channelSum += (hi shl 8) or lo
            }
            val s = channelSum / channelCount
            bufReal[i] = s.toFloat()
            bufImag[i] = 0.0f
            sumSquares += s.toDouble() * s.toDouble()
            if (i > 0 && (s >= 0) != (prevSample >= 0)) zeroCrossings++
            prevSample = s
        }
        // Zero-pad.
        for (i in usedFrames until FFT_SIZE) {
            bufReal[i] = 0.0f
            bufImag[i] = 0.0f
        }

        val rms = sqrt(sumSquares / usedFrames)
        val zcr = if (usedFrames > 1) {
            zeroCrossings.toDouble() / (usedFrames - 1)
        } else {
            0.0
        }

        val target = if (rms < SILENCE_RMS) {
            REST
        } else {
            // 2. Window + FFT + magnitude.
            for (i in 0 until usedFrames) bufReal[i] *= hannWindow[i]
            fft.forward(bufReal, bufImag)
            fft.magnitude(bufReal, bufImag, magnitude)

            classify(zcr, sampleRate)
        }

        return emit(target)
    }

    override fun reset() {
        lastEmittedViseme = REST
        lastEmittedAtNanos = 0L
    }

    /**
     * Apply hysteresis and return the new viseme id, or null if it's
     * unchanged or the held-floor hasn't elapsed yet. Entering REST is
     * instant (word-boundary closures must look crisp), entering any
     * other viseme requires [MIN_HOLD_MS] since the last change.
     */
    private fun emit(target: Int): Int? {
        if (target == lastEmittedViseme) return null
        val now = System.nanoTime()
        val elapsedMs = (now - lastEmittedAtNanos) / 1_000_000L
        if (target != REST && elapsedMs < MIN_HOLD_MS) return null
        lastEmittedViseme = target
        lastEmittedAtNanos = now
        return target
    }

    /** Top-level decision: fricative branch or vowel branch, by ZCR. */
    private fun classify(zcr: Double, sampleRate: Int): Int {
        val binHz = sampleRate.toDouble() / FFT_SIZE
        return if (zcr >= MOD_FRIC_ZCR) {
            classifyFricative(zcr, binHz)
        } else {
            classifyVowel(binHz)
        }
    }

    /** Centroid-based fricative classification.
     *
     *  Acoustic anchors (Stevens, *Acoustic Phonetics*):
     *   - `/s/`, `/z/` — narrow peak at 5-7 kHz (highest-centroid
     *     fricatives in English). Visually: teeth close, lips slightly
     *     spread → routes to `CDGKNSTXYZ` (the s/t/d/n/z bucket).
     *   - `/ʃ/`, `/ʒ/`, `/tʃ/`, `/dʒ/` — broader peak at 2.5-4 kHz,
     *     lips slightly rounded → routes to `CHJSH`.
     *   - `/f/`, `/v/` — diffuse, weak peak around 1.5-3 kHz, lower
     *     bottom-lip on upper teeth → routes to `FV`. /θ/ /ð/ also
     *     fall here by design (we don't try to disambiguate — see
     *     companion-object note).
     *   - Other moderate-ZCR consonants (unvoiced stops, weak
     *     fricatives) bucket into `CDGKNSTXYZ`. */
    private fun classifyFricative(zcr: Double, binHz: Double): Int {
        val centroid = spectralCentroid(binHz, fromHz = 1000.0, toHz = 8000.0)
        return when {
            // Strong sibilant + very-high centroid = /s/, /z/.
            zcr >= STRONG_FRIC_ZCR && centroid > 5000.0 -> CDGKNSTXYZ
            // Strong sibilant + mid-high centroid = /ʃ/, /tʃ/, /dʒ/.
            zcr >= STRONG_FRIC_ZCR && centroid > 2500.0 -> CHJSH
            // Mid-frequency, weak — labio-dentals + interdentals.
            centroid > 1500.0 -> FV
            // Low-centroid moderate-ZCR — stops + weak alveolars.
            else -> CDGKNSTXYZ
        }
    }

    /** Voiced classification by F1 / F2 band-energy ratios. Bands are
     *  picked from the standard IPA formant chart:
     *
     *  ```
     *  F2 (Hz)  ┌─────────────────────────────┐
     *  2500+    │     ee  ih                  │  front
     *  1500-2500│           ɛ ɑ (aei)         │
     *   600-1500│   qwoo  o  (back vowels)    │
     *  F1 (Hz)  │ low (200-400)   high (500-900) │
     *  ``` */
    private fun classifyVowel(binHz: Double): Int {
        // Energy in F1 sub-bands.
        val f1Low = bandEnergy(binHz, 200.0, 450.0)   // /u/, /i/ (high vowels)
        val f1High = bandEnergy(binHz, 450.0, 900.0)  // /a/, /ɛ/ (low vowels)
        // Energy in F2 sub-bands.
        val f2Back = bandEnergy(binHz, 600.0, 1200.0)   // /u/, /o/
        val f2Mid = bandEnergy(binHz, 1200.0, 2000.0)   // /a/, /ɛ/
        val f2Front = bandEnergy(binHz, 2000.0, 3200.0) // /i/, /ɪ/

        // The dominant F2 region trumps everything — F2 is the
        // clearest discriminator on the front/back axis.
        return when {
            // Front vowels: F2 dominant in the high band → ee.
            f2Front > f2Mid && f2Front > f2Back -> EE

            // Back vowels: F2 dominant in the low band.
            f2Back > f2Mid && f2Back > f2Front -> {
                // F1 differentiates oo (low F1) from o (mid F1).
                if (f1Low > f1High) QWOO else O
            }

            // Central / mid F2 → open vowel family. We deliberately do
            // NOT route to `bmp` (closed-lips bilabial) here: at this
            // point the speaker is in a voiced segment, so closing the
            // mouth mid-vowel reads as broken. `aei` is the safest
            // open-mouth fallback and matches what the audio sounds
            // like.
            else -> AEI
        }
    }

    /** Sum of magnitude bins within [fromHz, toHz). Cheap proxy for
     *  formant energy in that region — formants are broad peaks so
     *  exact peak picking is unnecessary. Upper bound exclusive so
     *  adjacent bands (e.g. f1Low 200-450 / f1High 450-900) don't
     *  double-count the shared boundary bin. */
    private fun bandEnergy(binHz: Double, fromHz: Double, toHz: Double): Float {
        val lo = (fromHz / binHz).toInt().coerceIn(0, magnitude.size - 1)
        val hi = (toHz / binHz).toInt().coerceIn(lo, magnitude.size - 1)
        var sum = 0.0f
        for (i in lo until hi) sum += magnitude[i]
        return sum
    }

    /** Spectral centroid in Hz over the chosen range. Used to bucket
     *  fricatives (high-centroid = sibilant, low-centroid = labio-
     *  dental). */
    private fun spectralCentroid(binHz: Double, fromHz: Double, toHz: Double): Double {
        val lo = (fromHz / binHz).toInt().coerceIn(0, magnitude.size - 1)
        val hi = (toHz / binHz).toInt().coerceIn(lo, magnitude.size - 1)
        var num = 0.0
        var den = 0.0
        for (i in lo..hi) {
            val m = magnitude[i].toDouble()
            num += m * (i * binHz)
            den += m
        }
        return if (den > 0.0) num / den else 0.0
    }
}
