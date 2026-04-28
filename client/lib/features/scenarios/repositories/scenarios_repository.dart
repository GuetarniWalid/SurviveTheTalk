import '../../../core/api/api_client.dart';
import '../models/call_usage.dart';
import '../models/scenario.dart';
import 'scenarios_fetch_result.dart';

class ScenariosRepository {
  final ApiClient _apiClient;

  ScenariosRepository(this._apiClient);

  Future<ScenariosFetchResult> fetchScenarios() async {
    final response = await _apiClient.get<Map<String, dynamic>>('/scenarios');
    final body = response.data!;
    final data = body['data'] as List<dynamic>;
    final meta = body['meta'] as Map<String, dynamic>;
    return ScenariosFetchResult(
      scenarios: data
          .map((e) => Scenario.fromJson(e as Map<String, dynamic>))
          .toList(),
      usage: CallUsage.fromMeta(meta),
    );
  }
}
