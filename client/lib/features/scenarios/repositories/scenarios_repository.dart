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
    // Story 9.1 — retain the RAW maps (server order preserved) so the offline
    // cache can persist them losslessly; the parsed models have no
    // `toJson`/`toMeta`. A non-Map element throws TypeError here (same blast
    // radius as before — the bloc's catch maps it to MALFORMED_RESPONSE).
    final rawScenarios = data.cast<Map<String, dynamic>>().toList();
    return ScenariosFetchResult(
      scenarios: rawScenarios.map(Scenario.fromJson).toList(),
      usage: CallUsage.fromMeta(meta),
      rawScenarios: rawScenarios,
      rawMeta: meta,
    );
  }
}
