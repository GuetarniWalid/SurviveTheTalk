import 'package:dio/dio.dart';

class ApiException implements Exception {
  final String code;
  final String message;

  const ApiException({required this.code, required this.message});

  factory ApiException.fromDioException(DioException e) {
    if (e.type == DioExceptionType.connectionError ||
        e.type == DioExceptionType.connectionTimeout) {
      return const ApiException(
        code: 'NETWORK_ERROR',
        message:
            'No internet connection. Please check your network and try again.',
      );
    }

    final response = e.response;
    if (response != null && response.data is Map<String, dynamic>) {
      final data = response.data as Map<String, dynamic>;
      final error = data['error'];
      if (error is Map<String, dynamic>) {
        return ApiException(
          code: error['code'] as String? ?? 'UNKNOWN_ERROR',
          message:
              error['message'] as String? ??
              'Something went wrong. Please try again.',
        );
      }
    }

    return const ApiException(
      code: 'UNKNOWN_ERROR',
      message: 'Something went wrong. Please try again.',
    );
  }

  @override
  String toString() => 'ApiException($code: $message)';
}
