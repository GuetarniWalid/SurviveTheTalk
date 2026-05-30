import 'package:client/features/call/services/env_warning_payload.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // Story 6.11 — EnvWarningPayload is a plain value class; the wire-format
  // parse lives in DataChannelHandler (covered in
  // data_channel_handler_test.dart). These pin the shape consumers rely on.
  test('holds reason + detectedSpeakers', () {
    const payload = EnvWarningPayload(
      reason: 'background_voice',
      detectedSpeakers: 2,
    );
    expect(payload.reason, 'background_voice');
    expect(payload.detectedSpeakers, 2);
  });
}
