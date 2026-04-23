import 'package:client/features/call/models/call_session.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('CallSession', () {
    test('fromJson maps snake_case payload to camelCase fields', () {
      final session = CallSession.fromJson(const {
        'call_id': 42,
        'room_name': 'call-abc',
        'token': 'user-token',
        'livekit_url': 'wss://livekit.example.com',
      });

      expect(session.callId, 42);
      expect(session.roomName, 'call-abc');
      expect(session.token, 'user-token');
      expect(session.livekitUrl, 'wss://livekit.example.com');
    });
  });
}
