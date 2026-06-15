package com.surviveTheTalk.client

import android.media.AudioFormat
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.cloudwebrtc.webrtc.FlutterWebRTCPlugin
import com.cloudwebrtc.webrtc.audio.RecordSamplesReadyCallbackAdapter
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import org.webrtc.audio.JavaAudioDeviceModule
import kotlin.math.sqrt

/**
 * Story 7.5 (D3-c) — Android-side mic RMS tap that streams short-window
 * loudness values to Flutter's [com.surviveTheTalk.client.HesitationMeter] so it
 * can detect the user's speech ONSET on-device (the second boundary of a
 * hesitation gap; the first is the character-audio-end the viseme stack already
 * provides). Onset accuracy matters; word accuracy does not — so a cheap RMS is
 * enough, and the noise-robustness lives in the Dart meter (adaptive floor +
 * SNR), NOT in the cleanliness of this signal.
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
 *     streamed on the platform main thread, one per ~10 ms capture frame.
 *
 * **Lifetime**: identical to [AudioClockChannel] — attach on [onListen]
 * (Dart subscription start), detach on [onCancel]. RMS only runs while a call
 * screen is actively subscribed.
 *
 * If the reflection attach fails (a future flutter_webrtc SDK rename), Dart
 * receives no events; the meter then never fires and the SERVER hesitation
 * observer covers the call — no crash, no garbage gap.
 */
class AudioCaptureChannel {
    companion object {
        private const val TAG = "AudioCaptureChannel"
        private const val EVENT_CHANNEL = "com.surviveTheTalk.client/onset_rms"
        private const val BYTES_PER_SAMPLE = 2 // PCM16
    }

    private lateinit var eventChannel: EventChannel
    private val mainHandler = Handler(Looper.getMainLooper())

    private var attachedCallback: JavaAudioDeviceModule.SamplesReadyCallback? = null
    private var adapter: RecordSamplesReadyCallbackAdapter? = null

    @Volatile private var eventSink: EventChannel.EventSink? = null

    fun startListening(messenger: BinaryMessenger) {
        eventChannel = EventChannel(messenger, EVENT_CHANNEL)
        eventChannel.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                eventSink = events
                Log.i(TAG, "onset_rms EventChannel onListen")
                tryAttachCallback()
            }

            override fun onCancel(arguments: Any?) {
                Log.i(TAG, "onset_rms EventChannel onCancel")
                eventSink = null
                mainHandler.removeCallbacksAndMessages(null)
                detachCallback()
            }
        })
    }

    fun stopListening() {
        if (::eventChannel.isInitialized) {
            eventChannel.setStreamHandler(null)
        }
        eventSink = null
        mainHandler.removeCallbacksAndMessages(null)
        detachCallback()
    }

    private fun tryAttachCallback(): Boolean {
        if (attachedCallback != null) return true
        try {
            val plugin = FlutterWebRTCPlugin.sharedSingleton ?: run {
                Log.w(TAG, "FlutterWebRTCPlugin.sharedSingleton is null — not yet initialized")
                return false
            }
            val mchField = plugin.javaClass.getDeclaredField("methodCallHandler")
            mchField.isAccessible = true
            val mch = mchField.get(plugin) ?: run {
                Log.w(TAG, "methodCallHandler field is null")
                return false
            }
            // The record adapter field is private on MethodCallHandlerImpl —
            // same reflection shape as AudioClockChannel's playback field.
            val adapterField = mch.javaClass.getDeclaredField("recordSamplesReadyCallbackAdapter")
            adapterField.isAccessible = true
            val a = adapterField.get(mch) as? RecordSamplesReadyCallbackAdapter ?: run {
                Log.w(TAG, "recordSamplesReadyCallbackAdapter is null or wrong type")
                return false
            }
            val cb = object : JavaAudioDeviceModule.SamplesReadyCallback {
                override fun onWebRtcAudioRecordSamplesReady(
                    samples: JavaAudioDeviceModule.AudioSamples
                ) {
                    if (samples.audioFormat != AudioFormat.ENCODING_PCM_16BIT) return
                    if (samples.channelCount <= 0) return
                    val rms = rmsOf(samples.data)
                    val sink = eventSink ?: return
                    mainHandler.post {
                        try {
                            sink.success(rms)
                        } catch (t: Throwable) {
                            Log.d(TAG, "sink.success after cancel: ${t.message}")
                        }
                    }
                }
            }
            a.addCallback(cb)
            adapter = a
            attachedCallback = cb
            Log.i(TAG, "AudioCaptureChannel attached to flutter_webrtc record callback")
            return true
        } catch (e: Throwable) {
            Log.e(TAG, "Failed to attach record callback: ${e.message}", e)
            return false
        }
    }

    /** Root-mean-square of a little-endian PCM16 byte buffer. */
    private fun rmsOf(data: ByteArray): Double {
        var sumSq = 0.0
        var count = 0
        var i = 0
        val limit = data.size - 1
        while (i < limit) {
            val lo = data[i].toInt() and 0xFF
            val hi = data[i + 1].toInt() // sign-extended high byte
            val sample = (hi shl 8) or lo
            sumSq += (sample * sample).toDouble()
            count++
            i += BYTES_PER_SAMPLE
        }
        return if (count > 0) sqrt(sumSq / count) else 0.0
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
