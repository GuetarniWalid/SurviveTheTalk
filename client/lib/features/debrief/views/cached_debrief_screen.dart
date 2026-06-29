// Story 9.1 (Task 5, Decision 3 — cache-only) — the report-icon → debrief
// route target. Resolves the most-recent CACHED debrief for a scenario and
// renders the real DebriefScreen, or an empathetic "no saved report" state on a
// cache-miss. There is NO server backfill: a report is viewable from the report
// icon ONLY if it was cached at call-end (CallEndedScreen, Task 4).

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/router.dart';
import '../../../core/api/api_client.dart';
import '../../../core/local_cache/debrief_cache_store.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/widgets/empathetic_error_screen.dart';
import '../../call/repositories/call_repository.dart';
import 'debrief_screen.dart';

/// Cached resolver type — also the test seam shape.
typedef CachedDebriefResolver =
    Future<({int callId, Map<String, dynamic> payload})?> Function();

class CachedDebriefScreen extends StatefulWidget {
  final String scenarioId;

  /// The local store. Null (no DB wired, e.g. some widget tests) resolves to
  /// the cache-miss state — same surface as offline-with-no-saved-report.
  final DebriefCacheStore? cacheStore;

  /// Test seam — overrides the resolver so widget tests skip sqflite entirely.
  @visibleForTesting
  final CachedDebriefResolver? debugResolve;

  const CachedDebriefScreen({
    super.key,
    required this.scenarioId,
    required this.cacheStore,
    this.debugResolve,
  });

  @override
  State<CachedDebriefScreen> createState() => _CachedDebriefScreenState();
}

class _CachedDebriefScreenState extends State<CachedDebriefScreen> {
  late final Future<({int callId, Map<String, dynamic> payload})?> _future;

  @override
  void initState() {
    super.initState();
    _future = _resolve();
  }

  Future<({int callId, Map<String, dynamic> payload})?> _resolve() async {
    final resolver = widget.debugResolve;
    if (resolver != null) return resolver();
    final store = widget.cacheStore;
    if (store == null) return null;
    try {
      return await store.readLatestForScenario(widget.scenarioId);
      // A corrupt cached row degrades to the miss state, never a crash.
      // ignore: avoid_catches_without_on_clauses
    } catch (_) {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<({int callId, Map<String, dynamic> payload})?>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          // The local read is sub-millisecond; a bare background avoids a
          // spinner flash (Gotcha D — no pumpAndSettle-hanging animation).
          return const Scaffold(backgroundColor: AppColors.background);
        }
        final result = snapshot.data;
        if (result != null) {
          // A READY cached payload makes DebriefScreen render immediately and
          // never poll. Story 10.7 (Bug B): a `pending` blob is never cached as
          // final, so this is normally a terminal report; were a pending copy
          // ever cached, the progressive DebriefScreen would RE-FETCH the
          // analysis (it gets the real `callId` + repository here). `callId` is
          // therefore threaded; the repository is constructed inline exactly as
          // the incoming-call route does (router.dart). No new DI thread needed.
          return DebriefScreen(
            payload: result.payload,
            callId: result.callId,
            callRepository: CallRepository(ApiClient()),
            presentPaywallOnLoad: false,
          );
        }
        return const _DebriefMissState();
      },
    );
  }
}

/// Empathetic "no saved report" surface (AC6). Reuses [EmpatheticErrorScreen]
/// exactly as NoNetworkScreen does. The CTA does NOT re-fetch (cache-only — no
/// backfill): it simply goes back. Copy stays within the Handler's-Brief copy
/// lint (Gotcha E — no exclamation/praise/emoji).
class _DebriefMissState extends StatelessWidget {
  const _DebriefMissState();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: EmpatheticErrorScreen(
        // No "no saved report" code in the table — pass any code for the icon
        // glyph and override the copy.
        code: 'UNKNOWN_ERROR',
        titleOverride: 'No saved report yet.',
        bodyOverride:
            'Reports are saved on your device after you finish a call online. '
            'Reconnect and complete this scenario to see its report here.',
        retryLabel: 'Back',
        semanticsLabel: 'Back',
        // Story 9.1 (F8 fix) — back-arrow glyph: this CTA pops back, it does NOT
        // re-fetch (cache-only, no backfill — Decision 3). The default refresh
        // glyph would contradict the "Back" label and the no-backfill intent.
        ctaIcon: Icons.arrow_back,
        onRetry: () =>
            context.canPop() ? context.pop() : context.go(AppRoutes.root),
      ),
    );
  }
}
