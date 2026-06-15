package com.surviveTheTalk.client

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {
    private val audioClock = AudioClockChannel()
    private val audioCapture = AudioCaptureChannel()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // Story 6.3b — native audio playback clock channel for lip-sync
        // alignment. See AudioClockChannel.kt for rationale.
        audioClock.startListening(flutterEngine.dartExecutor.binaryMessenger)
        // Story 7.5 (D3-c) — native record-side mic RMS tap feeding the
        // on-device hesitation onset meter. See AudioCaptureChannel.kt.
        audioCapture.startListening(flutterEngine.dartExecutor.binaryMessenger)
    }

    override fun onDestroy() {
        audioClock.stopListening()
        audioCapture.stopListening()
        super.onDestroy()
    }
}
