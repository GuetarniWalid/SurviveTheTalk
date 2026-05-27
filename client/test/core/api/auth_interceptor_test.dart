import 'package:client/core/api/auth_interceptor.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

DioException _dio401() => DioException(
  type: DioExceptionType.badResponse,
  requestOptions: RequestOptions(path: '/scenarios'),
  response: Response(
    requestOptions: RequestOptions(path: '/scenarios'),
    statusCode: 401,
    data: {
      'error': {
        'code': 'AUTH_UNAUTHORIZED',
        'message': 'token expired',
      },
    },
  ),
);

DioException _dio500() => DioException(
  type: DioExceptionType.badResponse,
  requestOptions: RequestOptions(path: '/scenarios'),
  response: Response(
    requestOptions: RequestOptions(path: '/scenarios'),
    statusCode: 500,
    data: {'error': {'code': 'INTERNAL', 'message': 'oops'}},
  ),
);

Response<dynamic> _response200() => Response<dynamic>(
  requestOptions: RequestOptions(path: '/scenarios'),
  statusCode: 200,
  data: {'ok': true},
);

class _CapturingErrorHandler extends ErrorInterceptorHandler {
  bool nextCalled = false;
  DioException? lastError;

  @override
  void next(DioException err) {
    nextCalled = true;
    lastError = err;
  }
}

class _CapturingResponseHandler extends ResponseInterceptorHandler {
  bool nextCalled = false;

  @override
  void next(Response<dynamic> response) {
    nextCalled = true;
  }
}

void main() {
  setUp(() {
    // Reset the global handler between tests so prior tests' stubs
    // don't bleed in. Production wiring lives in App.initState (set
    // once per app lifetime).
    AuthInterceptor.globalHandler = null;
    // The re-entry latch is STATIC (shared across instances) — reset it
    // so a prior test's 401 doesn't leak its `_handling=true` into the
    // next test.
    AuthInterceptor.reset();
  });

  tearDown(() {
    AuthInterceptor.globalHandler = null;
    AuthInterceptor.reset();
  });

  group('AuthInterceptor — Story 6.13 AC4 — Story 5.5 MUST-FIX gap', () {
    test('fires the global handler on 401', () async {
      var fired = 0;
      AuthInterceptor.globalHandler = () async {
        fired += 1;
      };
      final interceptor = AuthInterceptor();
      final handler = _CapturingErrorHandler();

      await interceptor.onError(_dio401(), handler);

      expect(fired, 1, reason: '401 must trigger the global handler');
      expect(
        handler.nextCalled,
        true,
        reason: 'interceptor must still let the error propagate',
      );
    });

    test('does NOT fire the handler on non-401 responses', () async {
      var fired = 0;
      AuthInterceptor.globalHandler = () async {
        fired += 1;
      };
      final interceptor = AuthInterceptor();
      final handler = _CapturingErrorHandler();

      await interceptor.onError(_dio500(), handler);

      expect(fired, 0, reason: '5xx must NOT trigger the auth handler');
      expect(handler.nextCalled, true);
    });

    test('re-entry guard: second 401 on same instance does not re-fire',
        () async {
      var fired = 0;
      AuthInterceptor.globalHandler = () async {
        fired += 1;
      };
      final interceptor = AuthInterceptor();

      await interceptor.onError(_dio401(), _CapturingErrorHandler());
      await interceptor.onError(_dio401(), _CapturingErrorHandler());

      expect(
        fired,
        1,
        reason:
            'duplicate 401s during the navigation window must not re-fire the '
            'handler (avoids double toast + double bloc dispatch)',
      );
    });

    test('null globalHandler does not crash on 401', () async {
      AuthInterceptor.globalHandler = null;
      final interceptor = AuthInterceptor();
      final handler = _CapturingErrorHandler();

      await interceptor.onError(_dio401(), handler);

      expect(
        handler.nextCalled,
        true,
        reason: 'absent handler must still let the error propagate '
            '(graceful degradation pre-bootstrap)',
      );
    });

    test('handler exception does not stop propagation', () async {
      AuthInterceptor.globalHandler = () async {
        throw StateError('keystore locked');
      };
      final interceptor = AuthInterceptor();
      final handler = _CapturingErrorHandler();

      await interceptor.onError(_dio401(), handler);

      expect(
        handler.nextCalled,
        true,
        reason: 'a crashing handler must NOT block the original 401 from '
            'reaching the original caller (defensive shutdown ergonomics)',
      );
    });

    test('resetForTest unlocks re-entry guard between tests', () async {
      var fired = 0;
      AuthInterceptor.globalHandler = () async {
        fired += 1;
      };
      final interceptor = AuthInterceptor();

      await interceptor.onError(_dio401(), _CapturingErrorHandler());
      interceptor.resetForTest();
      await interceptor.onError(_dio401(), _CapturingErrorHandler());

      expect(fired, 2, reason: 'resetForTest must clear the re-entry latch');
    });

    test('static guard dedups 401s across DIFFERENT interceptor instances',
        () async {
      var fired = 0;
      AuthInterceptor.globalHandler = () async {
        fired += 1;
      };
      // Mirrors prod: each ApiClient builds its own AuthInterceptor.
      final a = AuthInterceptor();
      final b = AuthInterceptor();

      await a.onError(_dio401(), _CapturingErrorHandler());
      await b.onError(_dio401(), _CapturingErrorHandler());

      expect(
        fired,
        1,
        reason:
            'concurrent 401s on different clients must fire the handler once '
            '(static latch) — no stacked toasts / double bloc reset',
      );
    });

    test('a successful response reopens the guard for a future expiry',
        () async {
      var fired = 0;
      AuthInterceptor.globalHandler = () async {
        fired += 1;
      };
      final interceptor = AuthInterceptor();

      await interceptor.onError(_dio401(), _CapturingErrorHandler());
      // User re-authenticates; a later protected request succeeds.
      interceptor.onResponse(_response200(), _CapturingResponseHandler());
      // A subsequent expiry MUST be handled again, not silently swallowed.
      await interceptor.onError(_dio401(), _CapturingErrorHandler());

      expect(
        fired,
        2,
        reason:
            'onResponse must clear the latch so a post-re-login 401 is handled '
            '(closes the Story 5.5 silent loop for repeat expiries)',
      );
    });
  });
}
