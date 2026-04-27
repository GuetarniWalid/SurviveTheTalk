# Deferred Work

Items flagged during code review but postponed — each entry records where the review surfaced it and why it was not actioned at the time.

## Deferred from: code review of story 4-5-build-first-call-incoming-call-experience (2026-04-23)

- **Bot subprocess never reaped** — `server/api/routes_calls.py:63-76` fires `subprocess.Popen` and never tracks it. Real lifecycle (terminate on call-end, zombie cleanup) belongs to Epic 6.4 / 7.1 via `POST /calls/{id}/end`.
- **`CallPlaceholderScreen` has no LiveKit timeout / reconnect / disconnect-event handler** — `call_placeholder_screen.dart:34-60` silently hangs on "Connecting to Tina…" if the room never comes up. Spec scopes real call UX (including error recovery) to Epic 6.2 Story 6.2.
- **Mic permission revoked between onboarding and `/call` not user-guided** — `call_placeholder_screen.dart:44-58` catches the failure and shows a generic "Couldn't connect" without offering a path back to settings. Epic 6.2 owns the real mic-error UX.
- **No rate-limit / per-user in-flight guard on `/calls/initiate`** — `routes_calls.py:33-101` allows unbounded subprocess spawns per user. Post-MVP infrastructure concern (middleware / Redis / idempotency key).
- **Migration `002_calls.sql` has no explicit `ON DELETE` policy on `user_id` FK** — defaults to `NO ACTION`, which blocks user deletion when call rows exist. Intentional (preserves audit trail) but undocumented; re-visit when user deletion / GDPR erasure lands.

## Deferred from: code review of story 5-1-build-scenarios-api-and-database (2026-04-24)

- **`run_migrations()` + `executescript` breaks outer `BEGIN IMMEDIATE` atomicity** — `server/db/database.py:82-104` wraps each migration in `BEGIN IMMEDIATE`, re-checks `schema_migrations`, then calls `db.executescript(sql)` which silently COMMITs the outer transaction before running the script. Consequence: (1) the `INSERT INTO schema_migrations(...)` is no longer atomic with the DDL — a crash mid-script can leave the DB partially migrated with no tracking row, (2) the "workers serialise via the lock" claim in the docstring is broken for any migration whose script takes >1 statement. Pre-existing in 001/002; amplified by 003-006 which each carry their own `BEGIN;/COMMIT;`. Root fix = rework `run_migrations` to split statements instead of using `executescript`, or switch to `isolation_level=None` + explicit savepoints.
  - **When to address**: before the first migration that (a) runs multiple DDL statements that MUST be atomic with `schema_migrations` insertion (e.g. a data migration where partial application is dangerous), OR (b) deploys with >1 uvicorn worker. The current VPS runs a single worker, so the multi-worker race is latent.
  - **Trigger check**: any future story that adds a migration performing data transformation (not just schema DDL) — grep the migration for `UPDATE` / `INSERT INTO` against existing tables. Also: the day `deploy/pipecat.service` or `gunicorn/uvicorn` invocation grows a `--workers N` flag with N>1.
  - **Owner/Route**: Architecture (Winston) — plan a `server/db/database.py` refactor, verify with the `prod_snapshot` test harness added in Story 5.1 (Change Log entry 4).

- **No `PRAGMA busy_timeout` on `get_connection()`** — `server/db/database.py:28-41` opens aiosqlite connections without a busy-timeout PRAGMA. Under multi-worker uvicorn, two lifespans racing to `BEGIN IMMEDIATE` (now both `run_migrations` AND `seed_scenarios`) can raise `sqlite3.OperationalError: database is locked` immediately instead of blocking. Pre-existing; amplified by this story adding a second write-lock consumer in the lifespan. Fix = `await db.execute("PRAGMA busy_timeout = 5000")` alongside the existing `foreign_keys` pragma.
  - **When to address**: same trigger as above (multi-worker deploy). Also: as soon as ANY user-facing write path (beyond lifespan startup) is introduced that could contend with the seeder, e.g. Story 6.4 `POST /calls/{id}/end` if it updates `user_progress`.
  - **Trigger check**: any PR that (a) sets `--workers > 1` anywhere (scan `deploy/pipecat.service`, `deploy/setup-vps.sh`, README deploy docs), OR (b) adds a new lifespan-phase DB write alongside `seed_scenarios` / `run_migrations`.
  - **Owner/Route**: one-line fix; can be rolled into the first story that trips the trigger. Very cheap — `await db.execute("PRAGMA busy_timeout = 5000")` in `get_connection()`.

### How these items get surfaced
Both items live in `server/db/database.py` — any future story that edits that file should re-read this section first. Consider adding a comment at the top of `database.py` pointing here ("See `deferred-work.md` §Story 5-1 before touching this file") so nobody rewrites the migration runner without picking them up.

## Deferred from: code review of 5-1-CI-deploy (2026-04-24)

The CI deploy pipeline (GitHub Actions → VPS) went through adversarial review against the ten trap axes specified in the review prompt. BLOCKERs (DB write perms, `migrate-to-releases.sh` path bug, migration-guard) and MAJORs (host-key TOFU, sudoers wildcard, trigger path filter, unit auto-sync, env ownership, `/health` git_sha hardening) were fixed inline. The items below are real, but not blocking the first `gh workflow run`. Each entry records when it becomes worth doing.

- **`migrate-to-releases.sh` copies `.venv` with possibly-broken entry-point shebangs** — `cp -a /opt/.../repo/server` preserves the existing `.venv`. `.venv/bin/python` is a symlink → `/usr/bin/python3.12` ✓, so the ExecStart invocation works. But `.venv/bin/ruff`, `.venv/bin/alembic`, etc. have absolute shebangs pointing at the *old* `.venv` path. The bridge release's `.venv` is therefore a "ghost" — any code path that invokes entry-points (not just `python main.py`) would silently run the old binaries. The first real CI deploy rebuilds `.venv` from scratch via `uv sync`, so this only affects the bridge window.
  - **Fix shape**: add `sudo -u deploy ~deploy/.local/bin/uv sync --frozen --no-dev` inside `$RELEASE_DIR/server` in `migrate-to-releases.sh`, after the `chown -R` and before the symlink swap.
  - **When to address**: only if the bridge window ever runs anything beyond `python main.py`. Today it doesn't. Re-evaluate the day something in main.py imports a package that shells out to a venv-bin script.
  - **Trigger check**: if a PR introduces `subprocess.run([".venv/bin/..."])` or similar in main.py or its import chain.

- **`uv` is installed via `curl ... astral.sh/uv/install.sh | sh`, no version pinning** — `deploy/setup-vps.sh` step 6. If astral ever changes the install path (e.g. from `~/.local/bin/uv` to `~/.local/share/uv/bin/uv`), the workflow's `$HOME/.local/bin/uv` reference in the "Install Python deps" step breaks silently.
  - **Fix shape**: `curl -LsSf https://astral.sh/uv/<VERSION>/install.sh | sh` with a pinned `<VERSION>`, kept in sync with the `uv` version used in the test job (`astral-sh/setup-uv@v3` auto-picks latest).
  - **When to address**: first time a CI deploy fails with "uv: command not found" on the VPS. Also worth doing preemptively on the next major uv release if astral's changelog mentions path changes.
  - **Trigger check**: grep `astral-sh/setup-uv` in `.github/workflows/` and correlate its version with `setup-vps.sh` install script.

- **`xargs -I{} rm -rf {}` in release pruning is not safe against filenames with spaces/newlines** — `.github/workflows/deploy-server.yml` "Prune old releases" step. Release dirs are git-SHA-keyed (7 hex chars), safe today. Only a risk if someone manually creates a release dir with an unusual name.
  - **Fix shape**: replace with `find $VPS_RELEASES -mindepth 1 -maxdepth 1 -type d | sort -r | tail -n +4 | xargs -r -d '\n' rm -rf --`, or a while-read loop.
  - **When to address**: if anyone ever creates a release dir by hand (e.g. during ops recovery) — prune becomes unpredictable. Cheap one-liner to swap in pre-emptively.

- **Pruning may delete the only rollback target if a healthcheck falsely passes** — workflow's "Prune old releases" runs on `if: success()`. If a deploy swapped the symlink, healthcheck passed on the NEW release, but the release is actually buggy in a way that only manifests later (logs, batch jobs, WebRTC flow), the prune has kept only the last 3 releases including the bad one. Rollback to N-4 is impossible via symlink swap.
  - **Fix shape**: keep last 5 (or configurable via env var), or gate prune behind an "acknowledge deploy success" delay (e.g., only prune on the NEXT successful deploy, which implies the current one stayed healthy).
  - **When to address**: first post-deploy incident where rollback was needed but the target was already pruned. Or when adding real user load (Epic 7+).

- **Backup disk growth** — workflow creates `db.pre-<sha>.sqlite` each deploy, retains 14 days. At today's ~50KB DB × 30 deploys/day × 14 days = 21MB ✓. When DB reaches 100MB (realistic post-MVP), same cadence = 42GB, which approaches Hetzner small-VPS disk budget.
  - **Fix shape**: replace `-mtime +14` with `ls -1t | tail -n +N` (keep last N regardless of age), OR add a size-cap (keep backups under X GB total).
  - **When to address**: when `du -sh /opt/survive-the-talk/backups` crosses 1GB, OR before a growth story (e.g., call transcripts in DB).
  - **Trigger check**: any migration that adds a new large table (transcripts, audio metadata, call logs).

- **pipecat.service has no `StartLimitBurst` / `StartLimitIntervalSec`** — `Restart=on-failure RestartSec=5s` without burst limit means a boot-broken service crashes-loops forever. The workflow's 5-attempt healthcheck window (15s) can coincidentally catch a "starting" window before the next crash and report green.
  - **Fix shape**: add `StartLimitBurst=5` and `StartLimitIntervalSec=60` under `[Service]`, plus `StartLimitAction=none`. Combined with the healthcheck step, a repeatedly-failing service cleanly signals "down".
  - **When to address**: first incident where a buggy release crash-looped and healthcheck passed ambiguously. Also: cheap, can be in the same PR as the `/health` `git_sha` hardening.
  - **Trigger check**: any PR that edits `deploy/pipecat.service` should pick this up opportunistically.

- **No SSH connection multiplexing in the workflow** — the deploy job opens 6+ separate SSH sessions (verify guard, backup, rsync, deps-install, unit-sync, swap, restart, journalctl-on-fail). Each pays ~2s handshake. OpenSSH `ControlMaster=auto` + `ControlPersist=10m` would cut ~10s off each deploy.
  - **Fix shape**: add an `~/.ssh/config` step that sets `ControlMaster=auto ControlPath=/tmp/cm-%r@%h:%p ControlPersist=10m` for the VPS host, early in the job.
  - **When to address**: when deploy latency becomes a developer-experience pain (probably once per-push cadence > a few per hour, or when Epic 6+ has many rapid iteration cycles).

- **`deploy/backup.sh` is an unused placeholder** — predates the CI workflow's inline `sqlite3 .backup`. Not called by anything, not on cron.
  - **Fix shape**: either delete the file, or wire it up to a systemd timer for a nightly non-deploy backup (orthogonal to the pre-deploy backup done by the workflow).
  - **When to address**: during a cleanup pass, OR when a "daily cold backup independent of deploy cadence" becomes a real need (e.g., for GDPR 30-day retention).

- **`deploy/Caddyfile` / `deploy/caddy.service` are not part of the CI pipeline** — the narrower path filter in the workflow trigger (§MAJOR #7 fix) excludes them correctly, but that also means Caddy changes require manual SSH + `systemctl reload caddy`. Not currently documented.
  - **Fix shape**: either (a) add a one-sentence note in `deploy/README.md` "How Caddy changes are applied", OR (b) extend the pipeline to scp+reload Caddy similarly to pipecat.service.
  - **When to address**: first time someone edits `Caddyfile` and forgets to reload Caddy on the VPS.

- **Deploy summary step has no context when healthcheck fails** — `Deploy summary` runs `if: always()`, prints release id and commit. But when the healthcheck fails, the user sees the journalctl dump inline AND the summary separately; ordering in the GH UI can be confusing.
  - **Fix shape**: fold the journalctl dump into a `if: failure()` "Deploy diagnostics" step AFTER the healthcheck, and always print `systemctl status pipecat.service | head -10` in the summary for success-path visibility.
  - **When to address**: first time a deploy fails and the GH UI is hard to read. Cheap UX polish.

### How these items get surfaced
Most of these live in `.github/workflows/deploy-server.yml`, `deploy/setup-vps.sh`, or `deploy/pipecat.service` — any future story that edits deploy infrastructure should re-read this section first. If the "Known gaps" section in `deploy/README.md` grows, sync it here (or inversely — the README "Known gaps" is already a bridge to this file).

## Deferred from: code review of story 5-2-build-scenario-list-screen-with-scenariocard-component (2026-04-27)

- **Test fixtures duplicated across scenario test files** — `_build({...}) Scenario` factory and `registerFallbackValue(const LoadScenariosEvent())` are copy-pasted across `client/test/features/scenarios/bloc/scenarios_bloc_test.dart`, `client/test/features/scenarios/views/scenario_list_screen_test.dart`, `client/test/features/scenarios/views/widgets/scenario_card_test.dart`, and `client/test/app_test.dart`. Cheap fix when a 4th caller appears: extract `client/test/features/scenarios/_helpers.dart` exporting `buildScenario({...})` + `setupScenariosFallback()`.
  - **When to address**: when adding the next test file that needs the same fixture, OR during an Epic 5/6 test pass.
  - **Trigger check**: any new file under `client/test/features/scenarios/` or `client/test/features/debrief/` that re-declares `_build`/`buildScenario`.

- **`scenarios_bloc_test.dart` spam-tap test uses microtask ordering + 200ms hard-coded `wait`** — `client/test/features/scenarios/bloc/scenarios_bloc_test.dart:131-141`. The test relies on `await Future<void>.delayed(Duration.zero)` to "yield" between the two `bloc.add` calls, plus a 200ms `wait` for assertions to snapshot the post-delay state. Microtask ordering and timer precision aren't guaranteed across Dart SDK / `bloc_test` versions — flake risk on slow CI runners.
  - **Fix shape**: replace the delayed-repo-answer pattern with an explicit `Completer<List<Scenario>>` the test resolves after dispatching the second event; assert the second `bloc.add` short-circuits before completing the first.
  - **When to address**: first time the test flakes in CI. Or during an Epic 5 test-quality pass.
  - **Trigger check**: any change to `IncomingCallBloc._onAccept` spam-tap pattern (which this test mirrors) — bring both into the new pattern together.

- **No localization (i18n) for hardcoded English strings in scenarios feature** — `client/lib/features/scenarios/views/scenario_list_screen.dart` ("Tap to retry"), `client/lib/features/scenarios/views/widgets/scenario_card.dart` ("View debrief", "Tap phone to call", "Best:", "attempts", "Not attempted", "in progress", "completed"), `client/lib/features/debrief/views/debrief_placeholder_screen.dart` ("Debrief placeholder — scenario X (Story 7.x)", "Back to scenarios"). Project-wide debt; this story does not introduce the issue but does extend the surface.
  - **Fix shape**: introduce `flutter_localizations` + `intl` + `lib/l10n/app_en.arb` (initially English-only), refactor strings to `AppLocalizations.of(context).xxx`. Same approach for auth/onboarding/call screens already shipped.
  - **When to address**: before Epic 10 store submission (i18n is a prerequisite for non-EN markets), OR if a French-speaking beta tester explicitly requests it.
  - **Trigger check**: any PR that adds a new user-visible string anywhere in `client/lib/features/**/views/`.

- **`ScenariosLoaded` with an empty list renders a blank `ListView` with no message** — `client/lib/features/scenarios/views/scenario_list_screen.dart:54-73`. Server currently seeds 5 scenarios, so the empty case is unreachable in MVP, but a future tier-filtered query or a maintenance window could legitimately return `[]` and the screen would silently render blank with no copy.
  - **Fix shape**: add `if (scenarios.isEmpty) return _EmptyView();` branch with a centered Text ("No scenarios available yet — pull to refresh") + retry tap area mirroring `_ErrorView`.
  - **When to address**: when any feature introduces a code path where `GET /scenarios` can legitimately return `[]` (tier filter, geo-gate, A/B test, maintenance mode). Or as part of the Story 5.4 content-warning work if it leads to a "no scenarios match your filter" path.
  - **Trigger check**: any change to `server/api/routes_scenarios.py` that adds query parameters or conditional WHERE clauses.

- **Back-press / back-swipe on `/call` still backgrounds the app** — `client/lib/features/call/views/call_placeholder_screen.dart` and `client/lib/app/router.dart`. Walid raised this during Story 5.2 review (2026-04-27): swiping back from the call screen on Android does NOT bounce off `PopScope(canPop: false)` — the system goes straight to `moveTaskToBack` and the app drops to background. Verified on a Pixel 9 Pro XL (Android 14) via on-device adb logcat tracing.
  - **What was tried during the review session and why each failed**:
    1. **`PopScope(canPop: false)` on the Scaffold root** — kept (it's harmless), but on its own the Flutter back-callback flapped between Flutter's and Android's default callbacks during the predictive back gesture. The logs showed `setTopOnBackInvokedCallback` toggling every ~500ms; the Android default callback was the one in charge when the gesture committed → `moveTaskToBack`.
    2. **Manifest `android:enableOnBackInvokedCallback="true"`** — opted into Android 13+ predictive back. Did not change the flapping behaviour.
    3. **Native `OnBackInvokedDispatcher.registerOnBackInvokedCallback(PRIORITY_OVERLAY, ...)` from `MainActivity.kt`** — Walid's logcat showed `startBackNavigation` still using the priority `-1` Android default callback at swipe time; my registered overlay callback was apparently never invoked. Either the registration silently failed, or Flutter's `FlutterActivity` overrides the dispatcher in a way that bypasses my callback.
    4. **AndroidX `OnBackPressedDispatcher.addCallback(this, OnBackPressedCallback(true) { … })`** — required switching `MainActivity` from `FlutterActivity` to `FlutterFragmentActivity` to access `onBackPressedDispatcher`. The build compiled but the user reported the same backgrounding behaviour after rebuild and on-device test.
  - **Probable root cause**: a known interaction between Flutter's embedding, go_router's `CustomTransitionPage`, the `_GoRouterRefreshStream(authBloc.stream)` listenable, and Android's predictive back system. The `PopScope` (or any back interceptor we register) is being torn down or de-prioritised at the moment the gesture commits. None of the four standard mechanisms held in our setup. Other apps (WhatsApp/FaceTime/native dialer) solve this — but with full native call APIs (CallKit on iOS, ConnectionService on Android) that own the audio session lifecycle and back behaviour together.
  - **Decision (Walid 2026-04-27)**: revert all native + manifest changes from the review session, keep only `PopScope(canPop: false)` (best-effort, harmless), defer the real fix to Story 6.1.
  - **Files reverted in the review session**: `AndroidManifest.xml` (removed the `enableOnBackInvokedCallback` flag), `MainActivity.kt` (back to the empty default), deleted `client/lib/core/system/back_press_blocker.dart`, removed the `BackPressBlocker.setBlocked(...)` calls from `CallPlaceholderScreen`'s `initState`/`dispose`. The `PopScope(canPop: false)` wrapper stays in `CallPlaceholderScreen.build`.
  - **Why this is acceptable for shipping Story 5.2**: the `/call` route is still a placeholder (the real WebRTC + Rive call screen is Story 6.1+). When the user accidentally backgrounds the app today, `_CallPlaceholderScreenState.dispose()` cleanly calls `room.disconnect()` — no resource leak. Re-opening the app cold-starts onto `/scenarios` (no broken state). The UX is sub-optimal but not a regression — the same back-swipe behaviour existed on `/call` before Story 5.2 (it just wasn't visible because the previous root route was a static placeholder, not a real screen reachable from a card tap).
  - **Fix shape for Story 6.1**: implementing CallKit (iOS) + ConnectionService (Android) is the right place for this. Those native call APIs:
    - Keep the audio session alive when the app backgrounds (currently LiveKit dies silently on background).
    - Surface a system "ongoing call" notification + lock-screen control.
    - Own the back-press behaviour at the OS level — back-swipe is naturally blocked while the call is ongoing because the OS treats it as a system-managed phone call.
    - Plus: a `flutter_callkit_incoming` (or similar) package wraps both APIs in a single Dart surface; that's likely the path of least resistance.
  - **When to address**: Story 6.1 (build-call-initiation-from-scenario-list-with-connection-animation) MUST decide on the call-session lifecycle approach (raw LiveKit vs. CallKit/ConnectionService wrapper) before wiring the real call screen. The back-press blocking falls out of that decision.
  - **Trigger check**: any change to `client/lib/features/call/views/` should re-read this entry first. If a PR introduces a real call screen (Rive + active WebRTC + hang-up logic), the back-press blocking + audio-session-keep-alive must ship together with it.

- **No widget test for `PopScope(canPop: false)` on `CallPlaceholderScreen`** — same file. A widget test was attempted but cannot pass: `_CallPlaceholderScreenState.initState` calls `Room()` from `livekit_client`, which constructs an `Engine` + `TTLMap` with a 15-second periodic timer that `room.disconnect()` does not cancel; the test framework reports "Pending timers" at end-of-test. Refactoring the screen to accept an injected `Room` factory would unblock the test.
  - **Fix shape**: Story 6.1 refactors this screen with the real Rive canvas + a proper Room factory injection point. Then write the test (pump the screen with the fake Room, assert that `tester.binding.handlePopRoute()` does not change the visible screen).
  - **When to address**: Story 6.1, alongside the call-screen refactor.
  - **Trigger check**: any change to `client/lib/features/call/views/call_placeholder_screen.dart` should pick this up.

- **`_Avatar.errorBuilder` returns `SizedBox.shrink()` and relies on the parent `Container` for size + colour** — `client/lib/features/scenarios/views/widgets/scenario_card.dart:98`. Today this works because the parent `Container(width: avatarSmall, height: avatarSmall, color: AppColors.avatarBg)` clips to the gray circle even when the image collapses. But the errorBuilder makes no local size guarantee — any future refactor that moves the size constraint onto the `Image.asset` (e.g. removing the `Container` in favour of `SizedBox.fromSize` + `DecoratedBox`) would silently break the missing-asset visual fallback.
  - **Fix shape**: `errorBuilder: (_, _, _) => const SizedBox(width: AppSpacing.avatarSmall, height: AppSpacing.avatarSmall)` so the contract lives in the errorBuilder itself, not in the surrounding widget tree.
  - **When to address**: any PR that touches `_Avatar` or extracts a shared `CharacterAvatar` widget. Cheap one-liner — can be folded into the next visual-asset PR (e.g. when a 6th scenario is added).
  - **Trigger check**: grep for `_Avatar` or `assets/images/characters/` in any incoming diff.

### How these items get surfaced
Three of the original four items (test fixtures, spam-tap delay, i18n) are test/code hygiene that will resurface during the next story that edits `client/test/features/scenarios/` or adds new user-visible strings. The placeholder back-button entry is self-evicting — Story 7.x replaces the screen wholesale. The two new entries (empty-list state + avatar errorBuilder) trigger only on specific structural changes — see each item's "Trigger check" line.
