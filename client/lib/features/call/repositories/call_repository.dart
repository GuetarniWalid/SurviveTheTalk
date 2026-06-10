import '../../../core/api/api_client.dart';
import '../models/call_session.dart';
import '../models/end_call_result.dart';

class CallRepository {
  final ApiClient _apiClient;

  CallRepository(this._apiClient);

  Future<CallSession> initiateCall({
    required String scenarioId,
    String? difficulty,
  }) async {
    // Story 6.19 — `difficulty` is the learner's global hub preference
    // (easy/medium/hard). Optional: only included in the body when set, so the
    // one-time onboarding `incoming_call` flow (which has no preference yet)
    // keeps posting just `{scenario_id}` and the server falls back to the
    // scenario's authored difficulty (server AC7).
    final body = <String, dynamic>{'scenario_id': scenarioId};
    if (difficulty != null) body['difficulty'] = difficulty;
    final response = await _apiClient.post<Map<String, dynamic>>(
      '/calls/initiate',
      data: body,
    );
    final data = response.data!['data'] as Map<String, dynamic>;
    return CallSession.fromJson(data);
  }

  // Story 6.5 — POST /calls/{call_id}/end with the canonical reason. The
  // server flips status → completed (or 'failed' if gifted), computes
  // duration_sec, returns `was_gifted` + `gifts_remaining_today` so the
  // bloc can drive the post-call notice screen (Déviation #27).
  //
  // CallBloc invokes this fire-and-forget via _endCallSilently so any
  // failure (server down, 422 from a future reason mismatch, network
  // timeout) does not surface to the UI — the user already committed to
  // leaving the call.
  //
  // Returns the parsed `EndCallResult`. The retry service uses only the
  // success/failure signal (a thrown exception means "queue for retry");
  // the bloc's exit-path handler uses the gift fields to decide whether
  // to push the notice screen.
  Future<EndCallResult> endCall({
    required int callId,
    required String reason,
  }) async {
    final response = await _apiClient.post<Map<String, dynamic>>(
      '/calls/$callId/end',
      data: <String, dynamic>{'reason': reason},
    );
    final data = response.data!['data'] as Map<String, dynamic>;
    return EndCallResult.fromJson(data);
  }

  // Story 7.2 — GET /debriefs/{call_id}. Returns the unwrapped `data`
  // block (the debrief JSON the Story 7.3 screen will render). Throws the
  // mapped `ApiException` on any non-2xx: the Call Ended overlay treats
  // `code == 'DEBRIEF_NOT_READY'` as "still generating → poll again" and
  // every other failure as terminal (give up silently, no error chrome —
  // UX-DR6).
  Future<Map<String, dynamic>> fetchDebrief({required int callId}) async {
    final response = await _apiClient.get<Map<String, dynamic>>(
      '/debriefs/$callId',
    );
    return response.data!['data'] as Map<String, dynamic>;
  }
}
