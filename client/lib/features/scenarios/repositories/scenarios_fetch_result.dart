import '../models/call_usage.dart';
import '../models/scenario.dart';

class ScenariosFetchResult {
  final List<Scenario> scenarios;
  final CallUsage usage;

  /// Story 9.1 — the RAW server maps retained alongside the parsed models so
  /// the offline cache can persist them losslessly. The parsed [Scenario] /
  /// [CallUsage] models have no `toJson`/`toMeta` and `tagline` is derived
  /// client-side, so re-serializing them would be lossy — the cache writes
  /// these raw maps instead. `rawScenarios` is the `/scenarios` `data` list in
  /// server order; `rawMeta` is the `meta` block.
  final List<Map<String, dynamic>> rawScenarios;
  final Map<String, dynamic> rawMeta;

  const ScenariosFetchResult({
    required this.scenarios,
    required this.usage,
    required this.rawScenarios,
    required this.rawMeta,
  });
}
