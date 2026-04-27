import '../models/scenario.dart';

sealed class ScenariosState {
  const ScenariosState();
}

final class ScenariosInitial extends ScenariosState {
  const ScenariosInitial();
}

// Deliberately non-const so successive loading emissions are distinct
// instances; BlocListener/BlocBuilder dedupe equal const instances and would
// silently skip a retry that re-enters Loading. Mirrors `auth_state.dart`.
final class ScenariosLoading extends ScenariosState {}

final class ScenariosLoaded extends ScenariosState {
  final List<Scenario> scenarios;
  const ScenariosLoaded(this.scenarios);
}

final class ScenariosError extends ScenariosState {
  final String message;
  const ScenariosError(this.message);
}
