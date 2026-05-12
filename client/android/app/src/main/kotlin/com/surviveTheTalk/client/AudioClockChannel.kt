package com.surviveTheTalk.client

import android.media.AudioFormat
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.cloudwebrtc.webrtc.FlutterWebRTCPlugin
import com.cloudwebrtc.webrtc.audio.PlaybackSamplesReadyCallbackAdapter
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import org.webrtc.audio.JavaAudioDeviceModule

/**
 * Story 6.3b — Android-side viseme generator that streams Rive viseme
 * ids to Flutter from the PCM bytes about to be played by the WebRTC
 * AudioTrack.
 *
 * **Why this design**: the previous architecture sent visemes from the
 * server over the WebRTC data channel; SCTP slow-start added 2-3 s of
 * latency on cellular, desyncing the mouth from the audio. The
 * industry-standard fix (Apple Memoji, Snapchat, NVIDIA Audio2Face) is
 * to derive visemes from the audio itself, on the same thread that is
 * about to hand bytes to the speaker. Sync is then a property of the
 * architecture — not a tuning constant.
 *
 * **Wiring**:
 *   1. Hook into flutter_webrtc's [PlaybackSamplesReadyCallbackAdapter]
 *      (reflection — the adapter field is private).
 *   2. On each chunk, hand bytes to [FormantVisemeAnalyzer], which
 *      returns one of the 12 Rive viseme ids (or null if nothing
 *      changed since the previous chunk).
 *   3. Push non-null ids to Dart via [EventChannel] on the main thread.
 *
 * Channel:
 *   - `com.surviveTheTalk.client/viseme_events` (EventChannel) — int
 *     viseme ids streamed on the platform main thread.
 *
 * **Lifetime**: the playback callback is attached on every [onListen]
 * (Dart subscription start) and detached on every [onCancel] (Dart
 * subscription end). FFT analysis only runs while a call screen is
 * actively listening — no wasted CPU between calls or during system
 * sounds.
 *
 * If the reflection attach fails (a future flutter_webrtc SDK rename),
 * Dart receives no events and the mouth stays at REST — no crash. The
 * call still works for audio + emotion.
 */
class AudioClockChannel {
    companion object {
        private const val TAG = "AudioClockChannel"
        private const val EVENT_CHANNEL = "com.surviveTheTalk.client/viseme_events"
        private const val BYTES_PER_SAMPLE = 2 // PCM16
    }

    private lateinit var eventChannel: EventChannel
    private val mainHandler = Handler(Looper.getMainLooper())

    private var attachedCallback: JavaAudioDeviceModule.PlaybackSamplesReadyCallback? = null
    private var adapter: PlaybackSamplesReadyCallbackAdapter? = null

    private val analyzer: VisemeAnalyzer = FormantVisemeAnalyzer()

    @Volatile private var eventSink: EventChannel.EventSink? = null

    fun startListening(messenger: BinaryMessenger) {
        eventChannel = EventChannel(messenger, EVENT_CHANNEL)
        eventChannel.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                eventSink = events
                Log.i(TAG, "viseme EventChannel onListen")
                // Dart subscribes when the call screen mounts — attach
                // the native playback callback so analysis runs only for
                // the duration of this subscription.
                tryAttachCallback()
            }

            override fun onCancel(arguments: Any?) {
                Log.i(TAG, "viseme EventChannel onCancel")
                eventSink = null
                // Drop any queued sink.success(...) posts that haven't
                // executed yet — they would otherwise hit a closed sink
                // moments after this returns.
                mainHandler.removeCallbacksAndMessages(null)
                // Stop the FFT entirely between calls. The callback is
                // re-attached lazily on the next onListen.
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
            // The adapter field is private on MethodCallHandlerImpl — use
            // getDeclaredField + setAccessible, mirroring the line above.
            // (getField would only return public fields and throws
            // NoSuchFieldException here.)
            val adapterField = mch.javaClass.getDeclaredField("playbackSamplesReadyCallbackAdapter")
            adapterField.isAccessible = true
            val a = adapterField.get(mch) as? PlaybackSamplesReadyCallbackAdapter ?: run {
                Log.w(TAG, "playbackSamplesReadyCallbackAdapter is null or wrong type")
                return false
            }
            val cb = object : JavaAudioDeviceModule.PlaybackSamplesReadyCallback {
                override fun onWebRtcAudioTrackSamplesReady(
                    samples: JavaAudioDeviceModule.AudioSamples
                ) {
                    // Format guard: the analyzer assumes 16-bit PCM
                    // little-endian. Bail on anything else so a future
                    // SDK switch to PCM_FLOAT produces silence rather
                    // than garbage visemes.
                    if (samples.audioFormat != AudioFormat.ENCODING_PCM_16BIT) {
                        Log.w(
                            TAG,
                            "Unsupported audioFormat ${samples.audioFormat} — expected ENCODING_PCM_16BIT (${AudioFormat.ENCODING_PCM_16BIT})"
                        )
                        return
                    }
                    // Divide-by-zero / nonsense-stride guard. Should never
                    // happen on a real stream but cheap to defend.
                    if (samples.channelCount <= 0) return

                    val frames = samples.data.size /
                            (samples.channelCount * BYTES_PER_SAMPLE)
                    val v = try {
                        analyzer.analyze(
                            samples.data,
                            frames,
                            samples.channelCount,
                            samples.sampleRate,
                        )
                    } catch (t: Throwable) {
                        Log.e(TAG, "analyzer threw: ${t.message}", t)
                        null
                    }
                    if (v != null) {
                        val sink = eventSink
                        if (sink != null) {
                            // EventChannel sinks must be invoked on the
                            // platform main thread per Flutter contract.
                            // The sink may have been cancelled between
                            // this post and its execution — wrap to
                            // swallow any IllegalStateException raised
                            // by Flutter's binary messenger. onCancel
                            // also calls removeCallbacksAndMessages so
                            // most queued posts never run; this catch
                            // covers the in-flight remainder.
                            mainHandler.post {
                                try {
                                    sink.success(v)
                                } catch (t: Throwable) {
                                    Log.d(TAG, "sink.success after cancel: ${t.message}")
                                }
                            }
                        }
                    }
                }
            }
            a.addCallback(cb)
            adapter = a
            attachedCallback = cb
            Log.i(TAG, "AudioClockChannel attached to flutter_webrtc playback callback")
            return true
        } catch (e: Throwable) {
            Log.e(TAG, "Failed to attach playback callback: ${e.message}", e)
            return false
        }
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
        analyzer.reset()
    }
}
