# Story 8.3: Build Subscription Management and Full Tier Enforcement

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to view my subscription status and have the system correctly enforce my access level,
so that I get exactly what I'm paying for and can manage my subscription easily.

> **One-paragraph orientation (read this first).** Stories 8.1 and 8.2 already shipped *purchasing* (native IAP + server-side receipt validation + tier flip to `paid`) and the *paywall UI* (4-state sheet + 3 entry points + Restore). **8.3 is the last functional Epic-8 story: it makes tier enforcement complete and server-authoritative, and adds the read/manage side of subscriptions.** Concretely, 8.3 closes the gaps the first two stories knowingly deferred: (1) the free-call counter currently counts *lifetime* sessions so a churned paid→free user is stuck at 0 calls forever; (2) `expires_at` is stored but never enforced, so subscriptions never actually lapse; (3) there is no `GET /user/profile`, no app-lifetime purchase listener, and no in-app way to see status / open the native manage screen. **Most of 8.3 is server-side and fully testable now via pytest; the live-purchase paths are on-device-blocked exactly like 8.1/8.2 (see Test Strategy).**

## Acceptance Criteria

_Verbatim from epics.md (Epic 8, Story 8.3). These are the canonical pass/fail gates._

1. **AC1 (FR30 — native subscription management).** **Given** FR30 requires subscription management, **when** a paid user wants to manage their subscription, **then** the app provides access to the native subscription management screen (StoreKit 2 / Google Play — platform-managed, not custom UI).

2. **AC2 (FR31 — scenario tier gating).** **Given** FR31 requires tier enforcement based on free/paid status, **when** a free user attempts to call a paid scenario, **then** the paywall is shown instead.

3. **AC3 (FR31 — daily call limit / call-icon disablement).** **Given** FR31 requires daily call limit enforcement, **when** a user has exhausted their daily calls, **then** call icons on all scenarios are non-functional and the BottomOverlayCard reflects the appropriate state (UX-DR5).

4. **AC4 (BottomOverlayCard 4-state matrix — UX-DR5).** **Given** the BottomOverlayCard has 4 states, **when** the user's status changes, **then** the overlay card updates correctly: free/calls remaining → "Unlock all scenarios", free/0 calls → "Subscribe to keep calling", paid/calls available → hidden, paid/0 calls today → "No more calls today".

5. **AC5 (`GET /user/profile` + server-side `POST /calls/initiate` enforcement).** **Given** `GET /user/profile` returns subscription status, **when** the app requests the user profile, **then** it includes tier (free/paid), calls remaining today, and subscription expiry date. **And** the server enforces limits on `POST /calls/initiate` — returning HTTP 403 with error code `CALL_LIMIT_REACHED` or `TIER_RESTRICTED` if limits are exceeded.

6. **AC6 (subscription expiry / cancellation → revert to free).** **Given** a user's subscription expires or is cancelled, **when** the tier reverts to free, **then** the user retains access to all past debriefs but loses access to paid scenarios and the daily call limit changes to the free tier.

---

## ⚠️ PRE-DEV DECISIONS — recommended defaults baked into this spec, PENDING Walid confirm before `/bmad-dev-story`

This story carries genuine product/scoping decisions (same pattern as 8.1/8.2). **The spec below is written assuming the recommended default for each.** Walid may override any before dev starts; if he confirms the defaults ("prends tes recos"), dev proceeds as written.

- **D1 — Where does the "manage subscription / status" surface live?** The UX spec explicitly forbids a settings/account screen ("Three-screen minimalism… no settings screen", ux-design-specification.md §47/§206). But AC1+AC5 need *some* in-app surface for a paid user to see status and reach the native manage screen.
  - **REC (default):** a **paid-only, low-key hub affordance** (a single Handler's-Brief-styled text line on the scenario hub, near `_DifficultyHubLine`) that opens a **minimal bottom sheet** (same modal idiom as the content-warning / difficulty sheets) showing: tier, renews/expires date, **Manage subscription** (native deep-link), **Restore purchases**. **Free users see nothing new** → invisible tiers (UX-DR16) preserved.
  - **ALT:** hang Manage/Restore off the paywall's paid-state only (no hub affordance) — less discoverable; or a dedicated full route (heavier, fights three-screen minimalism).

- **D2 — Free-call count policy on a paid→free reversion (the core AC6 rule).** Free tier = **3 calls lifetime** (not daily). Today the counter is unconditional-lifetime, so a churned user is capped at 0 forever (the deferred bug).
  - **REC (default):** count free calls **since the user's most recent `tier_changed_at`** (a reverted user gets a **fresh 3 free calls**). A never-paid user has `tier_changed_at = NULL` → counts true lifetime (unchanged). This is exactly the deferred-work prescription ("count calls since the current tier started") and what AC6's "daily limit changes to the free tier" implies.
  - **Caveat surfaced (per the trade-off-as-decision rule):** this lets a user farm free calls by subscribe→cancel→repeat. At MVP scale (60–500 subscribers, $1.99/wk) the abuse is negligible; flag it, don't engineer against it now.
  - **ALT:** strict lifetime (never refresh) — harsh, contradicts AC6, keeps the bug.

- **D3 — Cancellation/expiry detection mechanism.** AC6 = "expires or is cancelled → revert."
  - **REC (default):** **polling-only**, no store webhooks. Extend the existing 5-min revalidation loop to **downgrade any `paid` user whose latest `valid` purchase has `expires_at ≤ now`** (covers both natural expiry and cancellation — a cancelled sub simply doesn't renew and lapses at period end, which is correct subscription behavior). Pair with the new client app-lifetime purchase listener (D-bake below) that re-verifies renewals on app open → refreshes `expires_at`. Latency ≤ 5 min server-side, instant on app open.
  - **ALT:** add App Store Server Notifications V2 + Google RTDN webhook endpoints (push, lower latency, much more infra + store config). Out of MVP scope.

- **D4 — Apple App Store Server API (online revocation/renewal) scope.** The `apple_issuer_id` / `apple_key_id` / `apple_private_key_p8` config fields were reserved UNSET by 8.1 specifically for this.
  - **REC (default): DEFER the Apple App Store Server API online path.** AC6 is satisfiable without it: the offline JWS already carries `expiresDate` (Apple validator already rejects expired), the expiry-downgrade sweep (D3) handles lapse, and the client app-lifetime listener re-verifies fresh StoreKit 2 renewal transactions on next app open. Because **calls are online-only and require opening the app**, a server-side expiry-downgrade self-heals the instant the user re-opens (listener + `/scenarios` reload re-grant) — so a renewed-but-app-closed user is never wrongly blocked *in practice*. Wiring the ASSA path now would be **mock-only** (App Store Connect API key not created; iOS device-blocked until Story 10-4), adding large surface for little MVP value. Keep the three fields UNSET; leave the in-code TODO marker.
  - **ALT:** implement the ASSA online client now (structurally, mock-tested like 8.1's validators).

- **D5 — `GET /user/profile` vs extending `/scenarios` meta.** AC5 names `GET /user/profile` explicitly.
  - **REC (default): build `GET /user/profile`** returning `{tier, calls_remaining, calls_per_period, period, subscription_expires_at}` (AC5 verbatim). Keep `/scenarios` meta unchanged as the **hub's** lightweight tier/quota source (drives the BOC). The new paid-status surface (D1) reads `/user/profile` (the only place `expires_at` is exposed steady-state).
  - **ALT:** skip a new endpoint, add `expires_at` to `/scenarios` meta — less work but deviates from AC5's literal wording and bloats the hub payload.

- **No new DB migration is expected.** `users.tier_changed_at` (migration 014) and `purchases.expires_at` already exist; the count rework *reads* `tier_changed_at`, the expiry sweep *reads* `purchases` and *writes* `users.tier`, and `/user/profile` *reads* a new query over existing columns. The expiry-downgrade intentionally **does not mutate the purchase row** (an expired row was validly issued; it stops granting purely because `expires_at ≤ now`), so the `validation_status` CHECK enum is untouched. **If dev discovers a genuine schema need, the next migration is `015_*.sql` and it MUST keep `tests/test_migrations.py` green against `prod_snapshot.sqlite` (refresh + commit the snapshot).**

---

## Tasks / Subtasks

### Task 1 — Server: tier-transition-aware free-call counting (AC6, D2) ⟵ the headline server fix

- [ ] In `server/api/usage.py`, change `compute_call_usage(db, user_id, tier, *, now=None)` to also take the user's `tier_changed_at` (add param `tier_changed_at: str | None = None`).
  - [ ] **Free path:** if `tier_changed_at` is non-null → `used = await count_user_call_sessions_since(db, user_id, tier_changed_at)`; else (never-paid) → `used = await count_user_call_sessions_total(db, user_id)` (unchanged). Keep `period = "lifetime"`, `calls_per_period = CALLS_PER_PERIOD (3)`, `calls_remaining = max(0, 3 - used)`.
  - [ ] **Paid path:** unchanged (per-UTC-day via `count_user_call_sessions_since(_utc_day_start_iso(now))`).
- [ ] Update both callers to pass `tier_changed_at`:
  - `server/api/routes_calls.py` initiate gate (it already does `user = await get_user_by_id(...)`; pass `user["tier_changed_at"]`).
  - `server/api/routes_scenarios.py` (`GET /scenarios` meta computation) — same.
- [ ] **Do NOT** add a new query — `count_user_call_sessions_since` already exists and is reused. **Do NOT** change paid semantics.
- [ ] Tests in `server/tests/test_call_usage.py`: never-paid free user counts lifetime (regression); paid→free reverted user (set `tier_changed_at` to "now", insert older sessions) → fresh 3 remaining; sessions after `tier_changed_at` decrement correctly; `failed` sessions still excluded.

### Task 2 — Server: `GET /user/profile` endpoint (AC5, D5)

- [ ] New route module `server/api/routes_user.py`: `APIRouter(prefix="/user", tags=["user"], dependencies=[AUTH_DEPENDENCY])`, `GET /user/profile`. Register it in `server/api/app.py` alongside the other routers.
- [ ] Handler: resolve `user_id` from `request.state` → `get_user_by_id` → `compute_call_usage(db, user_id, user["tier"], tier_changed_at=user["tier_changed_at"])` → `expiry = await get_active_entitlement_expiry(db, user_id)`. Return via `ok(...)` `{data, meta}` envelope.
- [ ] New query `get_active_entitlement_expiry(db, user_id) -> str | None` in `server/db/queries.py`: latest `expires_at` among `purchases WHERE user_id=? AND validation_status='valid' AND expires_at IS NOT NULL` ordered by `expires_at DESC LIMIT 1` (parse-safe; if all expired this still returns the most recent — the client renders it as "Expired"/"Renews" based on whether it's future). No raw SQL in the route (Architecture Boundary 4).
- [ ] Response model `UserProfileOut` in `server/models/schemas.py`: `tier: Literal["free","paid"]`, `calls_remaining: int`, `calls_per_period: int`, `period: str`, `subscription_expires_at: str | None`. snake_case JSON; null field omitted only if absence is meaningful (here `null` is meaningful = "no subscription on record" → keep it explicit).
- [ ] Tests in a new `server/tests/test_user_profile.py`: 401 without JWT; free user → `tier:"free"`, correct `calls_remaining`, `subscription_expires_at: null`; paid user with a valid future-dated purchase → `tier:"paid"` + expiry echoed; envelope shape `{data, meta}`.

### Task 3 — Server: full tier/limit enforcement on `POST /calls/initiate` (AC2, AC5)

- [ ] In `server/api/routes_calls.py` initiate handler, BEFORE the existing `CALL_LIMIT_REACHED` check, add a **scenario-tier gate**: if `user["tier"] == "free"` AND the target scenario is **not free** (`scenario["is_free"]` falsy) → raise `HTTPException(403, {"code": "TIER_RESTRICTED", "message": "..."})`. This makes the paid-scenario gate server-authoritative (today it is client-only — a free user could bypass the paywall by calling the API directly).
  - [ ] Re-assert inside the `BEGIN IMMEDIATE` block too (mirror the existing TOCTOU re-check for the limit), so the gate holds under concurrency.
- [ ] Keep the existing `CALL_LIMIT_REACHED` 403 (now powered by the Task-1 tier-transition-aware count). Both errors use the canonical `{"error":{"code","message"}}` envelope (verify the route's error shaping matches the project standard).
- [ ] Tests in `server/tests/test_calls.py`: free user + paid scenario → 403 `TIER_RESTRICTED` (no `call_session` row created, no LiveKit token); free user + free scenario at cap → 403 `CALL_LIMIT_REACHED`; paid user + paid scenario under cap → 200.

### Task 4 — Server: expiry enforcement + expiry-driven downgrade sweep (AC6, D3, F11/F12)

- [ ] **Fix the Google validator (deferred F11/F12)** in `server/billing/google_validator.py`:
  - [ ] F12: select `expiryTime` **chronologically** — parse each line-item `expiryTime` (RFC3339, may carry fractional seconds + `Z`) to an aware `datetime` and take the max by datetime, not lexicographic `max()` on strings.
  - [ ] F11: after the `subscriptionState ∈ {ACTIVE, IN_GRACE_PERIOD}` check, **also reject when the chosen expiry parses to `≤ now`** → `ValidationResult(valid=False, status="invalid", reason="expired")`, mirroring the Apple guard (`apple_validator.py:146-154`). Add a parse helper (tolerate `Z` and fractional seconds).
- [ ] **Add the expiry-downgrade sweep** in `server/billing/revalidation.py`: a new `async def downgrade_expired_entitlements(db, *, now=None) -> int`. Find every user where `tier='paid'` AND there is **no** `valid` purchase with `expires_at > now` (new query `get_users_with_expired_entitlement(db, now)` in queries.py). For each, atomically (`BEGIN IMMEDIATE`) `update_user_tier(db, user_id, "free", tier_changed_at=now_iso())`. **Do NOT mutate the purchase row** (it was validly issued; it stops granting purely on `expires_at`). Idempotent (re-running finds nothing once downgraded). Fail-soft per-user (one bad row never aborts the sweep).
- [ ] Call `downgrade_expired_entitlements` from the existing 5-min loop in `server/api/app.py` (`_subscription_revalidation_loop`), right after `revalidate_pending_purchases`, on the same shared `stop_event`. (The `pending`-row re-check stays as-is.)
- [ ] **AC6 "retains access to all past debriefs"** is satisfied for free by construction — debriefs are never tier-gated (verify: no tier check on `GET /debriefs` / debrief read paths). Add a one-line assertion test that a `free` user can still read a previously-created debrief.
- [ ] Tests: `test_billing.py` — Google `ACTIVE` state but `expiryTime` in the past → `invalid` (the missing F11 case); chronological vs lexicographic expiry pick (F12, e.g. fractional-second strings). `test_subscription.py` — `downgrade_expired_entitlements` flips an expired-paid user to free + stamps `tier_changed_at`; leaves a future-dated paid user alone; leaves a free user alone; user with one expired + one future-valid purchase stays paid.

### Task 5 — Client: app-lifetime `purchaseStream` listener (AC6, deferred F4-func)

- [ ] New app-scoped service `client/lib/features/subscription/services/purchase_sync_service.dart` (mirror the `EndCallRetryService` app-singleton precedent). Holds `InAppPurchaseService` + `SubscriptionRepository`. On construction it `.listen()`s to `purchaseStream` for the **whole app lifetime**; for each re-delivered `purchased`/`restored` transaction it `verifyPurchase(...)` then `complete(...)` (reuse the 8.1 repo/service — do NOT duplicate verify logic), independent of whether the paywall is open. Expose a lightweight `Stream<void> onEntitlementChanged` (or a `ValueListenable`) that fires after a successful verify.
- [ ] Construct it in `client/lib/main.dart` `bootstrap()` BEFORE `runApp` (next to `EndCallRetryService`), provide it into the tree via `RepositoryProvider.value` in `app.dart` (same pattern). On `onEntitlementChanged`, the hub dispatches a silent `RefreshScenariosEvent` so tier re-flows from `/scenarios` meta.
- [ ] **Do NOT** remove or alter the paywall bloc's own stream subscription (it stays sheet-scoped for the interactive purchase). The two listeners coexist; both go through `complete()` which is idempotent — ensure no double-verify crash (the repo/verify endpoint is already idempotent + 409-guarded server-side, so a duplicate verify is safe).
- [ ] Keep restore semantics intact (8.2 F16 made `restored` auto-flip intentional).
- [ ] Tests: `bloc_test`/widget test with a fake `InAppPurchaseService` emitting a `purchased` event on `purchaseStream` while no paywall is mounted → service calls `verifyPurchase` + `complete` + fires `onEntitlementChanged`. Use `FlutterSecureStorage.setMockInitialValues({})` in `setUp`; never `pumpAndSettle` on spinners.

### Task 6 — Client: pending-approval state (deferred F17)

- [ ] Add `SubscriptionPendingApproval` to `subscription_state.dart`. In `subscription_bloc.dart` `_onPurchaseUpdated`, `case PurchaseStatus.pending:` now emits `SubscriptionPendingApproval` (instead of silently staying in `SubscriptionLoading` forever). When the same stream later delivers `purchased`/`error`, the bloc transitions normally (it is still listening).
- [ ] In `paywall_sheet.dart`, render `SubscriptionPendingApproval` as a dismissible state: replace the CTA with the message **"Waiting for approval"** + secondary line **"You can close this."** (declarative, no exclamation/emoji per the banned-copy lint). `PopScope` allows back here (it is NOT an in-flight network call — it can persist minutes→days for iOS Ask-to-Buy / Android deferred cards). "Not now" stays available.
- [ ] Tests: bloc emits `SubscriptionPendingApproval` on `pending`; paywall renders the copy + is dismissible; a subsequent `purchased` on the stream flips to Success.

### Task 7 — Client: native manage deep-link (AC1) + paid-status surface (D1) + CallUsage clamp

- [ ] **Native manage deep-link (AC1).** Add `openManageSubscriptions()` (use the existing `url_launcher: ^6.3.2` dep, `LaunchMode.externalApplication`, the same way `consent_screen.dart` opens the privacy URL):
  - iOS → `https://apps.apple.com/account/subscriptions`
  - Android → `https://play.google.com/store/account/subscriptions?sku=stt_weekly_199&package=<applicationId>` (read the package/product from the existing `kIapWeeklyProductId` const + the platform applicationId).
  - Keep platform branching guarded (the F15 note — assert `defaultTargetPlatform ∈ {iOS, android}`). **Do NOT** add a new IAP plugin or a `MethodChannel` — `url_launcher` to the platform-managed URL satisfies "platform-managed, not custom UI".
- [ ] **Paid-status surface (D1 default).** New client `UserProfile` model + repository method `getProfile()` → `GET /user/profile` (extend `SubscriptionRepository` or add a small `UserRepository`; reuse `ApiClient`). A **paid-only** low-key hub affordance opens a minimal bottom sheet (Handler's-Brief styled: one left rail, two-ink, no cards/dividers, ≤~24 app-owned words, A2/B1, no banned copy) showing: tier label, **Renews `<date>`** if `subscription_expires_at` is in the future (or **Expired `<date>`** if past), **Manage subscription** (→ `openManageSubscriptions`), **Restore purchases** (→ reuse the 8.2 `RestorePressed` flow). **Free users: no affordance** (invisible tiers, UX-DR16).
- [ ] **CallUsage negative clamp (deferred item — triggered because this surface displays `calls_remaining`).** In `client/lib/features/scenarios/models/call_usage.dart` `fromMeta`: `callsRemaining = max(0, json['calls_remaining'] as int)`; assert `calls_per_period > 0` else throw `FormatException`. Mirror the clamp anywhere `/user/profile`'s `calls_remaining` is parsed.
- [ ] Tests: `openManageSubscriptions` launches the correct per-platform URL (mock `url_launcher`); the paid-status sheet renders date + buttons for a paid profile and is absent for a free user; `CallUsage.fromMeta` clamps `-1 → 0` and throws on `calls_per_period <= 0`; theme-token test still green (add no inline hex — if a new token is truly needed, bump `theme_tokens_test.dart` count).

### Task 8 — Client: AC3/AC4 live-state verification (mostly already built — verify + close gaps)

- [ ] **AC4 BOC matrix** is already implemented in `client/lib/features/scenarios/views/.../bottom_overlay_card.dart` (`_variantFor`): free+calls→"Unlock all scenarios", free/0→"Subscribe to keep calling", paid+calls→hidden (`SizedBox.shrink`), paid/0→"No more calls today"/"Come back tomorrow". **Verify it reflects LIVE status after a tier change** (purchase, expiry-downgrade) by confirming the post-event `/scenarios` reload re-renders the right variant. Add/keep widget tests for all 4 variants.
- [ ] **AC3 call-icon disablement at 0 calls.** Confirm that when `usage.callsRemaining == 0` the per-scenario call icons are **non-functional**: tapping must NOT initiate a call. Today the server returns 403 (`CALL_LIMIT_REACHED`/`TIER_RESTRICTED`) and the client routes that to the paywall. Make the client also reflect the disabled affordance proactively (icon visibly inert / tap → BOC paywall path), so "call icons on all scenarios are non-functional" holds without relying on a round-trip. Wire/verify and add a widget test (0 calls → tapping a call icon does not dispatch `InitiateCall`/`_startCall`).
- [ ] **Do NOT** restyle the BOC or add tier badges to cards (invisible tiers, UX-DR16).

### Task 9 — Tests + gates (all green before commit, per CLAUDE.md)

- [ ] Server: `cd server && python -m ruff check . && python -m ruff format --check . && <venv> -m pytest` — all green. (Warm `import aiohttp` once if cold per the sandbox note.)
- [ ] Client: `cd client && flutter analyze` → **"No issues found!"** (zero infos) and `flutter test` → **all pass**.
- [ ] Migration test `tests/test_migrations.py` stays green (no new migration expected; if one is added, `015_*` + `refresh_prod_snapshot.py` + commit the snapshot).
- [ ] Update the story File List + Completion Notes + declare any deviations.

### Task 10 — Deploy + Smoke Test Gate (server) + on-device deferral

- [ ] Deploy to VPS (CI `deploy-server.yml` → `systemctl restart pipecat.service`); confirm `/health` git_sha matches.
- [ ] Fill the **Smoke Test Gate (Server)** boxes below with real command output.
- [ ] **On-device IAP gate is DEFERRED** (real purchase / renewal / restore / manage-deep-link untestable until 8.1-D4 store config lands AND Story 10-4 ships the iOS pipeline) — same posture as 8.1/8.2. Server enforcement (count rework, `/user/profile`, `TIER_RESTRICTED`, expiry sweep) IS testable now via pytest + the server smoke boxes; the Android `url_launcher` manage path and widget-level UI are widget-testable. Note this explicitly in the review summary so the story isn't blocked waiting on an ungated capability.

---

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** Included — this story adds `GET /user/profile`, changes `POST /calls/initiate` enforcement, and extends the 5-min revalidation loop. **DB-migration boxes are N/A** (no new migration expected — 8.3 reads `tier_changed_at`/`expires_at` and writes `users.tier`, all on existing columns).
>
> **Transition rule:** Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->

- [ ] **`GET /user/profile` happy path.** Authenticated curl returns `{data:{tier, calls_remaining, calls_per_period, period, subscription_expires_at}, meta}` + HTTP 200.
  - _Command:_ `curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/user/profile`
  - _Expected:_ 200 + `{"data":{"tier":"...","calls_remaining":N,"subscription_expires_at":null|"...Z"},"meta":{...}}`
  - _Actual:_ <!-- paste output -->

- [ ] **`TIER_RESTRICTED` enforcement.** A `free` user calling a **paid** scenario via `POST /calls/initiate` returns 403 `{"error":{"code":"TIER_RESTRICTED",...}}` (canonical error envelope, not a raw 500). Pair with a `CALL_LIMIT_REACHED` negative case for an at-cap free user.
  - _Command:_ <!-- POST /calls/initiate with a paid scenario_id as a free user; show both TIER_RESTRICTED and CALL_LIMIT_REACHED -->
  - _Expected:_ 403 + `{"error":{"code":"TIER_RESTRICTED"|"CALL_LIMIT_REACHED", ...}}`
  - _Actual:_ <!-- paste output -->

- [ ] **DB side-effect — tier-transition free count.** On the prod DB, confirm a user with `tier='free'` and a non-null `tier_changed_at` has `calls_remaining` computed since `tier_changed_at` (not lifetime). Read back via the venv stdlib (no `sqlite3` CLI on the VPS).
  - _Command:_ <!-- /opt/.../.venv/bin/python -c 'import sqlite3; ... SELECT id,tier,tier_changed_at FROM users WHERE ...' then hit /user/profile for that user -->
  - _Actual:_ <!-- paste rows + the /user/profile calls_remaining for that user -->

- [ ] **DB side-effect — expiry downgrade sweep.** Verify the 5-min loop downgrades a `paid` user whose latest valid `purchases.expires_at ≤ now` to `tier='free'` with a fresh `tier_changed_at`. (Safe to construct a synthetic expired row on a throwaway/test user; restore after — back up first.)
  - _Command:_ <!-- insert/seed an expired valid purchase for a test user, wait one loop tick, read back users.tier + tier_changed_at -->
  - _Actual:_ <!-- paste before/after rows -->

- [ ] **DB backup taken BEFORE any prod DB manipulation.** Even though no migration ships, the expiry-sweep + count verification may touch a real user — snapshot first.
  - _Command:_ `ssh root@167.235.63.129 "cp /opt/survive-the-talk/data/db.sqlite /opt/survive-the-talk/data/db.sqlite.bak-pre-8-3-$(date +%Y%m%d-%H%M%S)"`
  - _Proof:_ <!-- paste the resulting filename -->

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 80 --since "5 min ago"` shows no ERROR/Traceback for the requests above or the revalidation loop tick.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

---

## Dev Notes

### What already exists — REUSE, do not re-invent

**Server (Stories 8.1):**
- `server/billing/` — `validate_apple`, `validate_google`, `ValidationResult{valid,status,transaction_id,expires_at,reason}`, `BillingConfigError`, `apple_roots.py` (pinned Apple Root CA-G3), `revalidation.py`. [Source: 8-1 story File List]
- `POST /subscription/verify` (`server/api/routes_subscription.py`) — synchronous validate-then-flip; 200/402 `PURCHASE_INVALID`/409 `PURCHASE_CONFLICT`/503 `SUBSCRIPTION_UNAVAILABLE`. Idempotent, two-TX, cross-user-replay guarded.
- 5-min `_subscription_revalidation_loop` in `server/api/app.py` (re-checks `pending` rows only today). [Source: server `api/app.py:110`]
- Queries: `get_user_by_id`, `update_user_tier(...,*,tier_changed_at,commit=)`, `insert_purchase`, `update_purchase_validation`, `count_user_valid_purchases`, `get_pending_purchases`, `get_latest_purchase_by_token`, `count_user_call_sessions_total`, `count_user_call_sessions_since`. [Source: `server/db/queries.py`]
- Migration 014 added `users.tier_changed_at` (nullable, stamped on every flip) + the `purchases` table (`validation_status CHECK(pending|valid|invalid)`, `expires_at`, `verification_token UNIQUE`). **Highest migration = 014; next = 015 IF needed.** [Source: `server/db/migrations/014_subscriptions.sql`]
- Config (`server/config.py`): `apple_bundle_id`, `apple_app_apple_id`, `apple_accept_sandbox`, `google_play_package_name`, `google_service_account_json` (base64), `iap_product_id="stt_weekly_199"`. **`apple_issuer_id`/`apple_key_id`/`apple_private_key_p8` exist but are UNSET, reserved for 8.3's Apple online path (D4 = defer → leave UNSET, keep the TODO).**

**Client (Stories 8.1/8.2):**
- `client/lib/features/subscription/` — `InAppPurchaseService` (`purchaseStream`, `loadProduct`, `buy`, `complete`, `restore`, `kIapWeeklyProductId`), `SubscriptionRepository.verifyPurchase`, `SubscriptionBloc` (events: `SubscribePressed`/`RestorePressed`/`RestoreLapsed`/internal `PurchaseUpdated`/`PurchaseTimedOut`; states: `SubscriptionInitial`/`Loading`/`Purchased`/`Failed(code)`/`Cancelled`/`RestoreEmpty`), `SubscriptionStatus{tier,productId,expiresAt,status,isPaid}`.
- `PaywallSheet.show(context) -> Future<bool>` (native `showModalBottomSheet`, radius 16, surface `#F0F0F0`, 4 states, `debugBlocBuilder` test seam) + 3 entry points already wired in `scenario_list_screen.dart` (paid-scenario gate `_maybeGatePaidScenario`, BOC `onPaywallTap`, FR29 debrief thread) + the `CALL_LIMIT_REACHED` ApiException → paywall route. **AC2 is already satisfied client-side; 8.3 adds the server-side guarantee (Task 3).**
- `BottomOverlayCard` 4-state `_variantFor` (AC4 already implemented). `CallUsage.fromMeta` reads `/scenarios` meta `{tier,calls_remaining,calls_per_period,period}` (no clamp yet — Task 7). `ScenariosBloc` `LoadScenariosEvent` (full, post-purchase) + `RefreshScenariosEvent` (silent, post-call-return).
- `EndCallRetryService` app-singleton in `main.dart` `bootstrap()` (+ `RepositoryProvider.value` in `app.dart`) — **the exact precedent to copy for the app-lifetime purchase listener (Task 5)**.
- `url_launcher: ^6.3.2` is already a dep (used in `consent_screen.dart`) — reuse for AC1.

### The exact tier/quota mechanism AS IMPLEMENTED (not as architecture.md describes it)

architecture.md predates Stories 8.1/8.2 and is **stale** on billing/tier specifics — trust the code, not the doc. As built:
- `users.tier TEXT CHECK(tier IN ('free','paid'))` (canonical `'paid'`, ADR-002 — never `'full'`) + `users.tier_changed_at TEXT` (nullable, ISO-8601 UTC).
- **Free = 3 calls LIFETIME; Paid = 3 calls per UTC-day.** Computed in `server/api/usage.py:compute_call_usage`; `CALLS_PER_PERIOD = 3`.
- `call_sessions.status CHECK(pending|completed|failed)`. Count queries filter `status IN ('pending','completed')` → `failed` rows are refunded (the quota-reset mechanism; abandoned `pending` rows are janitored to `failed`).
- `calls_remaining = max(0, 3 - used)`, enforced at `POST /calls/initiate` → 403 `CALL_LIMIT_REACHED`; surfaced to the client via `GET /scenarios` `meta` (there is **no** `GET /user/profile` today — Task 2 builds it).
- **`tier_changed_at` and `expires_at` are write-only audit fields today — never read for any entitlement decision.** Task 1 makes the count read `tier_changed_at`; Task 4 makes the sweep read `expires_at`.

### Declared-deviation landmines inherited from 8.1/8.2 (do not trip)

- 8.1 #2 / **F4-func**: the paywall bloc's `purchaseStream` listener is **sheet-scoped** — a re-delivered/Ask-to-Buy purchase isn't verified unless the sheet is open. **Task 5 fixes this with an app-lifetime listener; do not "fix" it by changing the sheet bloc's lifecycle.**
- 8.1 #1: Google validator uses `pyjwt`+`httpx` (not `google-auth`) — stay async, add no deps when touching it (Task 4).
- 8.2 #1 + the on-device defer: native `showModalBottomSheet` swipe/scrim can't be programmatically blocked mid-sheet (the custom-route attempt was reverted on-device 2026-06-18). **Do NOT re-attempt the custom paywall route in 8.3** — it's deferred until the real-purchase path is on-device-testable. `PopScope` blocking back is the shipped behavior.
- 8.2 F16: `restored` auto-flipping tier is now **intentional** (the restore feature) — Task 5's app-lifetime listener must preserve restore semantics.
- `compute_call_usage` raises `ValueError` for tier ∉ {free,paid} (swallowed by a broad 500) — don't introduce a third tier string; canonical set stays `{free, paid}`.

### Architecture & cross-cutting constraints (binding)

- **Tier is server-authoritative.** The client paywall/gate is UX; the real gate is `POST /calls/initiate` (Task 3). Never set tier locally on the client — it learns tier ONLY from `/scenarios` meta and `/user/profile`. [Source: architecture.md §FR-mapping `api/middleware.py` tier enforcement; ADR-002]
- **API envelope (non-negotiable):** success `{data, meta}`, error `{"error":{"code","message"}}`, all JSON `snake_case`, 403 for tier/limit, JWT-required routes via `AUTH_DEPENDENCY`. [Source: architecture.md Implementation Patterns]
- **DB access only via `server/db/queries.py`** — no raw SQL in route handlers (Boundary 4).
- **Billing failures must fail-open to free-tier behavior** — never hard-block app usage on a verify/validation failure (the `unreachable` → optimistic-paid path; a sweep error must not crash). [Source: architecture.md external-services degradation]
- **Design rulebook "The Handler's Brief"** governs any NEW 8.3 surface (the D1 status sheet): one left rail, two-ink discipline (accent green is never text/icon), zero furniture (spacing does grouping), ≤~24 app-owned words, A2/B1, banned-copy lint (no exclamations/praise/emoji/tips/urgency — paste the banned list as a comment block above the const strings). The paywall's own centered/accent styling is a separate binding doc and is NOT the model for the status sheet. [Source: project_design_rulebook_handlers_brief.md; ux-design-specification.md §47/§206/§996-1020/§546-547]
- **Invisible tiers (UX-DR16):** never add tier badges to scenario cards or persistent "you are PAID" chrome. The D1 affordance is low-key and paid-only.

### Test Strategy (server fully testable now; live IAP deferred)

- **Server (pytest, fully runnable now):** mock the validators (patch at `api.routes_subscription.*` / `billing.revalidation.*`); never hit real stores. Follow `test_subscription.py`/`test_billing.py`/`test_call_usage.py`/`test_user_profile.py` patterns. Use a Loguru temp sink (not `caplog`). Warm `import aiohttp` once if the sandbox is cold. The whole tier-enforcement surface (count rework, `/user/profile`, `TIER_RESTRICTED`, Google expiry, expiry sweep) is verifiable here.
- **Client (flutter_test):** `mocktail` + `bloc_test`; `FlutterSecureStorage.setMockInitialValues({})` in every `setUp`; `registerFallbackValue` for sealed events; **never `pumpAndSettle` on a spinner — use `pump(Duration)`**; drive UI via the `debugBlocBuilder` seam + a `MockSubscriptionBloc`; force `setSurfaceSize(Size(320,480))` for overflow checks; theme-token test asserts exact token count (don't add inline hex).
- **On-device (DEFERRED):** real purchase / renewal / restore / native manage-deep-link launch are blocked until 8.1-D4 store config + Story 10-4 iOS pipeline. State this in the review summary; the story reaches review-complete via code review + the server Smoke Test Gate + widget/unit tests, exactly like 8.1/8.2.

### Project Structure Notes

- New server files: `server/api/routes_user.py`, `server/tests/test_user_profile.py`. New queries in `server/db/queries.py` (`get_active_entitlement_expiry`, `get_users_with_expired_entitlement`). Modified: `server/api/usage.py`, `server/api/routes_calls.py`, `server/api/routes_scenarios.py`, `server/api/app.py`, `server/billing/google_validator.py`, `server/billing/revalidation.py`, `server/models/schemas.py`, plus tests.
- New client files: `client/lib/features/subscription/services/purchase_sync_service.dart`, a `UserProfile` model + repository method, the paid-status sheet view. Modified: `client/lib/main.dart`, `client/lib/app/app.dart`, `client/lib/app/router.dart` (only if D1 becomes a route — default is a sheet, no route), `subscription_bloc.dart` / `subscription_state.dart`, `paywall_sheet.dart`, `call_usage.dart`, the scenario hub + BOC test files.
- No new migration expected. If one is unavoidable → `015_*.sql` + `tests/test_migrations.py` green against `prod_snapshot.sqlite` + refresh & commit the snapshot.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-8-Story-8.3] — user story + AC1–AC6 verbatim; FR30/FR31; UX-DR5/UX-DR16.
- [Source: _bmad-output/planning-artifacts/prd.md] — FR20/FR21 (3 scenarios / 3 calls lifetime vs 3/day), FR28–FR31, tier-enforcement definition, NFR11 (zero payment data / native), NFR26 (optimistic access + revoke).
- [Source: _bmad-output/planning-artifacts/architecture.md] — tier model, `api/middleware.py` enforcement mapping, `{data,meta}`/error envelope, migration conventions, BLoC + repository + feature-folder, server-authoritative security model, billing fail-open.
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md §47/§206/§546-547/§996-1020] — three-screen minimalism (no settings screen), invisible tiers (UX-DR16), BottomOverlayCard 4-state (UX-DR5).
- [Source: _bmad-output/implementation-artifacts/8-1-integrate-storekit-2-and-google-play-billing.md] — billing package, verify endpoint, migration 014, queries, 5-min loop, the reserved Apple ASSA config fields, declared deviations.
- [Source: _bmad-output/implementation-artifacts/8-2-build-paywall-screen-with-invisible-tier-design.md] — PaywallSheet 4 states + entry points, Restore flow, FR29 thread, native-sheet revert, F16/F17 status.
- [Source: _bmad-output/implementation-artifacts/deferred-work.md] — the `count_user_call_sessions_total` tier-transition bug (Epic 8), F4-func (app-lifetime listener), F11/F12 (Google expiry), F17 (pending spinner), CallUsage negative clamp.
- [Source: project memory] — `project_story_8_1_store_setup.md` (ASSA fields UNSET = 8.3), `feedback_review_required_before_done.md` (review + smoke gate both required for `done`), `feedback_content_is_server_side.md`, `feedback_sqlite_table_rebuild_fk.md`, `project_design_rulebook_handlers_brief.md`.

## Dev Agent Record

### Agent Model Used

_TBD by dev-story_

### Debug Log References

### Completion Notes List

### File List
