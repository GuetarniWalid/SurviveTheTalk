import 'package:dio/dio.dart';

/// Callback fired the FIRST time a 401 lands in any Dio request.
/// Returns a `Future` so the wiring can await JWT clearing + bloc
/// dispatch + toast presentation before letting the request error
/// propagate to the caller's bloc.
typedef OnUnauthorizedCallback = Future<void> Function();

/// Dio interceptor that closes the Story 5.5 `AUTH_UNAUTHORIZED`
/// silent-loop gap (`deferred-work.md` `MUST-FIX BEFORE MVP LAUNCH`).
///
/// Story 6.13 AC4 (2026-05-26) — when ANY backend endpoint returns
/// HTTP 401 (JWT expired or invalidated server-side), the previous
/// behaviour was: every feature bloc's `_classifyApiCode` mapped the
/// 401 to a generic "try again" error; retrying did nothing because
/// the token was dead; the user got stuck. This interceptor catches
/// the 401 BEFORE the bloc's error handler runs and:
///
///   1. Fires [globalHandler] once — bootstrap wires it to clear
///      the JWT from `flutter_secure_storage`, dispatch
///      `ResetAuthEvent` so `AuthBloc` emits `AuthInitial` (which
///      `GoRouter`'s `refreshListenable` observes and redirects to
///      `/login`), and show a `AppToast` with "Session expired,
///      please sign in again".
///   2. Lets the original `DioException` continue propagating so
///      any in-flight bloc still receives an error (idempotent —
///      duplicate 401s during the navigation window don't re-fire
///      the handler thanks to the [_handling] re-entry guard).
///
/// **Why a cross-cutting interceptor instead of per-bloc handling:**
/// the alternative (audit every `_classifyApiCode` site + add an
/// `AUTH_REQUIRED` slot to each feature's error state) would mean
/// 20+ touch points; one missed feature leaks the bug. The Dio
/// interceptor is one wiring point and runs for every endpoint
/// automatically. See `deferred-work.md` MUST-FIX-BEFORE-MVP-LAUNCH
/// entry for the original analysis.
class AuthInterceptor extends Interceptor {
  /// Global one-shot 401 handler. `null` in tests / pre-bootstrap.
  /// Set by `main.bootstrap()` after `TokenStorage` + `AuthBloc` are
  /// constructed. Public-static-mutable is intentional: every
  /// `ApiClient` instance in the app must share the same handler so
  /// a 401 on any endpoint converges on the same auth-reset flow,
  /// regardless of which feature constructed the client.
  static OnUnauthorizedCallback? globalHandler;

  /// Re-entry guard so concurrent 401s don't fire the handler multiple
  /// times.
  ///
  /// **Static, not per-instance** (Story 6.13 review 2026-05-27): the app
  /// builds a fresh `ApiClient` — and therefore a fresh `AuthInterceptor`
  /// — per feature/repository (9 construction sites). A per-instance guard
  /// let two concurrent 401s on DIFFERENT clients (e.g. a scenarios fetch
  /// + a call-end POST both racing a just-expired JWT) each pass their own
  /// latch and each invoke [globalHandler] → stacked "Session expired"
  /// toasts + double `ResetAuthEvent`. A static latch makes the dedup span
  /// every client.
  static bool _handling = false;

  /// Clears the static re-entry latch.
  ///
  /// Also cleared automatically on the next successful authenticated
  /// response (see [onResponse]). This reset is what closes the Story 5.5
  /// silent loop for REPEAT expiries: without it the latch would stay set
  /// for the whole app lifetime, so after a re-login a later token expiry
  /// would be silently swallowed — re-introducing the exact bug AC4 exists
  /// to fix.
  static void reset() {
    _handling = false;
  }

  /// Reset for tests — every test should start with a fresh
  /// re-entry guard so prior tests' 401 paths don't leak.
  void resetForTest() {
    _handling = false;
  }

  @override
  void onResponse(
    Response<dynamic> response,
    ResponseInterceptorHandler handler,
  ) {
    // A successful response proves the current token works (e.g. the user
    // has just re-authenticated). Clear the one-shot latch so a FUTURE 401
    // — a fresh expiry — is handled again instead of swallowed. During the
    // post-401 redirect-to-login window no protected request succeeds (the
    // token is dead), so the latch holds across the 401 burst and only
    // reopens once a real success lands.
    _handling = false;
    handler.next(response);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (err.response?.statusCode == 401 && !_handling) {
      _handling = true;
      final callback = AuthInterceptor.globalHandler;
      if (callback != null) {
        try {
          await callback();
        } catch (_) {
          // Defensive: handler MUST NOT crash the interceptor chain.
          // A failure here (e.g. SecureStorage delete throws on a
          // platform that doesn't permit deletion mid-foreground)
          // is logged elsewhere; here we just keep the chain alive
          // so the original DioException still propagates to the
          // bloc that issued the request.
        }
      }
    }
    handler.next(err);
  }
}
