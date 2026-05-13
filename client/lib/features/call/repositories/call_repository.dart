import '../../../core/api/api_client.dart';
import '../models/call_session.dart';
import '../models/end_call_result.dart';

class CallRepository {
  final ApiClient _apiClient;

  CallRepository(this._apiClient);

  Future<CallSession> initiateCall({required String scenarioId}) async {
    final response = await _apiClient.post<Map<String, dynamic>>(
      '/calls/initiate',
      data: <String, dynamic>{'scenario_id': scenarioId},
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
}
