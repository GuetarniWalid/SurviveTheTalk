# Story 5.3: Build BottomOverlayCard and Daily Call Limit Enforcement

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to see my subscription status and remaining calls at the bottom of the scenario list,
So that I understand what content is available to me and when I need to subscribe.

## Acceptance Criteria (BDD)

**AC1 — Server: `GET /scenarios` envelope `meta` carries the caller's call usage:**
Given an authenticated user requests `GET /scenarios`
When the route handler builds the success envelope
Then `meta` includes the canonical usage block alongside the existing `count` + `timestamp`:
  - `tier`: `"free"` or `"paid"` (read from `users.tier`)
  - `calls_remaining`: int ≥ 0 (server-computed — see Dev Notes → Usage policy)
  - `calls_per_period`: int (currently a constant `3` for both tiers — kept as a server-owned literal so a future tier rebalance is one-line)
  - `period`: `"lifetime"` for free users (FR21: "no daily recharge"), `"day"` for paid users
And the existing `data` array shape (`ScenarioListItem` × N) and `meta.count` / `meta.timestamp` are unchanged — Story 5.2's parser must keep working
And the call usage is computed inside the same DB connection that read the scenarios (no second connection — Architecture Boundary 4 keeps connection lifecycle inside one route handler).

**AC2 — Server: `/calls/initiate` enforces the cap before persisting:**
Given a user with no remaining calls (free with 3 lifetime call_sessions OR paid with 3 call_sessions started today UTC)
When the user calls `POST /calls/initiate`
Then the server responds `403` with the canonical error envelope `{"error": {"code": "CALL_LIMIT_REACHED", "message": "..."}}`
And NO `call_sessions` row is inserted (the check runs BEFORE the DB INSERT, BEFORE LiveKit token generation, BEFORE the bot subprocess spawn)
And the existing happy path remains untouched: a user under their cap still gets the `{data: {call_id, room_name, token, livekit_url}, meta: {timestamp}}` envelope in `200`
And the message is short, user-facing, and does NOT leak the cap value or the period (clients render the BOC for that — server message stays generic).

**AC3 — Server: usage policy correctness across tier/period boundaries:**
Given the canonical policy (free = 3 lifetime, paid = 3/day, day = UTC calendar day)
When `compute_call_usage(db, user_id, tier, now_utc)` runs:
  - **free with 0 sessions** → `calls_remaining = 3`
  - **free with 1 session** → `calls_remaining = 2`
  - **free with 3 sessions (any age)** → `calls_remaining = 0`
  - **free with >3 sessions** → `calls_remaining = 0` (clamped to 0, never negative)
  - **paid with 0 sessions today** → `calls_remaining = 3`
  - **paid with 3 sessions today + N sessions yesterday** → `calls_remaining = 0` (yesterday doesn't count)
  - **paid with 0 sessions today + 5 sessions yesterday** → `calls_remaining = 3` (clean slate at UTC midnight)
And `period` reflects the policy literal: `"lifetime"` for free, `"day"` for paid
And `calls_per_period` is the literal `3` regardless of tier (kept as a server-owned constant so a future rebalance ships as one-line PR + a regression test update).

**AC4 — Client: `CallUsage` model parses the meta block:**
Given the repository receives the `{data, meta}` envelope from `GET /scenarios`
When `ScenariosRepository.fetchScenarios()` returns
Then it now returns `ScenariosFetchResult(scenarios: List<Scenario>, usage: CallUsage)` instead of just `List<Scenario>`
And `CallUsage.fromMeta(Map<String, dynamic> meta)` maps the canonical keys → Dart camelCase:
  - `tier: String` (literal `'free'` or `'paid'`)
  - `callsRemaining: int`
  - `callsPerPeriod: int`
  - `period: String` (literal `'lifetime'` or `'day'`)
And missing/malformed meta keys throw `TypeError` (caller treats it as `ApiException`-equivalent — same blast radius as a malformed scenarios list)
And `CallUsage` exposes a sealed-ish boolean accessor surface for the BOC widget:
  - `bool get isFree => tier == 'free'`
  - `bool get hasCallsRemaining => callsRemaining > 0`
  - `bool get isLifetimePeriod => period == 'lifetime'`
And the model is immutable (`final` fields, `const` ctor, NO `copyWith`/`Equatable` — same pattern as `Scenario`).

**AC5 — Client: `ScenariosBloc` carries `CallUsage` through `ScenariosLoaded`:**
Given the bloc state machine from Story 5.2
When `LoadScenariosEvent` succeeds
Then `ScenariosLoaded(List<Scenario> scenarios, CallUsage usage)` carries BOTH payloads (Story 5.2's signature is widened — Story 5.2 dev was warned this would happen via "If Story 5.3 needs the same data on the same route…")
And the bloc + repository tests from Story 5.2 are updated to assert the new field is present (no orphan tests asserting on the old single-arg ctor)
And error/loading states are unchanged
And the `ScenariosLoading()` non-const guard from Story 5.2 stays in place — same `BlocListener` dedupe rationale (`auth_state.dart` precedent).

**AC6 — Client: `BottomOverlayCard` widget renders all four UX-DR5 states:**
Given UX-DR5 (`ux-design-specification.md` lines 670-709, 994-1018) defines the four states + layout
When the widget receives a `CallUsage usage` and a `VoidCallback? onTap`
Then it renders per the state matrix:

| State key | `usage.tier` | `usage.callsRemaining` | Title | Subtitle | Visible? | Tappable? |
|---|---|---|---|---|---|---|
| `freeWithCalls` | `free` | `> 0` | `"Unlock all scenarios"` | `"If you can survive us, real humans don't stand a chance"` | ✅ | ✅ → paywall |
| `freeExhausted` | `free` | `0` | `"Subscribe to keep calling"` | `"If you can survive us, real humans don't stand a chance"` | ✅ | ✅ → paywall |
| `paidWithCalls` | `paid` | `> 0` | — | — | ❌ (return `SizedBox.shrink()`) | n/a |
| `paidExhausted` | `paid` | `0` | `"No more calls today"` | `"Come back tomorrow"` | ✅ | ❌ (informational — `onTap` ignored when null is passed) |

And the widget anatomy follows UX-DR5 verbatim:
  - `Container(width: double.infinity, color: AppColors.textPrimary, padding: EdgeInsets.fromLTRB(20, 20, 20, MediaQuery.viewPaddingOf(context).bottom + 20))` — extends INTO the bottom safe area (UX spec line 681)
  - `Row(children: [_diamondIcon, SizedBox(width: AppSpacing.overlayIconTextGap), Expanded(child: _textColumn)])`
  - `_diamondIcon`: `Icon(Icons.diamond_outlined, color: AppColors.accent, size: AppSpacing.iconSmall)` (24px, mint accent — the only non-monochrome element on the list per UX §770-790 + UX line 690 "blue/diamond")
  - `_textColumn`: `Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: AppTypography.cardTitle.copyWith(fontSize: 14, color: AppColors.background)), SizedBox(height: AppSpacing.overlayLineGap), Text(subtitle, style: AppTypography.cardStats.copyWith(fontSize: 11, color: const Color(0xFF4C4C4C) /* see Tech Debt note in Dev Notes — token added if reused */))])`

And the widget pulls every colour, spacing, and typography token from `AppColors` / `AppSpacing` / `AppTypography` — `theme_tokens_test.dart` MUST stay green
And the widget is a pure `StatelessWidget` — no own state, no own animations.

**AC7 — Client: `ScenarioListScreen` integrates the overlay below the list:**
Given Story 5.2 lands `ScenarioListScreen` with `SafeArea(top: true, bottom: false)` + `ListView.separated`
When this story modifies the screen
Then the screen body becomes `Stack`-based:
  - The `ListView.separated` keeps a bottom padding equal to the BOC's measured height (or a generous static estimate — see Dev Notes → Bottom inset) so the last `ScenarioCard` is never hidden behind the overlay
  - The BOC is `Positioned(left: 0, right: 0, bottom: 0)` so it pins to the screen edge regardless of list scroll
  - The BOC reads `state.usage` from `BlocBuilder<ScenariosBloc, ScenariosState>` — only renders when state is `ScenariosLoaded` (during `Loading` / `Error` / `Initial`, the BOC is absent)
And in the `paidWithCalls` state, the BOC is `SizedBox.shrink()` (zero-height) — the list's bottom padding still applies but the visual row is hidden
And tapping the BOC (when actionable) dispatches `context.go(AppRoutes.paywall)` — the new placeholder route added by Task 7.

**AC8 — Client: paywall placeholder route exists:**
Given Story 8.2 will build the real `PaywallScreen`, but BOC tap needs a destination today
When this story lands
Then `lib/app/router.dart` has `static const String paywall = '/paywall';` in `AppRoutes` and a matching `GoRoute(path: AppRoutes.paywall, pageBuilder: …)` rendering a `PaywallPlaceholderScreen` widget
And the placeholder shows `"Paywall — coming in Story 8.2"` centered in `AppTypography.body.copyWith(color: AppColors.textPrimary)`, on `AppColors.background`, with a `IconButton(icon: Icons.arrow_back, color: AppColors.textPrimary, onPressed: () => context.go(AppRoutes.root))` so the user can return — same shape as `DebriefPlaceholderScreen` from Story 5.2.

**AC9 — Client: accessibility (UX-DR12 + UX line 1018):**
Given screen readers are enabled (VoiceOver / TalkBack)
When the BOC is rendered
Then a single `Semantics` wrapper announces the composed label:
  - `freeWithCalls`: `"Unlock all scenarios. If you can survive us, real humans don't stand a chance. Tap to view subscription options."`
  - `freeExhausted`: `"Subscribe to keep calling. If you can survive us, real humans don't stand a chance. Tap to view subscription options."`
  - `paidExhausted`: `"No more calls today. Come back tomorrow."` (no tap-affordance suffix — informational state, semantics `button: false`)
  - `paidWithCalls`: BOC absent — no semantic node
And the `Semantics` wrapper sets `button: true` for the actionable states and `button: false` for the informational state
And the touch target spans the entire visible card (full width, full height) — wrapping the whole row in an `InkWell` (or `GestureDetector` if no ripple wanted on a `#F0F0F0` surface — see Dev Notes → Tap target rendering) with `behavior: HitTestBehavior.opaque`.

**AC10 — Pre-commit validation gates:**
Given pre-commit requirements from CLAUDE.md + client/CLAUDE.md
When the story is complete
Then `cd server && python -m ruff check . && python -m ruff format --check . && pytest` all pass — including the new server-side usage tests AND the existing `test_migrations.py` snapshot replay (no schema change shipped, so the snapshot stays valid)
And `cd client && flutter analyze` prints "No issues found!" — every info-level lint fixed
And `cd client && flutter test` prints "All tests passed!" — ~10+ new Dart tests plus all Story 5.2 tests still green (since 5.2's `ScenariosLoaded(List<Scenario>)` ctor changes shape, every 5.2 test that constructs a `ScenariosLoaded` directly is updated)
And `test/core/theme/theme_tokens_test.dart` stays green (one new hex literal — `#4C4C4C` — is justified per Dev Notes → Tech debt; if it ends up reused elsewhere we promote to `AppColors.overlaySubtitle` instead).

## Tasks / Subtasks

- [ ] Task 1: Server — add `count_user_call_sessions_*` queries to `db/queries.py` (AC: 1, 2, 3)
  - [ ] 1.1 Append two functions at the bottom of `server/db/queries.py`:
    ```python
    async def count_user_call_sessions_total(
        db: aiosqlite.Connection, user_id: int
    ) -> int:
        """Lifetime call_sessions count for a user (used by free-tier policy)."""
        async with db.execute(
            "SELECT COUNT(*) FROM call_sessions WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0


    async def count_user_call_sessions_since(
        db: aiosqlite.Connection, user_id: int, since_iso: str
    ) -> int:
        """call_sessions count for a user since `since_iso` (used by paid-tier policy).

        `started_at` is stored as ISO 8601 UTC (per Architecture line 550), so a
        lexicographic `>=` comparison against a same-format `since_iso` is
        equivalent to a temporal comparison. Cheaper than parsing per-row.
        """
        async with db.execute(
            "SELECT COUNT(*) FROM call_sessions WHERE user_id = ? AND started_at >= ?",
            (user_id, since_iso),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0
    ```
  - [ ] 1.2 DO NOT add tier branching in `queries.py` — pure SQL only (Architecture Boundary 4). Tier policy lives one layer up in the new `usage.py` module (Task 2).
  - [ ] 1.3 Reuse the `idx_call_sessions_user_id` index (already in 002_calls.sql + carried by 005's rebuild) — both queries hit it. No new index needed; production has fewer than ~500 rows for MVP.

- [ ] Task 2: Server — add `api/usage.py` (policy layer) (AC: 1, 3)
  - [ ] 2.1 Create `server/api/usage.py`:
    ```python
    """Call-usage policy: tier → cap → period → calls_remaining.

    Centralises the FR21 rule (free = 3 lifetime, paid = 3/day) so both
    `/scenarios` (display state) and `/calls/initiate` (enforcement) share
    one source of truth. A future rebalance lands here and propagates to
    both endpoints + the client BOC for free.
    """
    from __future__ import annotations

    from datetime import UTC, datetime

    import aiosqlite

    from db.queries import (
        count_user_call_sessions_since,
        count_user_call_sessions_total,
    )

    CALLS_PER_PERIOD: int = 3  # FR21 — same literal for both tiers today.


    def _utc_day_start_iso(now: datetime) -> str:
        """Return the ISO 8601 UTC start-of-day for `now` (microseconds stripped)."""
        start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat(timespec="seconds").replace("+00:00", "Z")


    async def compute_call_usage(
        db: aiosqlite.Connection,
        user_id: int,
        tier: str,
        *,
        now: datetime | None = None,
    ) -> dict:
        """Return the canonical `{tier, calls_remaining, calls_per_period, period}` dict.

        `now` is injectable for tests; defaults to `datetime.now(UTC)`.
        """
        if now is None:
            now = datetime.now(UTC)

        if tier == "free":
            used = await count_user_call_sessions_total(db, user_id)
            period = "lifetime"
        elif tier == "paid":
            used = await count_user_call_sessions_since(
                db, user_id, _utc_day_start_iso(now)
            )
            period = "day"
        else:
            # Defensive: the CHECK constraint on users.tier limits values to
            # {'free','paid'} (migration 003), so this branch is unreachable
            # under normal operation. Raising preserves the invariant loud
            # rather than degrading silently.
            raise ValueError(f"Unsupported tier: {tier!r}")

        remaining = max(0, CALLS_PER_PERIOD - used)
        return {
            "tier": tier,
            "calls_remaining": remaining,
            "calls_per_period": CALLS_PER_PERIOD,
            "period": period,
        }
    ```
  - [ ] 2.2 DO NOT inline the tier branching at call sites. Both `routes_scenarios.py` and `routes_calls.py` MUST go through `compute_call_usage()`.
  - [ ] 2.3 Keep `CALLS_PER_PERIOD = 3` as a module-level constant (NOT a `Settings` env var). Future Story 8.x tier rebalance is a code edit, not a config-only deploy — keeps the migration story honest.
  - [ ] 2.4 The `now` injectable kwarg is the ONLY way to get deterministic UTC-day boundary tests without freezing system time. Use it in tests; production passes `None`.

- [ ] Task 3: Server — extend `routes_scenarios.list_scenarios` to fold `usage` into `meta` (AC: 1)
  - [ ] 3.1 In `server/api/routes_scenarios.py`, after the existing `rows = await get_all_scenarios_with_progress(db, user_id)` line, fetch the user record (or just the tier) and compute usage in the SAME `async with get_connection() as db:` block:
    ```python
    async with get_connection() as db:
        rows = await get_all_scenarios_with_progress(db, user_id)
        user = await get_user_by_id(db, user_id)  # already imported via queries
        if user is None:
            # Cannot happen for a JWT-authenticated request (middleware would
            # have 401'd already), but guard anyway — silent NoneType.access
            # would be much worse than a clean 401.
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "AUTH_UNAUTHORIZED",
                    "message": "Missing or invalid token.",
                },
            )
        usage = await compute_call_usage(db, user_id, user["tier"])
    ```
  - [ ] 3.2 At the return site, replace `return ok_list(items)` with `return ok_list(items, extra_meta=usage)`. Requires `ok_list` signature widening (Task 4).
  - [ ] 3.3 Add the import at the top: `from api.usage import compute_call_usage` and `from db.queries import get_all_scenarios_with_progress, get_scenario_by_id_with_progress, get_user_by_id`.
  - [ ] 3.4 DO NOT touch `get_scenario(scenario_id)` — single-scenario detail does NOT carry usage. The list endpoint is the one bound to the BOC's render lifecycle.

- [ ] Task 4: Server — widen `ok_list` to accept `extra_meta` (AC: 1)
  - [ ] 4.1 In `server/api/responses.py`, change `ok_list(items: list)` → `ok_list(items: list, *, extra_meta: dict | None = None)`. Body: delegate to `ok(payload, extra_meta={"count": len(payload), **(extra_meta or {})})`.
  - [ ] 4.2 Backwards-compat: existing `ok_list(items)` callers (just `routes_scenarios.list_scenarios` today, but keep the contract clean) keep working with no edit. The pre-commit `pytest` proves it.
  - [ ] 4.3 DO NOT introduce a new envelope helper for "list with meta" — `ok_list` is the canonical helper for any list endpoint. Any future list endpoint that needs aggregated meta uses `extra_meta` too.

- [ ] Task 5: Server — gate `/calls/initiate` on `compute_call_usage` (AC: 2, 3)
  - [ ] 5.1 In `server/api/routes_calls.py`, BEFORE the `system_prompt = load_scenario_prompt(...)` call, insert:
    ```python
    async with get_connection() as db:
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "AUTH_UNAUTHORIZED",
                    "message": "Missing or invalid token.",
                },
            )
        usage = await compute_call_usage(db, user_id, user["tier"])
    if usage["calls_remaining"] == 0:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CALL_LIMIT_REACHED",
                "message": "You've used all your calls for now.",
            },
        )
    ```
  - [ ] 5.2 Add imports: `from api.usage import compute_call_usage` and `from db.queries import get_user_by_id, insert_call_session` (the second import already exists; just add `get_user_by_id`).
  - [ ] 5.3 The cap check runs **BEFORE** `load_scenario_prompt`, **BEFORE** `generate_token` / `generate_token_with_agent`, **BEFORE** `insert_call_session`, and **BEFORE** the `subprocess.Popen` bot spawn. A blocked call must not consume a LiveKit token, write a row, or fork a process.
  - [ ] 5.4 The cap-check connection is closed before the rest of the handler opens its own connection — a separate context manager keeps the existing flow untouched. Two short-lived connections are cheaper than refactoring the whole handler to share one.
  - [ ] 5.5 DO NOT introduce a `429` (rate-limit) status. `403` is the architectural status for "tier/limit" per architecture line 318. Reserve `429` for global anti-abuse rate limiting at the Caddy layer.

- [ ] Task 6: Server — add `test_call_usage.py` for the policy unit (AC: 3)
  - [ ] 6.1 Create `server/tests/test_call_usage.py` — pure-policy tests against an in-memory aiosqlite, no FastAPI surface (the route is exercised by `test_scenarios.py` + `test_calls.py`):
    ```python
    """Tests for api.usage.compute_call_usage — the FR21 policy layer."""
    from __future__ import annotations

    import asyncio
    from datetime import datetime, timezone

    import pytest

    # ... import compute_call_usage, register_user fixture, etc.
    ```
  - [ ] 6.2 Tests to write (8 minimum — mirror the AC3 matrix):
    - `test_free_zero_sessions_returns_three_remaining_lifetime`
    - `test_free_one_session_returns_two_remaining`
    - `test_free_three_sessions_returns_zero_remaining_clamped`
    - `test_free_more_than_three_sessions_clamps_to_zero` (insert 5 → expect 0, not -2)
    - `test_paid_zero_sessions_today_returns_three_remaining_day`
    - `test_paid_three_sessions_today_returns_zero_remaining`
    - `test_paid_three_sessions_today_plus_two_yesterday_still_zero` (yesterday irrelevant)
    - `test_paid_zero_today_with_five_yesterday_clean_slate_three_remaining` (UTC midnight reset)
    - (bonus) `test_unknown_tier_raises_value_error` — direct call with `tier='garbage'` raises `ValueError`
  - [ ] 6.3 Use the `now` kwarg of `compute_call_usage` to inject a deterministic `datetime`. Insert call_sessions rows directly via raw SQL (`INSERT INTO call_sessions(user_id, scenario_id, started_at) VALUES (?, ?, ?)`) with hand-picked timestamps that straddle the UTC midnight boundary.
  - [ ] 6.4 Reuse the `register_user` helper from `tests/conftest.py` (already extracted in Story 5.1 cleanup batch). DO NOT re-implement.
  - [ ] 6.5 DO NOT mock `db` — use the real test DB via the existing `test_db_path` + a direct `aiosqlite.connect(test_db_path)`. The policy layer's contract is "pass me a connection and I'll count rows" — mocking the connection breaks the test's value.

- [ ] Task 7: Server — extend `test_scenarios.py` for the meta extension (AC: 1)
  - [ ] 7.1 Add tests that assert the new `meta` keys are present and correct on `GET /scenarios`:
    - `test_meta_includes_usage_for_free_user` — register user, GET `/scenarios`, assert `meta.tier == "free"`, `meta.period == "lifetime"`, `meta.calls_remaining == 3`, `meta.calls_per_period == 3`
    - `test_meta_calls_remaining_decrements_after_initiate` — register, hit `/calls/initiate` once (with `subprocess.Popen` mocked à la `test_calls.py`), then GET `/scenarios`, assert `meta.calls_remaining == 2`
    - `test_meta_period_is_day_for_paid_user` — register, then `UPDATE users SET tier='paid'` via raw SQL, GET `/scenarios`, assert `meta.period == "day"` and `meta.calls_remaining == 3`
    - `test_meta_count_and_timestamp_still_present` — assert the existing `meta.count == 5` + `meta.timestamp` keys did NOT disappear when usage was added (regression guard)
  - [ ] 7.2 The existing `test_envelope_shape` in `test_scenarios.py` (line ~ wherever) checks `meta.count` and `meta.timestamp`. Update it to also assert the four new keys are present (presence only — value correctness is covered by the dedicated tests above).
  - [ ] 7.3 Mock `subprocess.Popen` in any test that hits `/calls/initiate` — copy the `@patch("api.routes_calls.subprocess.Popen")` decorator pattern from `test_calls.py`. DO NOT actually fork a bot process.

- [ ] Task 8: Server — extend `test_calls.py` for the 403 cap path (AC: 2, 3)
  - [ ] 8.1 Add new tests to `server/tests/test_calls.py`:
    - `test_initiate_returns_403_call_limit_reached_when_free_user_exhausted` — register user, insert 3 `call_sessions` rows directly via SQL, POST `/calls/initiate` → assert `status_code == 403` AND `body["error"]["code"] == "CALL_LIMIT_REACHED"`
    - `test_initiate_returns_403_when_paid_user_exhausted_today` — register, `UPDATE users SET tier='paid'`, insert 3 `call_sessions` rows with `started_at = now_iso()` for TODAY, POST `/calls/initiate` → 403
    - `test_initiate_succeeds_when_paid_user_has_calls_yesterday_only` — register, `UPDATE` to paid, insert 3 `call_sessions` rows with `started_at = "2025-01-01T00:00:00Z"` (clearly before today), POST `/calls/initiate` → 200 (cap reset across UTC days)
    - `test_initiate_does_not_persist_when_capped` — register, insert 3 sessions, POST `/calls/initiate` → 403, assert `SELECT COUNT(*) FROM call_sessions WHERE user_id = ?` is still 3 (not 4 — the blocked attempt left no row)
    - `test_initiate_does_not_spawn_bot_when_capped` — same setup, assert the mocked `subprocess.Popen` was NOT called (`mock_popen.assert_not_called()`)
  - [ ] 8.2 Each new test mocks `subprocess.Popen` (so an unblocked call doesn't actually fork) but ALSO checks the negative case (cap → no Popen call).
  - [ ] 8.3 Existing `test_calls.py` tests (the happy `/calls/initiate` paths) must keep passing — registering a fresh user has 3 lifetime calls, so the first call still goes through. ZERO existing tests should regress.

- [ ] Task 9: Client — `CallUsage` model + result type (AC: 4)
  - [ ] 9.1 Create `client/lib/features/scenarios/models/call_usage.dart`:
    ```dart
    class CallUsage {
      final String tier;            // 'free' | 'paid'
      final int callsRemaining;
      final int callsPerPeriod;
      final String period;          // 'lifetime' | 'day'

      const CallUsage({
        required this.tier,
        required this.callsRemaining,
        required this.callsPerPeriod,
        required this.period,
      });

      factory CallUsage.fromMeta(Map<String, dynamic> meta) {
        return CallUsage(
          tier: meta['tier'] as String,
          callsRemaining: meta['calls_remaining'] as int,
          callsPerPeriod: meta['calls_per_period'] as int,
          period: meta['period'] as String,
        );
      }

      bool get isFree => tier == 'free';
      bool get hasCallsRemaining => callsRemaining > 0;
      bool get isLifetimePeriod => period == 'lifetime';
    }
    ```
  - [ ] 9.2 Create a small result type for the repository — keep it in the same `repositories/` folder (NOT a separate models folder for a 5-line wrapper):
    ```dart
    // client/lib/features/scenarios/repositories/scenarios_fetch_result.dart
    import '../models/call_usage.dart';
    import '../models/scenario.dart';

    class ScenariosFetchResult {
      final List<Scenario> scenarios;
      final CallUsage usage;

      const ScenariosFetchResult({required this.scenarios, required this.usage});
    }
    ```
  - [ ] 9.3 DO NOT add `Equatable` / `freezed` / `copyWith`. Same minimalism as `Scenario` (Story 5.2 Dev Notes).
  - [ ] 9.4 DO NOT model the BOC state (`freeWithCalls` / `freeExhausted` / `paidWithCalls` / `paidExhausted`) as an enum here. The widget computes its visual state from `usage.tier` + `usage.callsRemaining` directly — no extra layer. If a future story needs the state literal (analytics?), promote it then.

- [ ] Task 10: Client — extend `ScenariosRepository` to return `ScenariosFetchResult` (AC: 4)
  - [ ] 10.1 Modify `client/lib/features/scenarios/repositories/scenarios_repository.dart`:
    ```dart
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
    ```
  - [ ] 10.2 The repo is still a thin pass-through over `ApiClient`. `ApiException` from `_apiClient.get` continues to propagate (no catch added) — Story 5.2 contract preserved.
  - [ ] 10.3 The Story 5.2 unit tests for the repo (`test/features/scenarios/repositories/scenarios_repository_test.dart`) will fail when this lands — they assert on `List<Scenario>` directly. UPDATE them in Task 13.

- [ ] Task 11: Client — extend `ScenariosBloc` + `ScenariosLoaded` payload (AC: 5)
  - [ ] 11.1 In `client/lib/features/scenarios/bloc/scenarios_state.dart`, change `ScenariosLoaded` from `(List<Scenario>)` to `(List<Scenario>, CallUsage)`:
    ```dart
    final class ScenariosLoaded extends ScenariosState {
      final List<Scenario> scenarios;
      final CallUsage usage;
      const ScenariosLoaded(this.scenarios, this.usage);
    }
    ```
  - [ ] 11.2 Add `import '../models/call_usage.dart';` at the top of `scenarios_state.dart`.
  - [ ] 11.3 In `scenarios_bloc.dart`, the `_onLoad` method emits `ScenariosLoaded(result.scenarios, result.usage)` instead of `ScenariosLoaded(scenarios)`. Pull `result` from `_repository.fetchScenarios()`.
  - [ ] 11.4 Story 5.2 tests that build `ScenariosLoaded(...)` directly (e.g. `scenario_list_screen_test.dart`) get a compile error. UPDATE them — Task 13. This widening is the explicit reason Story 5.2 noted "If Story 5.3 needs the same data on the same route…".
  - [ ] 11.5 DO NOT add a separate `LoadUsageEvent` or `UsageRefreshEvent`. Single fetch, single state — usage is part of the list-screen contract.

- [ ] Task 12: Client — `BottomOverlayCard` widget (AC: 6, 9)
  - [ ] 12.1 Create `client/lib/features/scenarios/views/widgets/bottom_overlay_card.dart` — `StatelessWidget` with required `final CallUsage usage`, optional `final VoidCallback? onPaywallTap` (kept optional because `paidExhausted` ignores tap):
    ```dart
    import 'package:flutter/material.dart';

    import '../../../../core/theme/app_colors.dart';
    import '../../../../core/theme/app_spacing.dart';
    import '../../../../core/theme/app_typography.dart';
    import '../../models/call_usage.dart';

    class BottomOverlayCard extends StatelessWidget {
      final CallUsage usage;
      final VoidCallback? onPaywallTap;

      const BottomOverlayCard({
        super.key,
        required this.usage,
        this.onPaywallTap,
      });
      // ...
    }
    ```
  - [ ] 12.2 The state derivation is a switch-on-`usage.tier`-and-`usage.callsRemaining` pure helper at the top of the file. Three variants need a visible card; `paidWithCalls` returns `SizedBox.shrink()`:
    ```dart
    enum _OverlayVariant { freeWithCalls, freeExhausted, paidExhausted }

    _OverlayVariant? _variantFor(CallUsage usage) {
      if (usage.isFree) {
        return usage.hasCallsRemaining
            ? _OverlayVariant.freeWithCalls
            : _OverlayVariant.freeExhausted;
      }
      // paid
      if (usage.hasCallsRemaining) return null; // BOC absent
      return _OverlayVariant.paidExhausted;
    }
    ```
    Keep `_variantFor` as a top-level free function for testability (mirrors Story 5.2's `_buildCardSemanticsLabel` decision).
  - [ ] 12.3 Build the visible card body once via a helper that takes `(title, subtitle, isActionable)` and wraps a `Container` + `SafeArea(top: false, bottom: false)` + `Row(...)` + `Semantics(button: isActionable, label: ...)`. Keep the build method short — declarative.
  - [ ] 12.4 Title text style — UX-DR5 specifies Inter Bold 14px `#1E1F23`. Use `AppTypography.cardTitle.copyWith(fontSize: 14, color: AppColors.background)`. NO new `AppTypography.overlayTitle` token — adding a token for a single use is premature; promote ONLY if a second site reuses it.
  - [ ] 12.5 Subtitle text style — UX-DR5 specifies Inter Regular 11px `#4C4C4C`. The colour is **NOT in `AppColors`** — see Tech Debt note in Dev Notes. Inline `const Color(0xFF4C4C4C)` is allowed here EXCLUSIVELY because it's the only literal in the file AND the contract is documented in the BOC anatomy comment AND a `// theme-tokens-test allow: overlay subtitle (UX-DR5 line 700)` annotation lives next to the literal so the test exception is auditable. PREFERRED ALTERNATIVE: extend `AppColors` (see Task 14).
  - [ ] 12.6 Diamond icon — use `Icons.diamond_outlined` (Material outline glyph, the closest match to UX line 686 "diamond/gem icon (blue)"). Color: `AppColors.accent` (mint — closest non-monochrome accent in the palette; UX spec says "blue" but the locked palette has no blue token, and the accent serves the same semantic "premium / paywall" cue). Size: `AppSpacing.iconSmall` (24px).
  - [ ] 12.7 The `onPaywallTap` callback wraps the visible card body in either:
    - `InkWell(onTap: ..., behavior: HitTestBehavior.opaque, child: ...)` for the actionable variants — gives a faint ripple on the `#F0F0F0` surface
    - or, for `paidExhausted`, wrap the body without an `InkWell` (no tap target — informational only)
  - [ ] 12.8 The container colour is `AppColors.textPrimary` (`#F0F0F0` — the inverted "light card on dark bg" choice from UX-DR5 line 680). The test will ensure no raw `0xFFF0F0F0` literal sneaks in.
  - [ ] 12.9 Padding extends INTO the safe area: `EdgeInsets.fromLTRB(20, 20, 20, MediaQuery.viewPaddingOf(context).bottom + 20)`. UX-DR5 line 681 verbatim. The 20-px values come from `AppSpacing.overlayCardPadding`.
  - [ ] 12.10 DO NOT add a `BoxShadow` or `Border`. Flat per UX-DR17.
  - [ ] 12.11 DO NOT animate the BOC's appearance/disappearance in this story. State transitions (free → paid via subscribe, paid → free via unsubscribe) are out of scope until Epic 8.

- [ ] Task 13: Client — wire BOC into `ScenarioListScreen` + update Story 5.2 tests (AC: 5, 7)
  - [ ] 13.1 In `client/lib/features/scenarios/views/scenario_list_screen.dart` (created by Story 5.2), replace the `ListView.separated` body with a `Stack`:
    ```dart
    Stack(
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: kBottomOverlayCardEstimatedHeight),
          child: ListView.separated(/* unchanged from 5.2 */),
        ),
        const Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: _OverlayHost(),
        ),
      ],
    )
    ```
    where `_OverlayHost` is a `BlocBuilder<ScenariosBloc, ScenariosState>` that returns `BottomOverlayCard(usage: state.usage, onPaywallTap: () => context.go(AppRoutes.paywall))` when `state is ScenariosLoaded`, else `SizedBox.shrink()`.
  - [ ] 13.2 Define `kBottomOverlayCardEstimatedHeight = 96.0` as a top-level const at the top of `scenario_list_screen.dart` with a comment `// Conservative estimate covers diamond row (44) + padding (20+20) + safe-area inset (~12) on phones 320-430. Off-screen content scrolls past the BOC; the last card is fully readable.`
  - [ ] 13.3 In `scenario_list_screen.dart`, the `Padding(padding: EdgeInsets.symmetric(horizontal: AppSpacing.screenHorizontal, vertical: AppSpacing.screenVerticalList))` from Story 5.2 stays in place around the `Stack` — the BOC pins to the OUTER scaffold edge, not to the padded content area. Wrap accordingly:
    ```dart
    Scaffold(
      backgroundColor: AppColors.background,
      body: Stack(
        children: [
          SafeArea(
            top: true,
            bottom: false,
            child: Padding(
              padding: EdgeInsets.symmetric(/* 5.2 values */),
              child: ListView.separated(/* 5.2 — with bottom padding for BOC */),
            ),
          ),
          const Positioned(left: 0, right: 0, bottom: 0, child: _OverlayHost()),
        ],
      ),
    )
    ```
  - [ ] 13.4 UPDATE `scenarios_repository_test.dart` (5.2 file): the 3 tests now expect `ScenariosFetchResult` instead of `List<Scenario>`. The fixture envelope must include a `meta` block with the four usage keys (`tier: 'free'`, `calls_remaining: 3`, `calls_per_period: 3`, `period: 'lifetime'`).
  - [ ] 13.5 UPDATE `scenarios_bloc_test.dart` (5.2 file): every `ScenariosLoaded(scenarios)` constructor call becomes `ScenariosLoaded(scenarios, const CallUsage(tier: 'free', callsRemaining: 3, callsPerPeriod: 3, period: 'lifetime'))`. Add a top-level `const _kFreshUsage = CallUsage(...)` test helper to keep call sites tidy.
  - [ ] 13.6 UPDATE `scenario_list_screen_test.dart` (5.2 file): all `ScenariosLoaded([scenario1, scenario2])` → `ScenariosLoaded([scenario1, scenario2], _kFreshUsage)`. Add 4 NEW tests covering each BOC variant (see Task 14.3).
  - [ ] 13.7 UPDATE `app_test.dart` if it stubs `ScenariosLoaded` — same constructor widening.

- [ ] Task 14: Client — `BottomOverlayCard` widget tests (AC: 6, 9)
  - [ ] 14.1 Create `client/test/features/scenarios/views/widgets/bottom_overlay_card_test.dart`:
    - `setUp`: `FlutterSecureStorage.setMockInitialValues({})` (transitive — keep the reflex per client/CLAUDE.md §1)
    - `setUp`: `tester.binding.setSurfaceSize(const Size(320, 480))` + `addTearDown(() => tester.binding.setSurfaceSize(null))` — client/CLAUDE.md §7
    - Helper: `Widget _harness({required CallUsage usage, VoidCallback? onTap}) => MaterialApp(theme: AppTheme.dark(), home: Scaffold(body: Stack(children: [Positioned(left: 0, right: 0, bottom: 0, child: BottomOverlayCard(usage: usage, onPaywallTap: onTap))])));`
  - [ ] 14.2 Tests (8 minimum):
    - `freeWithCalls renders Unlock all scenarios + actionable subtitle` — `find.text('Unlock all scenarios')` + `find.text('If you can survive us, real humans don\'t stand a chance')` both `findsOneWidget`
    - `freeExhausted renders Subscribe to keep calling` — `find.text('Subscribe to keep calling')` `findsOneWidget`
    - `paidWithCalls renders SizedBox.shrink (no visible card)` — `find.text('Unlock all scenarios')` + `find.text('Subscribe to keep calling')` + `find.text('No more calls today')` ALL `findsNothing`; the diamond icon is also absent
    - `paidExhausted renders No more calls today + Come back tomorrow + not actionable` — text present; tapping the card does NOT fire the callback
    - `tap on freeWithCalls fires onPaywallTap` — `await tester.tap(find.byType(BottomOverlayCard))`, callback called once
    - `tap on freeExhausted fires onPaywallTap` — same
    - `Semantics announces composed label for freeWithCalls` — find by `bySemanticsLabel('Unlock all scenarios. If you can survive us, real humans don\'t stand a chance. Tap to view subscription options.')`
    - `Semantics is button:false on paidExhausted` — assert via `tester.getSemantics(find.byType(BottomOverlayCard)).hasFlag(SemanticsFlag.isButton)` is `false` (or absent)
  - [ ] 14.3 Add 4 tests to `scenario_list_screen_test.dart`:
    - `BOC visible (free, with calls) when ScenariosLoaded emits free user with calls > 0`
    - `BOC says Subscribe to keep calling when free + 0 calls`
    - `BOC absent when paid + calls > 0`
    - `BOC says No more calls today when paid + 0 calls`
  - [ ] 14.4 Add a `theme_tokens_test.dart` exception ONLY IF Task 12.5 keeps the inline `0xFF4C4C4C`. If Task 14 adds `AppColors.overlaySubtitle = Color(0xFF4C4C4C)` (preferred — see Tech Debt), no exception needed.

- [ ] Task 15: Client — paywall placeholder route (AC: 8)
  - [ ] 15.1 Create `client/lib/features/paywall/views/paywall_placeholder_screen.dart`:
    ```dart
    import 'package:flutter/material.dart';
    import 'package:go_router/go_router.dart';

    import '../../../app/router.dart';
    import '../../../core/theme/app_colors.dart';
    import '../../../core/theme/app_typography.dart';

    class PaywallPlaceholderScreen extends StatelessWidget {
      const PaywallPlaceholderScreen({super.key});

      @override
      Widget build(BuildContext context) {
        return Scaffold(
          backgroundColor: AppColors.background,
          body: SafeArea(
            child: Stack(
              children: [
                Positioned(
                  top: 8,
                  left: 8,
                  child: IconButton(
                    icon: const Icon(Icons.arrow_back),
                    color: AppColors.textPrimary,
                    onPressed: () => context.go(AppRoutes.root),
                  ),
                ),
                Center(
                  child: Text(
                    'Paywall — coming in Story 8.2',
                    style: AppTypography.body.copyWith(color: AppColors.textPrimary),
                  ),
                ),
              ],
            ),
          ),
        );
      }
    }
    ```
  - [ ] 15.2 In `lib/app/router.dart`:
    - Add `static const String paywall = '/paywall';` to `AppRoutes` (after `debrief`).
    - Add a new `GoRoute(path: AppRoutes.paywall, pageBuilder: (context, state) => _fadePage(key: state.pageKey, child: const PaywallPlaceholderScreen()))`.
    - Add the import `import '../features/paywall/views/paywall_placeholder_screen.dart';` alphabetically at the top.
  - [ ] 15.3 DO NOT add a real paywall, subscription flow, or StoreKit/Play Billing code. That's Story 8.x. This is the navigation hook only.
  - [ ] 15.4 Widget test: `client/test/features/paywall/views/paywall_placeholder_screen_test.dart` — 2 tests: renders the placeholder text, tapping back-arrow calls `context.go(AppRoutes.root)`.

- [ ] Task 16: Pre-commit validation gates (AC: 10)
  - [ ] 16.1 `cd server && python -m ruff check .` → zero issues (Windows: `python -m ruff` per memory)
  - [ ] 16.2 `cd server && python -m ruff format --check .` → zero diffs
  - [ ] 16.3 `cd server && pytest` → all green INCLUDING `test_migrations.py` (the prod-snapshot replay — no schema change shipped, so the snapshot stays valid). Expect ~13 new server tests (8 in `test_call_usage.py` + 4 in `test_scenarios.py` + 5 in `test_calls.py`).
  - [ ] 16.4 `cd client && flutter analyze` → "No issues found!" (every info-level lint resolved or silenced with rationale)
  - [ ] 16.5 `cd client && flutter test` → "All tests passed!" — count that the new tests bring the total up by ~14 (8 BOC + 4 list-screen overlay variants + 2 paywall) AND the Story 5.2 tests still pass after the `ScenariosLoaded` widening + repo result type change
  - [ ] 16.6 Update `sprint-status.yaml`: `5-3-build-bottomoverlaycard-and-daily-call-limit-enforcement: backlog → in-progress` AT START, `in-progress → review` AT END (after Smoke Test Gate is filled). Memory rule (Epic 1 Retro Lesson): non-negotiable.
  - [ ] 16.7 **DO NOT commit autonomously.** Memory rule (Git Commit Rules): wait for `/commit` or "commit ça". Dev workflow stops at `review` status with the Smoke Test Gate filled.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story modifies a server endpoint (`GET /scenarios` envelope) and adds a new server-side enforcement path on `POST /calls/initiate`. Smoke Test Gate is **required** before flipping to review. NO DB migration ships in this story (queries only) — the migration-backup gate is N/A.
>
> **Transition rule:** Every unchecked box below is a stop-ship for the `in-progress → review` transition. Paste the actual command run and its output as proof — a checked box without evidence does not count.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->

- [ ] **Happy-path `GET /scenarios` envelope carries the new `meta.usage` keys.** Production-like curl returns the `{data, meta}` envelope where `meta` includes `tier`, `calls_remaining`, `calls_per_period`, `period` alongside `count` + `timestamp`.
  - _Command:_ `curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/scenarios | jq '.meta'`
  - _Expected:_ `{"timestamp": "...Z", "count": 5, "tier": "free", "calls_remaining": 3, "calls_per_period": 3, "period": "lifetime"}`
  - _Actual:_ <!-- paste output -->

- [ ] **`POST /calls/initiate` enforces the cap and returns the `{error}` envelope with `CALL_LIMIT_REACHED`.** A free-tier user with 3 lifetime `call_sessions` rows hits the cap.
  - _Command:_ `curl -sS -o /tmp/body -w "%{http_code}\n" -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{}' http://167.235.63.129/calls/initiate; cat /tmp/body | jq`
  - _Expected:_ `403` + `{"error": {"code": "CALL_LIMIT_REACHED", "message": "..."}}`
  - _Actual:_ <!-- paste output -->

- [ ] **DB side-effect verified — blocked attempt did NOT insert a `call_sessions` row.** Read back the prod DB at `/opt/survive-the-talk/data/db.sqlite` and confirm the row count for the test user is unchanged. **Note:** the VPS does NOT have the `sqlite3` CLI installed — query via the venv's stdlib instead.
  - _Command:_ `ssh root@167.235.63.129 "/opt/survive-the-talk/repo/server/.venv/bin/python -c 'import sqlite3; c=sqlite3.connect(\"/opt/survive-the-talk/data/db.sqlite\"); [print(r) for r in c.execute(\"SELECT user_id, COUNT(*) FROM call_sessions GROUP BY user_id\")]'"`
  - _Expected:_ test user_id has the same count BEFORE and AFTER the blocked POST (cap-hit attempt left no orphan row)
  - _Actual:_ <!-- paste rows -->

- [ ] **Paid-tier path verified — `meta.period` flips to `day`.** Promote the test user to `tier='paid'` via direct SQL, hit `GET /scenarios`, confirm meta.
  - _Command:_ `ssh root@167.235.63.129 "/opt/survive-the-talk/repo/server/.venv/bin/python -c 'import sqlite3; c=sqlite3.connect(\"/opt/survive-the-talk/data/db.sqlite\"); c.execute(\"UPDATE users SET tier=? WHERE id=?\", (\"paid\", $USER_ID)); c.commit()'"; curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/scenarios | jq '.meta.tier, .meta.period'`
  - _Expected:_ `"paid"` then `"day"` (calls_remaining resets to 3 because today UTC has 0 sessions for this user)
  - _Actual:_ <!-- paste output -->
  - _Cleanup:_ revert the user back to `'free'` after the smoke test (or leave for follow-up Epic 8 work — note which choice in the proof block).

- [ ] **DB backup taken BEFORE deploy.** N/A — this story ships no migration. Mark with one-line rationale.
  - _Rationale:_ <!-- e.g. "Story 5.3 ships zero schema changes — `ls /opt/survive-the-talk/data/` shows no new `db.sqlite.bak-*` file because none was needed; pre-deploy SHA snapshot is sufficient." -->

- [ ] **Server logs clean on the happy + blocked paths.** `journalctl -u pipecat.service -n 100 --since "5 min ago"` shows no ERROR / Traceback for the requests fired above; the blocked POST shows the expected `403 CALL_LIMIT_REACHED` audit line.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

## Dev Notes

### Scope Boundary (What This Story Does and Does NOT Do)

| In scope (this story) | Out of scope (later stories) |
|---|---|
| `meta.usage` extension on `GET /scenarios` (tier/remaining/period/cap) | A standalone `GET /user/profile` endpoint — folded into `/scenarios` for MVP simplicity (architecture line 306 stays as future contract for Epic 8) |
| `compute_call_usage` policy module + 8 unit tests | Tier rebalance UI / admin tooling (`CALLS_PER_PERIOD = 3` is a code constant) |
| `POST /calls/initiate` 403 `CALL_LIMIT_REACHED` enforcement | Client-side handling of the 403 response on `/call` — Story 6.1 wires the real call screen and its error states |
| `BottomOverlayCard` widget — 4 UX-DR5 states | `PaywallScreen` (Story 8.2) — placeholder route only |
| `CallUsage` model + repo result widening + bloc state widening | StoreKit 2 / Play Billing integration — Story 8.1 |
| Paywall placeholder route (`/paywall`) | Subscription-status persistence (`tier='paid'` is set today only via direct SQL) |
| Smoke Test Gate (server-touching story) | Day-boundary localisation (UTC midnight is a known limitation — see Tech Debt) |

### Usage policy (the FR21 contract — exact rules)

**Free tier (`users.tier = 'free'`):**
- 3 calls **lifetime** (no recharge — FR21 verbatim "no daily recharge")
- `calls_remaining = max(0, 3 - count(call_sessions WHERE user_id=?))`
- `period = 'lifetime'`

**Paid tier (`users.tier = 'paid'`):**
- 3 calls **per UTC day** (UTC midnight reset)
- `calls_remaining = max(0, 3 - count(call_sessions WHERE user_id=? AND started_at >= utc_midnight_today))`
- `period = 'day'`

**Why UTC, not user-local time?**
- Architecture line 550: "Dates: ISO 8601 UTC always" — the entire backend is UTC.
- Mobile clients send no time-zone metadata in JWT or API requests today.
- A US-West user calling at 11 PM PST would see "calls remaining: 0" until 4 PM the next day. Acceptable for MVP — fix is a Story 8.x +1 once subscription management ships and we have user TZ from the App Store metadata.
- Documented as a Known Limitation in `deferred-work.md` under Epic 5.

**Why a literal `CALLS_PER_PERIOD = 3` and not a `Settings` env var?**
- The constant is a product decision (FR21), not an operator decision. A future rebalance ships with code review + a regression test update — not a quiet env-var nudge.
- Keeps the migration story honest: no `.env` drift between local + VPS.

### API contract — extended `meta` block

Before this story (Story 5.1):
```json
{
  "data": [...],
  "meta": { "count": 5, "timestamp": "2026-04-27T12:00:00Z" }
}
```

After this story:
```json
{
  "data": [...],
  "meta": {
    "count": 5,
    "timestamp": "2026-04-27T12:00:00Z",
    "tier": "free",
    "calls_remaining": 2,
    "calls_per_period": 3,
    "period": "lifetime"
  }
}
```

The `data` array shape is unchanged — Story 5.2's `Scenario.fromJson` keeps working.

### Error contract — `CALL_LIMIT_REACHED`

```json
HTTP/1.1 403 Forbidden
Content-Type: application/json

{
  "error": {
    "code": "CALL_LIMIT_REACHED",
    "message": "You've used all your calls for now."
  }
}
```

The message is intentionally generic — the BOC carries the period-specific copy ("Subscribe to keep calling" vs "Come back tomorrow"). The `code` is what clients branch on; the `message` is a fallback for clients that don't know the code (none today, but futureproofing).

### Why no new endpoint (`GET /user/profile`)?

Architecture line 306 lists `GET /user/profile` returning "tier, stats, progression". Three reasons it doesn't ship in this story:

1. **MVP discipline** — every BOC render needs `tier + calls_remaining`. The scenario list is the screen that renders the BOC. A second round trip on the same screen mount is gratuitous.
2. **Refresh semantics** — when the user comes back from a call, the BOC must reflect the new `calls_remaining`. The `/scenarios` fetch already runs on route revisit (route-scoped bloc). Folding usage into the same envelope means the BOC refreshes for free.
3. **Future-compat** — Epic 8 (paywall + subscription) and Epic 7 (debrief progression aggregate) will need `/user/profile`. Adding it now without a real consumer is YAGNI; adding it then is a clean delta.

If a future story (Epic 7?) needs tier/usage off-screen-from-the-list, that's the moment to extract `compute_call_usage` into a `/user/profile` endpoint — `compute_call_usage` is already designed to be reusable.

### Bottom inset / Stack architecture (AC7)

Why a `Stack` instead of a `Column`?

- **Pinned-to-edge requirement** — UX-DR5 line 678 "Position: Fixed bottom, extends INTO safe area". A `Column` with a fixed-height `BottomOverlayCard` and a flex'd `ListView` works visually but the BOC scrolls AWAY from the bottom safe-area inset on Android keyboards / 3-button-nav variations. `Stack + Positioned(bottom: 0)` is the idiomatic Flutter pattern for "always at screen edge regardless of inner scroll state".
- **Bottom padding strategy** — the `ListView.separated` gets a static bottom padding (`kBottomOverlayCardEstimatedHeight = 96.0`) so the last `ScenarioCard` is fully visible above the BOC. Why not measure the BOC's actual height with a `LayoutBuilder` or `Size.zero` trick? Because measure-then-relayout creates a one-frame jitter and adds 30 lines of state for a 16-px optical difference. A static estimate (44 row + 40 padding + ~12 safe-area) is "correct enough" for phones 320-430 — measured against UX-DR18's range.
- **`paidWithCalls` (no card)** — the BOC returns `SizedBox.shrink()`, so there's effectively zero overlay. The list's bottom padding stays — a tiny gap below the last card is acceptable (and matches the "clean list" UX-DR5 line 708).

### Tap target rendering (AC9)

`InkWell` vs `GestureDetector` on a `#F0F0F0` surface:

- **`InkWell`**: tappable variants (`freeWithCalls`, `freeExhausted`) — gives a faint ripple on the off-white surface. Visually consistent with the rest of the app's interaction style. The ripple respects `Material` ancestor (the `Scaffold` provides one).
- **`GestureDetector`**: not ideal here — no visual tap feedback, accessibility a11y treatment is identical, but the missing ripple makes the actionability less discoverable.
- **No tap wrapper** for the informational variant (`paidExhausted`) — wrapping in an `InkWell` with `onTap: null` would still show the ripple (Material 3 default on tap-but-disabled), confusing users into thinking it's actionable.

### Tech Debt (must-track for `deferred-work.md`)

1. **`#4C4C4C` overlay subtitle hex literal** — UX-DR5 specifies this colour; it's not in the locked `AppColors` palette. Two responses, pick one:
   - **(a) PREFERRED** — extend `AppColors` with `static const Color overlaySubtitle = Color(0xFF4C4C4C);`. Add to the `values` list (count goes 9 → 10, update the assertion in `theme_tokens_test.dart`). Document the contrast ratio in the AppColors comment block (5.7:1 on `textPrimary` background — passes WCAG AA per UX-DR1 line 14-15). This is the cleanest path and is explicitly anticipated by `app_colors.dart:14-15` ("overlay card subtitle 5.7:1").
   - **(b) ACCEPTABLE** — single inline `const Color(0xFF4C4C4C)` in the BOC widget with a `// theme-tokens-test allow:` annotation. `theme_tokens_test.dart` would need an exception list — adds drift risk.
   Default to (a). The contrast ratio is already pre-validated in the AppColors comment block.

2. **UTC day boundary for paid-tier daily cap** — see "Why UTC, not user-local time?" above. Defer to post-Epic-8 (subscription management ships user TZ).

3. **Static BOC height estimate (`kBottomOverlayCardEstimatedHeight = 96.0`)** — works for phones 320-430 today. If scaling to tablets or accessibility text scaler ≥ 2.0, revisit by adopting a `LayoutBuilder` measurement pass. Acceptable for MVP launch.

4. **Generic 403 message** — clients map `CALL_LIMIT_REACHED` to the BOC's exact copy. If a non-Flutter client (CLI debug tool?) hits the endpoint, it sees the generic "You've used all your calls for now." which doesn't expose the cap value. Acceptable trade-off — not a debt item, just a contract note.

### What NOT to Do

1. **Do NOT add a `/user/profile` endpoint in this story.** Folded into `/scenarios.meta`. See Dev Notes → "Why no new endpoint".
2. **Do NOT add a daily-cap UI counter ("2 calls left today").** UX-DR5 doesn't show a numeric counter — just the binary "calls remaining vs exhausted" branch. Adding a counter is feature creep + a translation/i18n problem post-MVP.
3. **Do NOT introduce a `429` status for the cap.** `403` per architecture line 318 (tier/limit). `429` is reserved for global anti-abuse (Caddy-layer).
4. **Do NOT lazy-load the BOC.** It's part of the same `BlocBuilder` cycle as the list — single emission, single render, single logical state.
5. **Do NOT mock `subprocess.Popen` in the cap-rejection tests.** Wait — this is the opposite: DO mock it (so `200`-path branches don't fork), but ASSERT it was NOT called when the 403 fires. The mock is the witness, not the bypass.
6. **Do NOT touch `migrate-to-releases.sh` / `setup-vps.sh` / `deploy-server.yml`.** This story ships zero deploy-pipeline changes — the existing 5.1-CI-deploy plumbing stays in place.
7. **Do NOT change `Scenario.fromJson`.** The list-item shape is unchanged. The repository / bloc absorbs the new `meta.usage` payload.
8. **Do NOT add an `Equatable` package.** Same minimalism rule as Story 5.2 (`pubspec.yaml` untouched).
9. **Do NOT promote `BottomOverlayCard` to a global widget under `core/widgets/`.** It's scenario-list-specific. If Story 8.2's PaywallSheet wants a similar diamond row, refactor THEN. YAGNI now.
10. **Do NOT animate the BOC's appearance/disappearance.** Tier/state changes happen on route revisit (full screen rebuild) — animation adds complexity for an invisible MVP win.
11. **Do NOT enforce the cap client-side in `/call` route's `extra:` extraction.** The server is the single source of truth. The client renders state, the server enforces. A double-gate is duplicate logic that drifts.
12. **Do NOT refresh the BOC mid-call.** The bloc fetches on route mount only. When the user returns from a call (Story 6.1), the route remounts and the bloc re-fetches — that's the refresh point. This is a feature, not a bug.
13. **Do NOT add a "remaining call counter" toast / banner anywhere.** UX-DR5 is the single surface for the call-limit signal. Inline or modal counters would compete and dilute the BOC.
14. **Do NOT promote `tier`/`usage` to a top-level `MultiBlocProvider`.** Route-scoped via `ScenariosBloc`. If Story 6.x or 7.x needs `usage` off the list screen, they fetch their own (or pass via `extra:` on navigation).
15. **Do NOT forget to update `sprint-status.yaml`** at start AND before review (Epic 1 Retro Lesson).
16. **Do NOT commit autonomously** — wait for `/commit` or "commit ça" (project memory: Git Commit Rules).
17. **Do NOT skip the Smoke Test Gate.** This is a server-touching story. Every box must be filled with real proof — Epic 4 retro AI-B made this non-optional.
18. **Do NOT introduce a `tier` claim in the JWT.** Tier is read from the DB on every request — keeps the source of truth singular and supports tier flips without re-issuing tokens. Performance is non-issue at MVP scale (~500 users, 1 SELECT per request).

### Library & Version Requirements

**No new server dependencies.** Everything is stdlib:
- `aiosqlite ^0.20` (existing) — `Connection` / `Row` typing
- `pydantic ^2` (existing) — schemas
- `fastapi ^0.115` (existing) — `APIRouter`, `HTTPException`
- `python ^3.13` (existing) — `datetime.UTC` (PEP 615 alias)

**No new Flutter dependencies.** Everything in `pubspec.yaml`:
- `flutter_bloc ^9.1.1`
- `dio ^5.9.2` (via `ApiClient`)
- `go_router ^17.2.1`
- `bloc_test ^10.0.0`
- `mocktail ^1.0.5`
- `flutter_secure_storage ^10.0.0` (transitive)

### Key Imports (exact — Epic 1 Retro Lesson: #1 velocity multiplier)

```python
# server/api/usage.py
from datetime import UTC, datetime

import aiosqlite

from db.queries import (
    count_user_call_sessions_since,
    count_user_call_sessions_total,
)
```

```python
# server/api/routes_scenarios.py (additions)
from api.usage import compute_call_usage
from db.queries import get_user_by_id  # already had get_all_scenarios_with_progress + get_scenario_by_id_with_progress
```

```python
# server/api/routes_calls.py (additions)
from api.usage import compute_call_usage
from db.queries import get_user_by_id  # already had insert_call_session
```

```python
# server/tests/test_call_usage.py
import asyncio
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from api.usage import compute_call_usage
```

```dart
// client/lib/features/scenarios/models/call_usage.dart
// (no imports needed — pure Dart)
```

```dart
// client/lib/features/scenarios/repositories/scenarios_fetch_result.dart
import '../models/call_usage.dart';
import '../models/scenario.dart';
```

```dart
// client/lib/features/scenarios/repositories/scenarios_repository.dart
import '../../../core/api/api_client.dart';
import '../models/call_usage.dart';
import '../models/scenario.dart';
import 'scenarios_fetch_result.dart';
```

```dart
// client/lib/features/scenarios/views/widgets/bottom_overlay_card.dart
import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_spacing.dart';
import '../../../../core/theme/app_typography.dart';
import '../../models/call_usage.dart';
```

### Previous Story Intelligence

**From Story 5.2 (Scenario List Screen + ScenarioCard):**
- `ScenarioListScreen` is the parent screen. The Stack-with-overlay refactor preserves Story 5.2's `Padding(symmetric)` + `SafeArea(top: true, bottom: false)` while adding the `Positioned(bottom: 0)` BOC.
- `ScenariosBloc` is route-scoped (created in `router.dart`'s `pageBuilder` for `/`). Story 5.3 leaves that lifecycle as-is — `ScenariosLoaded` widening is internal to the bloc/state file.
- Theme-tokens test (`theme_tokens_test.dart`) is green and must stay green. The `#4C4C4C` overlay subtitle is the one new hex; the preferred fix is to add it to `AppColors` (Tech Debt #1).
- `Scenario.fromJson` consumes the `data` array unchanged — `meta.usage` is parsed at the repository boundary, not in `Scenario`.
- Inline error UX (Story 5.2 AC3 + `feedback_error_ux.md`): the error display for `ScenariosError` stays inline. The BOC simply doesn't render in the error state.
- Sealed-state widening (`ScenariosLoaded(scenarios)` → `ScenariosLoaded(scenarios, usage)`) is the explicit "hand-off seam" Story 5.2 anticipated in its router note.
- The `LoadScenariosEvent` is non-const (per `auth_state.dart` precedent) — keep it that way after the widening.

**From Story 5.1 (Scenarios API + DB):**
- `users.tier` is `'free' | 'paid'` after migration 003 (ADR 002). NEVER use `'full'`.
- `call_sessions(user_id, scenario_id, started_at, duration_sec, cost_cents)` is the schema. `started_at` is ISO 8601 UTC.
- Migration 005 added `FK call_sessions.scenario_id → scenarios.id`. Story 5.3 doesn't touch the schema, but if a `call_sessions` row needs to be inserted in a test, `scenario_id` must reference a seeded scenario id (e.g. `'waiter_easy_01'`).
- `ok_list` already accepts a list of Pydantic models or dicts. Story 5.3 widens it to accept `extra_meta` — backward-compat preserved.
- `_safe_json_load` / `SCENARIO_CORRUPT` paths are out of scope here — meta extension doesn't touch JSON-in-TEXT columns.
- `register_user` helper lives in `tests/conftest.py` — reuse it.
- `test_migrations.py` replays migrations against `prod_snapshot.sqlite`. Story 5.3 ships zero migrations, so the snapshot stays valid — DO NOT refresh it.

**From Story 4.5 (Call Initiate + First-Call UX):**
- `subprocess.Popen` mocking pattern: `@patch("api.routes_calls.subprocess.Popen")`. Use it in every new `test_calls.py` test that exercises a 200-path call.
- `mock_resend` fixture is required for any test that registers a user via `/auth/request-code`.
- `lifespan` in `api/app.py` runs migrations + seed. No change needed for this story.
- Route-scoped `BlocProvider` pattern: `ScenariosBloc` is created INSIDE the GoRoute `pageBuilder`. Lifetime tied to the screen.

**From Story 4.2 (Auth + JWT):**
- `AUTH_DEPENDENCY` on the `APIRouter` level — `routes_calls.py` and `routes_scenarios.py` both already use it. No change.
- `request.state.user_id` is available in every protected handler. The `tier` is NOT — fetch via `get_user_by_id(db, user_id)` when needed.
- `http_exception_handler` wraps `HTTPException(detail={"code": ..., "message": ...})` into `{"error": {...}}`. Use it for `CALL_LIMIT_REACHED`.

**From Epic 4 Retro (2026-04-23):**
- **AI-B Smoke Test Gate**: required for any server-touching or DB-touching story. This story modifies `/scenarios` envelope + adds `/calls/initiate` enforcement → gate is required. NO migration → DB-backup gate marked N/A.
- **client/CLAUDE.md gotchas** (especially §1, §2, §4, §6, §7) apply to every Flutter test in this story.
- Walid's MVP iteration strategy (`feedback_mvp_iteration_strategy.md`): build the straight-line story, iterate on render. The BOC's exact pixel padding / icon glyph / micro-copy is up for Walid's review iteration after dev-story lands.

**From Epic 5 ADRs (2026-04-23):**
- **ADR 002 — Tier Naming**: canonical literal is `'paid'`. Any occurrence of `'full'` in new code is a bug.
- **ADR 001 — Scenarios Schema**: not directly relevant here (no scenario column changes), but `is_free` per scenario stays the per-scenario lock affordance — orthogonal to per-user tier.

### Git Intelligence

Recent commit pattern to follow:
```
05295fb feat: 5.1-migration-guardrail harden snapshot sanitisation + self-checks
8c9b9a9 fix: 5.1-CI-deploy harden setup-vps pubkey path + bridge .env strip
7534818 feat: Story 5.1 scenarios API + 5.1-CI-deploy pipeline
4ac116a feat: 5.1-CI-deploy: point pipecat.service at atomic release symlink
b0a804e feat: close Epic 4 retro action items and create Story 5.1
```

Expected commit title when Walid says "commit ça":
```
feat: build BottomOverlayCard and daily call limit enforcement (Story 5.3)
```

**Files to read before starting (patterns, not modify beyond tasks):**
- `client/CLAUDE.md` — Flutter Gotchas §1-10. READ FIRST. §1, §2, §4, §6, §7 are all relevant here.
- `_bmad-output/implementation-artifacts/5-1-build-scenarios-api-and-database.md` — `GET /scenarios` envelope contract, `users.tier` policy, migration / test idioms
- `_bmad-output/implementation-artifacts/5-2-build-scenario-list-screen-with-scenariocard-component.md` — `ScenarioListScreen` shape, `ScenariosBloc` patterns, theme-token discipline (THIS STORY MODIFIES files Story 5.2 creates — read both)
- `_bmad-output/planning-artifacts/ux-design-specification.md` lines 670-709 + 994-1018 — BOC anatomy + four states + accessibility (the canonical UX source)
- `_bmad-output/planning-artifacts/epics.md:944-975` — Story 5.3 BDD source
- `_bmad-output/planning-artifacts/architecture.md` lines 240-310 (data model + endpoints) + line 318 (HTTP status codes) + line 550 (UTC dates)
- `_bmad-output/planning-artifacts/adr/002-tier-naming.md` — `'paid'` canonical
- `server/api/responses.py` — `ok` / `ok_list` envelope idiom
- `server/api/routes_scenarios.py` — list endpoint to extend
- `server/api/routes_calls.py` — initiate endpoint to gate
- `server/api/middleware.py` — `AUTH_DEPENDENCY` + `request.state.user_id`
- `server/db/queries.py` — raw-SQL contract layer
- `server/tests/conftest.py` — `register_user` helper
- `server/tests/test_calls.py` — Popen-mocking pattern
- `server/tests/test_scenarios.py` — meta-assertion pattern
- `client/lib/features/scenarios/repositories/scenarios_repository.dart` — Story 5.2 repo to widen
- `client/lib/features/scenarios/bloc/scenarios_state.dart` — `ScenariosLoaded` to widen
- `client/lib/core/theme/app_colors.dart` — palette to extend (Tech Debt #1)
- `client/lib/app/router.dart` — `AppRoutes` + `GoRoute` registration

### Testing Requirements

**Server target:** ~13 new Python tests.

| File | Count | Scope |
|---|---|---|
| `test_call_usage.py` | 8-9 | tier × period × edge-case matrix (AC3) |
| `test_scenarios.py` (additions) | 4 | meta extension keys, decrement after initiate, paid switch, regression on existing keys |
| `test_calls.py` (additions) | 5 | 403 path, paid yesterday-only allow, no-row side-effect, no-Popen on cap, regression of happy path |

**Client target:** ~14 new Dart tests + edits to ~5 existing tests.

| File | Count | Scope |
|---|---|---|
| `bottom_overlay_card_test.dart` | 8 | 4 states + 2 tap callbacks + 2 semantics |
| `scenario_list_screen_test.dart` (additions) | 4 | BOC visible/absent per state |
| `paywall_placeholder_screen_test.dart` | 2 | renders + back-arrow nav |
| `scenarios_repository_test.dart` (edits) | — | result-type widening |
| `scenarios_bloc_test.dart` (edits) | — | `ScenariosLoaded` ctor widening |
| `call_usage_test.dart` (NEW) | 4 | `fromMeta` happy + missing-key + accessor flags |

**Mock strategy:**
- **Server:** mock `subprocess.Popen` in `test_calls.py` (existing pattern). Real `aiosqlite` connection via `test_db_path`. NO mocking of `compute_call_usage` — it's the unit under test.
- **Client:** mock `ScenariosRepository` in `scenarios_bloc_test.dart`. Mock `ApiClient` in `scenarios_repository_test.dart`. `MockBloc<ScenariosEvent, ScenariosState>` in widget tests (mirrors Story 5.2).

**Harness helpers:**
- A `_kFreshUsage` const at the top of `scenarios_bloc_test.dart` and `scenario_list_screen_test.dart` keeps `ScenariosLoaded(...)` ctor calls one-line.

### Project Structure Notes

**New files (create):**
```
server/
├── api/
│   └── usage.py                                # compute_call_usage policy
└── tests/
    └── test_call_usage.py                      # 8-9 policy tests

client/lib/features/
├── scenarios/
│   ├── models/
│   │   └── call_usage.dart                     # CallUsage model
│   ├── repositories/
│   │   └── scenarios_fetch_result.dart         # result wrapper
│   └── views/widgets/
│       └── bottom_overlay_card.dart            # BOC widget
└── paywall/
    └── views/
        └── paywall_placeholder_screen.dart     # /paywall stub

client/test/features/
├── scenarios/
│   ├── models/
│   │   └── call_usage_test.dart                # 4 model tests
│   └── views/widgets/
│       └── bottom_overlay_card_test.dart       # 8 BOC tests
└── paywall/
    └── views/
        └── paywall_placeholder_screen_test.dart # 2 stub tests
```

**Files to modify (server):**
- `server/api/responses.py` — `ok_list(items, *, extra_meta=None)`
- `server/api/routes_scenarios.py` — fold `meta.usage` into list response
- `server/api/routes_calls.py` — gate `/calls/initiate` on cap
- `server/db/queries.py` — `count_user_call_sessions_total` + `count_user_call_sessions_since`
- `server/tests/test_scenarios.py` — 4 new tests + 1 envelope-shape edit
- `server/tests/test_calls.py` — 5 new tests

**Files to modify (client):**
- `client/lib/features/scenarios/repositories/scenarios_repository.dart` — return `ScenariosFetchResult`
- `client/lib/features/scenarios/bloc/scenarios_bloc.dart` — emit widened `ScenariosLoaded`
- `client/lib/features/scenarios/bloc/scenarios_state.dart` — `ScenariosLoaded(scenarios, usage)`
- `client/lib/features/scenarios/views/scenario_list_screen.dart` (Story 5.2 file) — `Stack` + `Positioned` overlay host
- `client/lib/app/router.dart` — `AppRoutes.paywall` + `GoRoute` + import
- `client/lib/core/theme/app_colors.dart` — add `overlaySubtitle = Color(0xFF4C4C4C)` (Tech Debt #1, Option a)
- `client/test/core/theme/theme_tokens_test.dart` — assert `AppColors.values.length == 10` if option (a) is taken
- `client/test/features/scenarios/repositories/scenarios_repository_test.dart` — `ScenariosFetchResult` assertions
- `client/test/features/scenarios/bloc/scenarios_bloc_test.dart` — widened `ScenariosLoaded`
- `client/test/features/scenarios/views/scenario_list_screen_test.dart` — BOC variants + widened `ScenariosLoaded`
- `client/test/app_test.dart` — if it stubs `ScenariosLoaded`, widen the stubs

**Files to verify but DO NOT modify:**
- `server/db/migrations/*.sql` — IMMUTABLE (no new migration in this story)
- `server/db/seed_scenarios.py` — Story 5.1 contract
- `server/tests/test_migrations.py` + `tests/fixtures/prod_snapshot.sqlite` — replay-against-snapshot still passes (no schema change)
- `server/api/middleware.py` — `AUTH_DEPENDENCY` unchanged
- `client/lib/features/scenarios/models/scenario.dart` — `Scenario` model unchanged
- `client/lib/features/scenarios/views/widgets/scenario_card.dart` (Story 5.2 file) — untouched
- `client/lib/core/theme/app_spacing.dart` — already has `overlayCardPadding`, `overlayIconTextGap`, `overlayLineGap` (added in Story 4.1b prep) — reuse them
- `client/pubspec.yaml` — no new deps
- `_bmad-output/planning-artifacts/architecture.md` — unchanged (folding into `/scenarios.meta` is consistent with the documented data envelope)

### References

- [Source: `_bmad-output/planning-artifacts/epics.md:944-975`] — Story 5.3 BDD acceptance criteria
- [Source: `_bmad-output/planning-artifacts/epics.md#FR21`] (line 52) — daily call limits policy (free=3 lifetime, paid=3/day)
- [Source: `_bmad-output/planning-artifacts/epics.md#FR20`] (line 51) — free vs paid scenario access (orthogonal to call cap)
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR5`] (line 209) — BottomOverlayCard four-state spec
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR12`] (line 223) — screen reader announcements
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR17`] (line 233) — monochrome list (BOC inverted is the EXPLICIT exception)
- [Source: `_bmad-output/planning-artifacts/epics.md#UX-DR18`] (line 235) — responsive 320-430 px + safe-area extension
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md`] lines 670-709 — Bottom Overlay Card validated layout
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md`] lines 994-1018 — BottomOverlayCard component spec
- [Source: `_bmad-output/planning-artifacts/architecture.md`] lines 240-310 — data model (`users.tier`, `call_sessions`) + endpoint table
- [Source: `_bmad-output/planning-artifacts/architecture.md`] line 318 — HTTP 403 for tier/limit
- [Source: `_bmad-output/planning-artifacts/architecture.md`] line 550 — ISO 8601 UTC always
- [Source: `_bmad-output/planning-artifacts/adr/002-tier-naming.md`] — `'paid'` canonical literal
- [Source: `_bmad-output/implementation-artifacts/5-1-build-scenarios-api-and-database.md`] — `/scenarios` envelope, `ok_list`, migration 003 tier rename
- [Source: `_bmad-output/implementation-artifacts/5-2-build-scenario-list-screen-with-scenariocard-component.md`] — ScenarioListScreen + ScenariosBloc + theme-token discipline (this story extends those files)
- [Source: `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md#AI-B`] — Smoke Test Gate non-optional for server stories
- [Source: `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md#AI-A`] — `client/CLAUDE.md` Flutter gotchas
- [Source: `client/CLAUDE.md`] — 10 Flutter gotchas (tests, lints, error UX)
- [Source: `client/lib/core/theme/app_colors.dart:14-15`] — pre-validated 5.7:1 contrast for the BOC subtitle (`#4C4C4C` on `#F0F0F0`)
- [Source: `CLAUDE.md`] — pre-commit gates + migration testing rule (snapshot replay)
- [Source: project memory `feedback_error_ux.md`] — inline error pattern (BOC absent in error state)
- [Source: project memory `feedback_mvp_iteration_strategy.md`] — straight-line story, iterate on render
- [Source: project memory (Git Commit Rules)] — NEVER autonomous commit, no Co-Authored-By, sprint-status discipline

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
