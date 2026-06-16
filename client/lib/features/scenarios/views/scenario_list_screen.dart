import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/api/api_client.dart';
import '../../../core/api/api_exception.dart';
import '../../../core/onboarding/difficulty_storage.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
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
import 'widgets/difficulty_sheet.dart';
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

  /// Story 6.19 — the GLOBAL difficulty preference store. Production passes the
  /// bootstrap-preloaded instance (threaded via the router) so the hub line and
  /// the outgoing call reflect the persisted choice; tests may omit it (a fresh,
  /// non-preloaded instance defaults to `easy`).
  final DifficultyStorage? difficultyStorage;

  const ScenarioListScreen({
    super.key,
    this.callRepository,
    this.callScreenBuilder,
    this.difficultyStorage,
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
                        difficultyStorage: difficultyStorage,
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
          onPaywallTap: () async {
            if (!context.mounted) return;
            // Story 8.1 (G2) — on a completed purchase, reload the list so the
            // fresh `paid` CallUsage re-flows from `/scenarios` meta and the
            // BOC updates (paid + calls remaining → card hidden, UX-DR5).
            final purchased = await PaywallSheet.show(context);
            if (purchased && context.mounted) {
              context.read<ScenariosBloc>().add(const LoadScenariosEvent());
            }
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
  final DifficultyStorage? difficultyStorage;

  const _List({
    required this.scenarios,
    required this.usage,
    this.callRepository,
    this.callScreenBuilder,
    this.difficultyStorage,
  });

  @override
  State<_List> createState() => _ListState();
}

class _ListState extends State<_List> {
  /// Tap debounce — held for the WHOLE tap flow (briefing await included
  /// since Story 7.4, so a double-tap can't double-push the route), reset
  /// in `finally`. The bloc-level `if (state is ScenariosLoading) return`
  /// guard doesn't help here: the bloc isn't transitioning, only the local
  /// async closure is awaiting. Story 6.1 chose the StatefulWidget path
  /// (vs. ValueNotifier on ScenarioCard) because ScenarioCard has no
  /// per-tap visual feedback requirement in 6.1 — see Dev Notes.
  bool _initiating = false;

  /// Story 7.4 Decision B — ids whose first call was successfully initiated
  /// THIS session. The hub list never refetches after a call, so
  /// `scenario.attempts` goes stale in-session; without this mark the
  /// briefing would re-gate right after the first call (epic AC3
  /// violation). Marked only after a successful `initiateCall` POST (a
  /// failed POST means no call happened — re-showing the briefing is
  /// correct). In-memory only: on app restart the server truth is fresh.
  final Set<String> _initiatedThisSession = <String>{};

  late final CallRepository _callRepository =
      widget.callRepository ?? CallRepository(ApiClient());

  // Story 6.19 — resolved once per State so a sheet selection (set()) and the
  // hub line stay in sync across BlocBuilder rebuilds. Production injects the
  // bootstrap-preloaded store; tests fall back to a fresh (default-easy) one.
  late final DifficultyStorage _difficultyStorage =
      widget.difficultyStorage ?? DifficultyStorage();

  @override
  Widget build(BuildContext context) {
    // Reserve exactly the BOC's rendered height (static content + the
    // device's bottom safe-area inset) so the last ScenarioCard sits flush
    // above the pinned overlay.
    final bottomInset = MediaQuery.viewPaddingOf(context).bottom;
    final reservedForOverlay = BottomOverlayCard.isVisibleFor(widget.usage)
        ? BottomOverlayCard.staticContentHeight + bottomInset
        : 0.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Story 6.19 — discreet GLOBAL difficulty line (set once, applies to
        // every call). Sits above the scrolling list (and so above the pinned
        // BottomOverlayCard); tapping it opens the difficulty bottom sheet.
        _DifficultyHubLine(
          difficulty: _difficultyStorage.getSync(),
          onTap: () => _onDifficultyTap(context),
        ),
        const SizedBox(height: AppSpacing.cardGap),
        Expanded(
          child: ListView.separated(
            padding: EdgeInsets.only(bottom: reservedForOverlay),
            itemCount: widget.scenarios.length,
            separatorBuilder: (_, _) =>
                const SizedBox(height: AppSpacing.cardGap),
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
          ),
        ),
      ],
    );
  }

  // Story 6.19 — open the difficulty bottom sheet, persist the pick, and
  // refresh the hub line. A null result (dismissed) or an unchanged pick is a
  // no-op. `_onCallTap` reads `_difficultyStorage.getSync()` fresh each tap, so
  // the chosen value reaches the next call without any extra plumbing.
  Future<void> _onDifficultyTap(BuildContext context) async {
    final current = _difficultyStorage.getSync();
    final chosen = await showDifficultySheet(context, current: current);
    if (chosen == null || chosen == current) return;
    await _difficultyStorage.set(chosen);
    if (mounted) setState(() {});
  }

  // Story 7.4 first-attempt gate (Decision B) — push the briefing BEFORE
  // any call initiation when this is the scenario's first attempt (server
  // truth at list-load AND not initiated this session) and it has
  // renderable briefing content. Anything but an explicit `true` pop
  // (back arrow, system back) aborts with zero network calls. Returning
  // users (attempts > 0 / session mark / no content) run the chain
  // directly — byte-identical to pre-7.4 behavior.
  Future<void> _onCallTap(BuildContext context, Scenario scenario) async {
    if (_initiating) return;
    setState(() => _initiating = true);
    try {
      final needsBriefing = scenario.attempts == 0 &&
          !_initiatedThisSession.contains(scenario.id) &&
          scenario.hasBriefingContent;
      if (needsBriefing) {
        final ready = await context.push<bool>(
          '${AppRoutes.briefing}/${scenario.id}',
          extra: scenario,
        );
        if (ready != true) return;
        if (!context.mounted) return;
      }
      await _startCall(context, scenario);
    } finally {
      if (mounted) {
        setState(() => _initiating = false);
      }
    }
  }

  // Story 6.1 contract (extracted to `_startCall` in Story 7.4 — chain
  // order untouched; both the call-icon and card-tap entries converge
  // here AFTER their briefing gate resolves):
  //   1. await content-warning sheet (existing behaviour — Decision D:
  //      briefing first, warning after confirm, every time, no merge).
  //   2. await POST /calls/initiate.
  //   3. push CallScreen via the *root* Navigator (ADR 003 §Tier 1 —
  //      detaches the call screen from go_router so PopScope is arbitrated
  //      against the root navigator instead of the GoRouter shell).
  //
  // Failure routing (AC6):
  //   - NETWORK_ERROR        → push NoNetworkScreen (root nav)
  //   - CALL_LIMIT_REACHED   → PaywallSheet.show (modal)
  //   - any other ApiException → stay on scenario list (no inline retry
  //                              banner — see feedback_error_ux.md)
  //
  // No `_initiating` logic here — the flag is always already held by the
  // caller (`_onCallTap` / `_onCardTap`).
  Future<void> _startCall(BuildContext context, Scenario scenario) async {
    if (scenario.contentWarning != null) {
      final proceed = await showContentWarningSheet(context, scenario);
      if (!proceed) return;
      if (!context.mounted) return;
    }

    try {
      final session = await _callRepository.initiateCall(
        scenarioId: scenario.id,
        // Story 6.19 — send the learner's chosen global difficulty for this
        // call (read fresh so a mid-session change on the sheet is honored).
        difficulty: _difficultyStorage.getSync(),
      );
      // Story 7.4 Decision B — the POST succeeded: a call happened, the
      // server-side `attempts` is now stale until the next list load.
      _initiatedThisSession.add(scenario.id);
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
          // Story 8.1 (G2) — reload on a completed purchase so the freed cap
          // re-flows; the user can then re-tap to start the call.
          final purchased = await PaywallSheet.show(context);
          if (purchased && context.mounted) {
            context.read<ScenariosBloc>().add(const LoadScenariosEvent());
          }
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
    }
  }

  void _onReportTap(BuildContext context, Scenario scenario) {
    context.push('${AppRoutes.debrief}/${scenario.id}');
  }

  // Story 7.4 AC-C7 — the whole-card tap opens the same briefing with the
  // same confirm contract: confirming from browse ALSO starts the call
  // (reading the briefing then hunting for the phone icon would be
  // hostile). Replaces the bare `context.push` to the placeholder.
  Future<void> _onCardTap(BuildContext context, Scenario scenario) async {
    if (_initiating) return;
    setState(() => _initiating = true);
    try {
      final ready = await context.push<bool>(
        '${AppRoutes.briefing}/${scenario.id}',
        extra: scenario,
      );
      if (ready != true) return;
      if (!context.mounted) return;
      await _startCall(context, scenario);
    } finally {
      if (mounted) {
        setState(() => _initiating = false);
      }
    }
  }
}

/// Story 6.19 — the discreet, tappable `Difficulty: <Level>` line on the hub.
/// Low-key (textSecondary grey, no new colors) so it reads as a quiet setting,
/// not a prominent control. Tapping opens the difficulty bottom sheet.
class _DifficultyHubLine extends StatelessWidget {
  final String difficulty;
  final VoidCallback onTap;

  const _DifficultyHubLine({required this.difficulty, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final label =
        '${difficulty[0].toUpperCase()}${difficulty.substring(1)}';
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            const Icon(
              Icons.tune,
              size: 15,
              color: AppColors.textSecondary,
            ),
            const SizedBox(width: 6),
            Text(
              'Difficulty: $label',
              style: const TextStyle(
                fontFamily: AppTypography.fontFamily,
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
