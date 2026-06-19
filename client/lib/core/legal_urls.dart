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

  static const String privacyPolicy = '${ApiClient.baseUrl}/legal/privacy';
  static const String termsOfService = '${ApiClient.baseUrl}/legal/terms';
}
