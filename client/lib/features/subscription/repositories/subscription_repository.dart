import '../../../core/api/api_client.dart';
import '../models/subscription_status.dart';

/// Talks to `POST /subscription/verify`. Mirrors `ScenariosRepository` /
/// `CallRepository`: takes an [ApiClient], extracts the `{data}` envelope, lets
/// [ApiException] propagate (the bloc classifies it).
class SubscriptionRepository {
  final ApiClient _apiClient;

  SubscriptionRepository(this._apiClient);

  /// Send the store verification artifact to the server. `verificationData` is
  /// the unified `serverVerificationData` (iOS JWS / Android purchaseToken).
  /// Returns the parsed tier; throws `ApiException` on any non-2xx (the bloc
  /// maps `PURCHASE_INVALID` / `SUBSCRIPTION_UNAVAILABLE` to a failed state).
  Future<SubscriptionStatus> verifyPurchase({
    required String platform,
    required String productId,
    required String verificationData,
  }) async {
    final response = await _apiClient.post<Map<String, dynamic>>(
      '/subscription/verify',
      data: <String, dynamic>{
        'platform': platform,
        'product_id': productId,
        'verification_data': verificationData,
      },
    );
    final data = response.data!['data'] as Map<String, dynamic>;
    return SubscriptionStatus.fromJson(data);
  }
}
