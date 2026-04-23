import '../../../core/api/api_client.dart';
import '../models/call_session.dart';

class CallRepository {
  final ApiClient _apiClient;

  CallRepository(this._apiClient);

  Future<CallSession> initiateCall() async {
    final response = await _apiClient.post<Map<String, dynamic>>(
      '/calls/initiate',
      data: const <String, dynamic>{},
    );
    final data = response.data!['data'] as Map<String, dynamic>;
    return CallSession.fromJson(data);
  }
}
