import '../../../core/api/api_client.dart';
import '../models/scenario.dart';

class ScenariosRepository {
  final ApiClient _apiClient;

  ScenariosRepository(this._apiClient);

  Future<List<Scenario>> fetchScenarios() async {
    final response = await _apiClient.get<Map<String, dynamic>>('/scenarios');
    final data = response.data!['data'] as List<dynamic>;
    return data
        .map((e) => Scenario.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
