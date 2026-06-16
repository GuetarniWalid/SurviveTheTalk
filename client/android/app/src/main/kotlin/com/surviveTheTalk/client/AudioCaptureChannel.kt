package com.surviveTheTalk.client

import android.media.AudioFormat
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.cloudwebrtc.webrtc.FlutterWebRTCPlugin
import com.cloudwebrtc.webrtc.audio.RecordSamplesReadyCallbackAdapter
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import java.util.concurrent.atomic.AtomicBoolean
import org.webrtc.audio.JavaAudioDeviceModule
import kotlin.math.sqrt

/**
 * Story 7.5 (D3-c) / Story 7.6 — Android-side mic RMS tap that streams
 * short-window loudness values to Flutter's
 * [com.surviveTheTalk.client.HesitationMeter] so it can detect the user's
 * speech ONSET on-device (the second boundary of a hesitation gap; the first is
 * the character-audio-end the viseme stack already provides). Onset accuracy
 * matters; word accuracy does not — so a cheap RMS is enough, and the
 * noise-robustness lives in the Dart meter (adaptive floor + SNR), NOT in the
 * cleanliness of this signal.
 *
 * **The sister of [AudioClockChannel]** — same proven reflection attach, but on
 * the RECORD side: it reflects flutter_webrtc's private
 * `recordSamplesReadyCallbackAdapter` (a [RecordSamplesReadyCallbackAdapter],
 * a fan-out of [JavaAudioDeviceModule.SamplesReadyCallback]) and adds a callback
 * whose `onWebRtcAudioRecordSamplesReady` computes the per-chunk RMS of the
 * captured PCM16 frame and pushes it (a Double) to Dart.
 *
 * IMPORTANT — where this sits relative to noise processing: the record
 * SamplesReadyCallback fires right after `AudioRecord.read()` and BEFORE the
 * libwebrtc software APM (AEC3 / strong NS / AGC). So this signal is post
 * hardware-AEC/NS but PRE software-APM — "mostly-cleaned near-end", NOT
 * AEC3-clean. Robustness to steady noise + the character's echo comes from the
 * Dart meter's adaptive-floor + SNR + the ARMING GATE (the meter is disarmed
 * while the character speaks), never from this signal being clean.
 *
 * Channel:
 *   - `com.surviveTheTalk.client/onset_rms` (EventChannel) — Double RMS values
 *     streamed on the platform main thread, at most one delivery queued at a
 *     time (Story 7.6 flood bound).
 *
 * **Lifetime**: identical to [AudioClockChannel] — attach on [onListen]
 * (Dart subscription start), detach on [onCancel]. RMS only runs while a call
 * screen is actively subscribed.
 *
 * **Story 7.6 hardening (AC2/AC8):**
 *   - the attach RETRIES on a bounded schedule when the WebRTC record path
 *     isn't warm yet at [onListen] (`sharedSingleton`/adapter still null), so a
 *     cold record path no longer permanently kills the tap; a reflection error
 *     (SDK rename) is treated as permanent and not retried. Both terminal
 *     outcomes log LOUD ("onset tap UNAVAILABLE …") — a silent failure here
 *     corrupts DATA (the hesitation number), not just visuals.
 *   - [rmsOf] honors `channelCount` (interleaved stereo is averaged to mono, not
 *     read with a per-channel bias that would skew the SNR the Dart meter
 *     computes).
 *   - the per-frame delivery is BOUNDED: at most one main-thread message is
 *     queued at a time, so the ~100 Hz callback can't pile up a backlog and
 *     starve the main thread; under backpressure frames coalesce to the PEAK
 *     RMS since the last delivery (cadence throttled, onset energy NEVER hidden).
 *     A delivery that lands after [onCancel] is a no-op (the sink is null-checked).
 */
class AudioCaptureChannel {
    companion object {
        private const val TAG = "AudioCaptureChannel"
        private const val EVENT_CHANNEL = "com.surviveTheTalk.client/onset_rms"
        private const val BYTES_PER_SAMPLE = 2 // PCM16

        // Story 7.6 — bounded retry for a cold record path. ~25 × 150 ms ≈ 3.75 s
        // covers the WebRTC capture path warming up after the call connects.
        private const val MAX_ATTACH_ATTEMPTS = 25
        private const val ATTACH_RETRY_MS = 150L
    }

    private enum class AttachResult { ATTACHED, NOT_READY, FAILED }

    private lateinit var eventChannel: EventChannel
    private val mainHandler = Handler(Looper.getMainLooper())

    private var attachedCallback: JavaAudioDeviceModule.SamplesReadyCallback? = null
    private var adapter: RecordSamplesReadyCallbackAdapter? = null
    private var attachAttempts = 0

    @Volatile private var eventSink: EventChannel.EventSink? = null

    // Story 7.6 flood bound: a single in-flight main-thread delivery + the PEAK
    // RMS accumulated since the last one. `pendingPeakRms` is written on the
    // WebRTC audio thread and read on the main thread, guarded by `rmsLock`.
    private val deliverScheduled = AtomicBoolean(false)
    private val rmsLock = Any()
    private var pendingPeakRms = 0.0

    private val deliverRunnable = Runnable {
        val peak: Double
        synchronized(rmsLock) {
            peak = pendingPeakRms
            pendingPeakRms = 0.0
        }
        // Allow the next frame to schedule AFTER we've drained the peak, so no
        // frame's contribution is lost between the drain and the reset.
        deliverScheduled.set(false)
        val sink = eventSink ?: return@Runnable
        try {
            sink.success(peak)
        } catch (t: Throwable) {
            Log.d(TAG, "sink.success after cancel: ${t.message}")
        }
    }

    fun startListening(messenger: BinaryMessenger) {
        eventChannel = EventChannel(messenger, EVENT_CHANNEL)
        eventChannel.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                eventSink = events
                attachAttempts = 0
                deliverScheduled.set(false)
                Log.i(TAG, "onset_rms EventChannel onListen")
                tryAttachCallback()
            }

            override fun onCancel(arguments: Any?) {
                Log.i(TAG, "onset_rms EventChannel onCancel")
                eventSink = null
                attachAttempts = 0
                mainHandler.removeCallbacksAndMessages(null)
                deliverScheduled.set(false)
                detachCallback()
            }
        })
    }

    fun stopListening() {
        if (::eventChannel.isInitialized) {
            eventChannel.setStreamHandler(null)
        }
        eventSink = null
        attachAttempts = 0
        mainHandler.removeCallbacksAndMessages(null)
        deliverScheduled.set(false)
        detachCallback()
    }

    /**
     * Attempt the reflection attach; on a not-yet-warm record path, re-post on a
     * bounded schedule until it warms (Story 7.6 AC2). A reflection FAILURE
     * (SDK rename) is permanent — logged once, not retried.
     */
    private fun tryAttachCallback() {
        if (attachedCallback != null) return
        if (eventSink == null) return // not subscribed — nothing to attach for
        when (attemptAttach()) {
            AttachResult.ATTACHED -> {
                if (attachAttempts > 0) {
                    Log.i(
                        TAG,
                        "onset tap attached on retry #$attachAttempts " +
                            "(record path warmed late)"
                    )
                }
                attachAttempts = 0
            }
            AttachResult.FAILED -> {
                // A reflection error (a flutter_webrtc field rename) won't fix
                // itself by waiting — don't burn retries on it.
                Log.w(
                    TAG,
                    "onset tap UNAVAILABLE (reflection failed) — server " +
                        "fallback covers hesitations"
                )
                attachAttempts = 0
            }
            AttachResult.NOT_READY -> {
                attachAttempts++
                if (attachAttempts >= MAX_ATTACH_ATTEMPTS) {
                    Log.w(
                        TAG,
                        "onset tap UNAVAILABLE after $attachAttempts attempts " +
                            "(record path never warmed) — server fallback " +
                            "covers hesitations"
                    )
                    attachAttempts = 0
                } else {
                    mainHandler.postDelayed({ tryAttachCallback() }, ATTACH_RETRY_MS)
                }
            }
        }
    }

    private fun attemptAttach(): AttachResult {
        return try {
            val plugin = FlutterWebRTCPlugin.sharedSingleton ?: run {
                Log.d(TAG, "record path not warm yet: sharedSingleton null")
                return AttachResult.NOT_READY
            }
            val mchField = plugin.javaClass.getDeclaredField("methodCallHandler")
            mchField.isAccessible = true
            val mch = mchField.get(plugin) ?: run {
                Log.d(TAG, "record path not warm yet: methodCallHandler null")
                return AttachResult.NOT_READY
            }
            // The record adapter field is private on MethodCallHandlerImpl —
            // same reflection shape as AudioClockChannel's playback field.
            val adapterField = mch.javaClass.getDeclaredField("recordSamplesReadyCallbackAdapter")
            adapterField.isAccessible = true
            val a = adapterField.get(mch) as? RecordSamplesReadyCallbackAdapter ?: run {
                Log.d(TAG, "record path not warm yet: recordSamplesReadyCallbackAdapter null")
                return AttachResult.NOT_READY
            }
            val cb = object : JavaAudioDeviceModule.SamplesReadyCallback {
                override fun onWebRtcAudioRecordSamplesReady(
                    samples: JavaAudioDeviceModule.AudioSamples
                ) {
                    if (samples.audioFormat != AudioFormat.ENCODING_PCM_16BIT) return
                    val channels = samples.channelCount
                    if (channels <= 0) return
                    if (eventSink == null) return // not subscribed — drop, don't schedule
                    val rms = rmsOf(samples.data, channels)
                    synchronized(rmsLock) {
                        if (rms > pendingPeakRms) pendingPeakRms = rms
                    }
                    // Bound the ~100 Hz flood: only ONE main-thread delivery is
                    // queued at a time (no backlog → no starvation). Under
                    // backpressure later frames fold into the PEAK above, so the
                    // onset energy is preserved — only the cadence is throttled.
                    if (deliverScheduled.compareAndSet(false, true)) {
                        mainHandler.post(deliverRunnable)
                    }
                }
            }
            a.addCallback(cb)
            adapter = a
            attachedCallback = cb
            Log.i(TAG, "AudioCaptureChannel attached to flutter_webrtc record callback")
            AttachResult.ATTACHED
        } catch (e: Throwable) {
            Log.w(TAG, "Failed to attach record callback (reflection): ${e.message}", e)
            AttachResult.FAILED
        }
    }

    /**
     * Root-mean-square of a little-endian interleaved PCM16 byte buffer,
     * averaged across [channelCount] (Story 7.6 — a stereo capture must be
     * read as a mono mix, not with a per-channel bias that would skew the SNR
     * the Dart meter computes). For mono this is identical to the per-sample RMS.
     */
    private fun rmsOf(data: ByteArray, channelCount: Int): Double {
        val channels = if (channelCount > 0) channelCount else 1
        val bytesPerFrame = BYTES_PER_SAMPLE * channels
        var sumSq = 0.0
        var frameCount = 0
        var i = 0
        while (i <= data.size - bytesPerFrame) {
            var frameSum = 0
            var c = 0
            while (c < channels) {
                val off = i + c * BYTES_PER_SAMPLE
                val lo = data[off].toInt() and 0xFF
                val hi = data[off + 1].toInt() // sign-extended high byte
                frameSum += (hi shl 8) or lo
                c++
            }
            val mono = frameSum.toDouble() / channels
            sumSq += mono * mono
            frameCount++
            i += bytesPerFrame
        }
        return if (frameCount > 0) sqrt(sumSq / frameCount) else 0.0
    }

    private fun detachCallback() {
        val a = adapter
        val cb = attachedCallback
        if (a != null && cb != null) {
            try {
                a.removeCallback(cb)
            } catch (e: Throwable) {
                Log.w(TAG, "removeCallback threw: ${e.message}")
            }
        }
        adapter = null
        attachedCallback = null
    }
}
