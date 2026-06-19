import 'package:client/core/api/api_client.dart';
import 'package:client/features/subscription/repositories/user_repository.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class MockApiClient extends Mock implements ApiClient {}

void main() {
  late MockApiClient api;
  late UserRepository repository;

  setUp(() {
    api = MockApiClient();
    repository = UserRepository(api);
  });

  test('deleteAccount issues DELETE /user/me', () async {
    when(() => api.delete<Map<String, dynamic>>('/user/me')).thenAnswer(
      (_) async => Response<Map<String, dynamic>>(
        requestOptions: RequestOptions(path: '/user/me'),
        statusCode: 200,
        data: const {'deleted': true},
      ),
    );

    await repository.deleteAccount();

    verify(() => api.delete<Map<String, dynamic>>('/user/me')).called(1);
  });
}
