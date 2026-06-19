import 'package:dio/dio.dart';

import '../auth/token_storage.dart';
import 'api_exception.dart';
import 'auth_interceptor.dart';

class ApiClient {
  static const String baseUrl = 'http://167.235.63.129';

  final Dio _dio;
  final TokenStorage _tokenStorage;

  ApiClient({TokenStorage? tokenStorage, Dio? dio})
    : _tokenStorage = tokenStorage ?? TokenStorage(),
      _dio = dio ?? Dio() {
    _dio.options
      ..baseUrl = baseUrl
      ..connectTimeout = const Duration(seconds: 15)
      ..receiveTimeout = const Duration(seconds: 15)
      ..headers = {'Content-Type': 'application/json'};

    // Story 6.13 AC4 — install the 401 handler FIRST so it observes
    // every error before the request-wrapper's ApiException mapping.
    // Order matters: if the ApiException mapping ran first, the 401
    // would already be wrapped and `err.response?.statusCode` lookup
    // would still work (DioException keeps the response intact) but
    // putting the AuthInterceptor first keeps the auth flow
    // self-contained.
    _dio.interceptors.add(AuthInterceptor());
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final path = options.path;
          if (!path.startsWith('/auth/')) {
            final token = await _tokenStorage.readToken();
            if (token != null) {
              options.headers['Authorization'] = 'Bearer $token';
            }
          }
          handler.next(options);
        },
        onError: (error, handler) {
          handler.next(error.copyWith(error: ApiException.fromDioException(error)));
        },
      ),
    );
  }

  Future<Response<T>> post<T>(String path, {Object? data}) async {
    try {
      return await _dio.post<T>(path, data: data);
    } on DioException catch (e) {
      throw ApiException.fromDioException(e);
    }
  }

  Future<Response<T>> get<T>(String path) async {
    try {
      return await _dio.get<T>(path);
    } on DioException catch (e) {
      throw ApiException.fromDioException(e);
    }
  }

  Future<Response<T>> delete<T>(String path, {Object? data}) async {
    try {
      return await _dio.delete<T>(path, data: data);
    } on DioException catch (e) {
      throw ApiException.fromDioException(e);
    }
  }
}
