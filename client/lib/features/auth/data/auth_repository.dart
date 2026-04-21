import '../../../core/api/api_client.dart';
import 'auth_result.dart';

class AuthRepository {
  final ApiClient _apiClient;

  AuthRepository(this._apiClient);

  Future<void> requestCode(String email) async {
    await _apiClient.post('/auth/request-code', data: {'email': email});
  }

  Future<AuthResult> verifyCode(String email, String code) async {
    final response = await _apiClient.post<Map<String, dynamic>>(
      '/auth/verify-code',
      data: {'email': email, 'code': code},
    );
    final data = response.data!['data'] as Map<String, dynamic>;
    return AuthResult.fromJson(data);
  }
}
