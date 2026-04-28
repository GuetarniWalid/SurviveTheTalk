import '../models/call_usage.dart';
import '../models/scenario.dart';

class ScenariosFetchResult {
  final List<Scenario> scenarios;
  final CallUsage usage;

  const ScenariosFetchResult({required this.scenarios, required this.usage});
}
