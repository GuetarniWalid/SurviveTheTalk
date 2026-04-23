class CallSession {
  final int callId;
  final String roomName;
  final String token;
  final String livekitUrl;

  const CallSession({
    required this.callId,
    required this.roomName,
    required this.token,
    required this.livekitUrl,
  });

  factory CallSession.fromJson(Map<String, dynamic> json) {
    return CallSession(
      callId: json['call_id'] as int,
      roomName: json['room_name'] as String,
      token: json['token'] as String,
      livekitUrl: json['livekit_url'] as String,
    );
  }
}
