import 'package:flutter/foundation.dart';

import 'api/api_client.dart';

/// Single source of truth for the hosted legal-page URLs (Story 10.1, AC6).
///
/// Derived from [ApiClient.baseUrl] so Story 10.2 flips IP → HTTPS domain in ONE
/// place. These point at the public, unauthenticated `GET /legal/*` routes
/// (`server/api/routes_legal.py`); the app opens them in an external browser
/// (it does NOT render legal text in-app).
@immutable
class LegalUrls {
  const LegalUrls._();

  /// [ApiClient.baseUrl] with any trailing slash stripped, so a future base
  /// that ends in `/` can't yield a double slash (`//legal/...`) — the deferred
  /// Story 10.1 review item. Kept as the single derived source.
  static String get _base => ApiClient.baseUrl.endsWith('/')
      ? ApiClient.baseUrl.substring(0, ApiClient.baseUrl.length - 1)
      : ApiClient.baseUrl;

  static String get privacyPolicy => '$_base/legal/privacy';
  static String get termsOfService => '$_base/legal/terms';
}
