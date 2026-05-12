package com.surviveTheTalk.client

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {
    private val audioClock = AudioClockChannel()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // Story 6.3b — native audio playback clock channel for lip-sync
        // alignment. See AudioClockChannel.kt for rationale.
        audioClock.startListening(flutterEngine.dartExecutor.binaryMessenger)
    }

    override fun onDestroy() {
        audioClock.stopListening()
        super.onDestroy()
    }
}
