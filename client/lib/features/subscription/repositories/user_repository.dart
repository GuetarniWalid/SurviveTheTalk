import '../../../core/api/api_client.dart';
import '../models/user_profile.dart';

/// Talks to `GET /user/profile` (Story 8.3). Mirrors `ScenariosRepository` /
/// `SubscriptionRepository`: takes an [ApiClient], extracts the `{data}`
/// envelope, lets `ApiException` propagate (the cubit maps it to an error state).
class UserRepository {
  final ApiClient _apiClient;

  UserRepository(this._apiClient);

  /// Fetch the caller's subscription status (tier, calls remaining, expiry).
  /// Throws `ApiException` on any non-2xx; `FormatException` on a malformed
  /// payload (`UserProfile.fromJson`).
  Future<UserProfile> getProfile() async {
    final response = await _apiClient.get<Map<String, dynamic>>('/user/profile');
    final data = response.data!['data'] as Map<String, dynamic>;
    return UserProfile.fromJson(data);
  }
}
