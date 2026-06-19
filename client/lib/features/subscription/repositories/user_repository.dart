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

  /// Permanently delete the caller's account and all their data (Story 10.1,
  /// GDPR Art 17 — `DELETE /user/me`). Throws `ApiException` on any non-2xx so
  /// the caller can surface an inline failure and keep the user signed in.
  Future<void> deleteAccount() async {
    await _apiClient.delete<Map<String, dynamic>>('/user/me');
  }
}
