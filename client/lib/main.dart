import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:livekit_client/livekit_client.dart';

import 'config.dart';

void main() {
  runApp(const SurviveTheTalkApp());
}

class SurviveTheTalkApp extends StatelessWidget {
  const SurviveTheTalkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SurviveTheTalk',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF1E1F23),
        colorScheme: const ColorScheme.dark(
          surface: Color(0xFF1E1F23),
          primary: Colors.green,
        ),
        textTheme: const TextTheme(
          bodyMedium: TextStyle(color: Color(0xFFF0F0F0)),
        ),
      ),
      home: const CallScreen(),
    );
  }
}

enum CallState { idle, connecting, connected, error }

class CallScreen extends StatefulWidget {
  const CallScreen({super.key});

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  CallState _callState = CallState.idle;
  String _errorMessage = '';
  Room? _room;
  EventsListener<RoomEvent>? _listener;
  Timer? _durationTimer;
  int _callDurationSeconds = 0;

  @override
  void dispose() {
    _durationTimer?.cancel();
    _listener?.dispose();
    _room?.dispose();
    super.dispose();
  }

  Future<void> _startCall() async {
    if (_callState != CallState.idle) return;

    setState(() {
      _callState = CallState.connecting;
      _errorMessage = '';
    });

    try {
      final response = await http
          .post(Uri.parse('$serverUrl/connect'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw Exception('Server returned ${response.statusCode}');
      }

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final token = data['token'] as String;
      final livekitUrl = data['livekit_url'] as String;

      final room = Room(
        roomOptions: const RoomOptions(
          adaptiveStream: true,
          dynacast: true,
        ),
      );
      final listener = room.createListener();

      try {
        listener.on<RoomDisconnectedEvent>((_) {
          if (mounted) {
            unawaited(_endCall());
          }
        });

        await room.connect(livekitUrl, token);

        await room.localParticipant?.setMicrophoneEnabled(true);
      } catch (_) {
        await listener.dispose();
        await room.dispose();
        rethrow;
      }

      _room = room;
      _listener = listener;
      _callDurationSeconds = 0;
      _durationTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) {
          setState(() {
            _callDurationSeconds++;
          });
        }
      });

      setState(() {
        _callState = CallState.connected;
      });
    } catch (e) {
      setState(() {
        _callState = CallState.error;
        _errorMessage = e.toString();
      });
    }
  }

  Future<void> _endCall() async {
    _durationTimer?.cancel();
    _durationTimer = null;

    final listener = _listener;
    final room = _room;
    _listener = null;
    _room = null;

    try {
      await room?.disconnect();
    } finally {
      await listener?.dispose();
      await room?.dispose();

      if (mounted) {
        setState(() {
          _callState = CallState.idle;
          _callDurationSeconds = 0;
        });
      }
    }
  }

  String _formatDuration(int totalSeconds) {
    final minutes = totalSeconds ~/ 60;
    final seconds = totalSeconds % 60;
    return '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: switch (_callState) {
          CallState.idle => _buildIdleState(),
          CallState.connecting => _buildConnectingState(),
          CallState.connected => _buildConnectedState(),
          CallState.error => _buildErrorState(),
        },
      ),
    );
  }

  Widget _buildIdleState() {
    return FloatingActionButton.large(
      onPressed: _startCall,
      backgroundColor: Colors.green,
      child: const Icon(Icons.phone, size: 36),
    );
  }

  Widget _buildConnectingState() {
    return const Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        CircularProgressIndicator(),
        SizedBox(height: 16),
        Text(
          'Connecting...',
          style: TextStyle(color: Color(0xFFF0F0F0), fontSize: 16),
        ),
      ],
    );
  }

  Widget _buildConnectedState() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          _formatDuration(_callDurationSeconds),
          style: const TextStyle(
            color: Color(0xFFF0F0F0),
            fontSize: 48,
            fontWeight: FontWeight.w300,
          ),
        ),
        const SizedBox(height: 32),
        FloatingActionButton.large(
          onPressed: _endCall,
          backgroundColor: Colors.red,
          child: const Icon(Icons.phone_disabled, size: 36),
        ),
      ],
    );
  }

  Widget _buildErrorState() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.error_outline, color: Colors.red, size: 48),
        const SizedBox(height: 16),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32),
          child: Text(
            _errorMessage,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Color(0xFFF0F0F0)),
          ),
        ),
        const SizedBox(height: 24),
        ElevatedButton(
          onPressed: () {
            setState(() {
              _callState = CallState.idle;
              _errorMessage = '';
            });
          },
          child: const Text('Retry'),
        ),
      ],
    );
  }
}
