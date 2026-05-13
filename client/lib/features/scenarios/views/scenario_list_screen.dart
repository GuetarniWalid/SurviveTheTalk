import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/api/api_client.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_toast.dart';
import '../../../core/widgets/empathetic_error_screen.dart';
import '../../call/models/call_session.dart';
import '../../call/repositories/call_repository.dart';
import '../../call/views/call_screen.dart';
import '../../call/views/no_network_screen.dart';
import '../../paywall/views/paywall_sheet.dart';
import '../bloc/scenarios_bloc.dart';
import '../bloc/scenarios_event.dart';
import '../bloc/scenarios_state.dart';
import '../models/call_usage.dart';
import '../models/scenario.dart';
import 'widgets/bottom_overlay_card.dart';
import 'widgets/content_warning_sheet.dart';
import 'widgets/scenario_card.dart';

/// Builds the in-call surface to push from `_onCallTap`. Defaults to
/// `CallScreen.new`. Tests pass a lightweight stub to avoid constructing a
/// real LiveKit `Room` (which spawns background timers that leak across
/// test boundaries).
typedef CallScreenBuilder =
    Widget Function(Scenario scenario, CallSession session);

Widget _defaultCallScreenBuilder(Scenario scenario, CallSession session) {
  return CallScreen(scenario: scenario, callSession: session);
}

class ScenarioListScreen extends StatelessWidget {
  /// Optional injection seam for tests. Production uses
  /// `CallRepository(ApiClient())` — passing nothing keeps the existing
  /// router wiring unchanged.
  final CallRepository? callRepository;

  /// Optional injection seam for tests. Production uses `CallScreen.new`.
  final CallScreenBuilder? callScreenBuilder;

  const ScenarioListScreen({
    super.key,
    this.callRepository,
    this.callScreenBuilder,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      // Each state owns its own SafeArea + Padding envelope: the loaded
      // list uses iPhone 16 - 5 metrics (top: true, bottom: false, h-pad
      // 18) so the pinned BOC can bleed into the bottom safe-area, while
      // the error view (Story 5.5 Figma iphone-16-8) wants top + bottom
      // SafeArea + h-pad 36 because the "Try again" button sits at the
      // bottom and must respect the home-indicator inset.
      body: Stack(
        children: [
          BlocBuilder<ScenariosBloc, ScenariosState>(
            builder: (context, state) {
              switch (state) {
                case ScenariosInitial():
                case ScenariosLoading():
                  return const SizedBox.shrink();
                case ScenariosLoaded(:final scenarios, :final usage):
                  return SafeArea(
                    top: true,
                    bottom: false,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(
                        AppSpacing.screenHorizontalScenarioList,
                        AppSpacing.screenVerticalList,
                        AppSpacing.screenHorizontalScenarioList,
                        0,
                      ),
                      child: _List(
                        scenarios: scenarios,
                        usage: usage,
                        callRepository: callRepository,
                        callScreenBuilder: callScreenBuilder,
                      ),
                    ),
                  );
                case ScenariosError(:final code, :final retryCount):
                  return EmpatheticErrorScreen(
                    code: code,
                    retryCount: retryCount,
                    onRetry: () => context
                        .read<ScenariosBloc>()
                        .add(const LoadScenariosEvent()),
                  );
              }
            },
          ),
          const Positioned(left: 0, right: 0, bottom: 0, child: _OverlayHost()),
        ],
      ),
    );
  }
}

/// Pinned bottom overlay that surfaces the user's remaining call budget /
/// paywall CTA when the scenarios list is loaded.
///
/// During Loading/Error/Initial we have no CallUsage to render — emitting
/// a half-state would mislead the user about their remaining calls. The
/// error view (full-area) is the entire screen.
class _OverlayHost extends StatelessWidget {
  const _OverlayHost();

  @override
  Widget build(BuildContext context) {
    // No `buildWhen` — `ScenariosLoaded` has no value-equality (spec: NO
    // Equatable) so any custom predicate based on identity would still
    // rebuild on every emit. Letting BlocBuilder rebuild unconditionally
    // is honest about the cost and avoids a misleading no-op predicate.
    return BlocBuilder<ScenariosBloc, ScenariosState>(
      builder: (context, state) {
        if (state is! ScenariosLoaded) return const SizedBox.shrink();
        return BottomOverlayCard(
          usage: state.usage,
          // `context.mounted` guards against the rare race where the
          // BlocBuilder rebuilds (unmounting this BOC) between gesture
          // recognition and the tap firing. Without the guard, the closure
          // would call `showModalBottomSheet` with a deactivated context.
          onPaywallTap: () {
            if (!context.mounted) return;
            PaywallSheet.show(context);
          },
        );
      },
    );
  }
}

class _List extends StatefulWidget {
  final List<Scenario> scenarios;
  final CallUsage usage;
  final CallRepository? callRepository;
  final CallScreenBuilder? callScreenBuilder;

  const _List({
    required this.scenarios,
    required this.usage,
    this.callRepository,
    this.callScreenBuilder,
  });

  @override
  State<_List> createState() => _ListState();
}

class _ListState extends State<_List> {
  /// Tap debounce — set to true while a `/calls/initiate` POST is in
  /// flight, gates `_onCallTap` at the top so a second tap can't fire a
  /// second POST. The bloc-level `if (state is ScenariosLoading) return`
  /// guard doesn't help here: the bloc isn't transitioning, only the local
  /// async closure is awaiting. Story 6.1 chose the StatefulWidget path
  /// (vs. ValueNotifier on ScenarioCard) because ScenarioCard has no
  /// per-tap visual feedback requirement in 6.1 — see Dev Notes.
  bool _initiating = false;

  late final CallRepository _callRepository =
      widget.callRepository ?? CallRepository(ApiClient());

  @override
  Widget build(BuildContext context) {
    // Reserve exactly the BOC's rendered height (static content + the
    // device's bottom safe-area inset) so the last ScenarioCard sits flush
    // above the pinned overlay.
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    final reservedForOverlay = BottomOverlayCard.isVisibleFor(widget.usage)
        ? BottomOverlayCard.staticContentHeight + bottomInset
        : 0.0;
    return ListView.separated(
      padding: EdgeInsets.only(bottom: reservedForOverlay),
      itemCount: widget.scenarios.length,
      separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.cardGap),
      itemBuilder: (context, i) {
        final scenario = widget.scenarios[i];
        return ScenarioCard(
          scenario: scenario,
          onCallTap: () => _onCallTap(context, scenario),
          onCardTap: () => _onCardTap(context, scenario),
          onReportTap: scenario.isNotAttempted
              ? null
              : () => _onReportTap(context, scenario),
        );
      },
    );
  }

  // Story 6.1 contract:
  //   1. await content-warning sheet (existing behaviour).
  //   2. await POST /calls/initiate (was: navigate to /call placeholder).
  //   3. push CallScreen via the *root* Navigator (ADR 003 §Tier 1 —
  //      detaches the call screen from go_router so PopScope is arbitrated
  //      against the root navigator instead of the GoRouter shell).
  //
  // Failure routing (AC6):
  //   - NETWORK_ERROR        → push NoNetworkScreen (root nav)
  //   - CALL_LIMIT_REACHED   → PaywallSheet.show (modal)
  //   - any other ApiException → stay on scenario list (no inline retry
  //                              banner — see feedback_error_ux.md)
  Future<void> _onCallTap(BuildContext context, Scenario scenario) async {
    if (_initiating) return;
    if (scenario.contentWarning != null) {
      final proceed = await showContentWarningSheet(context, scenario);
      if (!proceed) return;
      if (!context.mounted) return;
    }

    setState(() => _initiating = true);
    try {
      final session = await _callRepository.initiateCall(
        scenarioId: scenario.id,
      );
      if (!context.mounted) return;
      final builder =
          widget.callScreenBuilder ?? _defaultCallScreenBuilder;
      await Navigator.of(context, rootNavigator: true).push<void>(
        MaterialPageRoute<void>(
          builder: (_) => builder(scenario, session),
          fullscreenDialog: true,
        ),
      );
    } on ApiException catch (e) {
      if (!context.mounted) return;
      switch (e.code) {
        case 'NETWORK_ERROR':
          await Navigator.of(context, rootNavigator: true).push<void>(
            MaterialPageRoute<void>(
              builder: (_) => const NoNetworkScreen(),
              fullscreenDialog: true,
            ),
          );
        case 'CALL_LIMIT_REACHED':
          await PaywallSheet.show(context);
        default:
          // Generic 5xx (LIVEKIT_TOKEN_FAILED, BOT_SPAWN_FAILED,
          // SCENARIO_LOAD_FAILED, UNKNOWN_ERROR, etc.). Stay on the list
          // (the safe fallback already exists right here) but surface a
          // red toast so the user knows their tap registered and the
          // failure is scenario-specific + temporary. AppToast (Story
          // 4.3) is the same primitive used for the spam-folder hint —
          // reused with `error` type so the colour is destructive red.
          AppToast.show(
            context,
            message:
                "This scenario hit a snag. Try a different one — we're on it.",
            type: AppToastType.error,
          );
      }
    } finally {
      if (mounted) {
        setState(() => _initiating = false);
      }
    }
  }

  void _onReportTap(BuildContext context, Scenario scenario) {
    context.push('${AppRoutes.debrief}/${scenario.id}');
  }

  void _onCardTap(BuildContext context, Scenario scenario) {
    context.push('${AppRoutes.briefing}/${scenario.id}');
  }
}
