# Story 8.3: Build Subscription Management and Full Tier Enforcement

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to view my subscription status and have the system correctly enforce my access level,
so that I get exactly what I'm paying for and can manage my subscription easily.

> **One-paragraph orientation (read this first).** Stories 8.1 and 8.2 already shipped *purchasing* (native IAP + server-side receipt validation + tier flip to `paid`) and the *paywall UI* (4-state sheet + 3 entry points + Restore). **8.3 is the last functional Epic-8 story: it makes tier enforcement complete and server-authoritative, adds the read/manage side of subscriptions (a real "Manage Subscription" screen), and makes subscriptions actually lapse.** Concretely, 8.3 closes the gaps the first two stories knowingly deferred: (1) the free-call counter currently counts *lifetime* sessions so a churned paid→free user is stuck at 0 calls forever; (2) `expires_at` is stored but never enforced, so subscriptions never lapse and cancellations are never detected; (3) there is no `GET /user/profile`, no app-lifetime purchase listener, no in-app way to see status or open the native manage screen. **Most of 8.3 is server-side and fully testable now via pytest; the live-purchase/webhook paths are on-device/store-blocked exactly like 8.1/8.2 (see Test Strategy).**

## Acceptance Criteria

_Verbatim from epics.md (Epic 8, Story 8.3). These are the canonical pass/fail gates._

1. **AC1 (FR30 — native subscription management).** **Given** FR30 requires subscription management, **when** a paid user wants to manage their subscription, **then** the app provides access to the native subscription management screen (StoreKit 2 / Google Play — platform-managed, not custom UI).

2. **AC2 (FR31 — scenario tier gating).** **Given** FR31 requires tier enforcement based on free/paid status, **when** a free user attempts to call a paid scenario, **then** the paywall is shown instead.

3. **AC3 (FR31 — daily call limit / call-icon disablement).** **Given** FR31 requires daily call limit enforcement, **when** a user has exhausted their daily calls, **then** call icons on all scenarios are non-functional and the BottomOverlayCard reflects the appropriate state (UX-DR5).

4. **AC4 (BottomOverlayCard 4-state matrix — UX-DR5).** **Given** the BottomOverlayCard has 4 states, **when** the user's status changes, **then** the overlay card updates correctly: free/calls remaining → "Unlock all scenarios", free/0 calls → "Subscribe to keep calling", paid/calls available → hidden, paid/0 calls today → "No more calls today".

5. **AC5 (`GET /user/profile` + server-side `POST /calls/initiate` enforcement).** **Given** `GET /user/profile` returns subscription status, **when** the app requests the user profile, **then** it includes tier (free/paid), calls remaining today, and subscription expiry date. **And** the server enforces limits on `POST /calls/initiate` — returning HTTP 403 with error code `CALL_LIMIT_REACHED` or `TIER_RESTRICTED` if limits are exceeded.

6. **AC6 (subscription expiry / cancellation → revert to free).** **Given** a user's subscription expires or is cancelled, **when** the tier reverts to free, **then** the user retains access to all past debriefs but loses access to paid scenarios and the daily call limit changes to the free tier.

---

## ✅ DECISIONS — RESOLVED by Walid 2026-06-18 (these are settled; build to them)

These five were surfaced at create-story and Walid ruled on each. **The spec below is written to his rulings, not to the original recommended defaults.**

- **D1 — Manage-subscription surface = a REAL, fully-designed screen (route), with a minimalist hub entry.** Walid: *"un écran gérer mon abonnement est tout à fait possible"* — build a proper screen. Its design is **binding** and lives in [`manage-subscription-screen-design.md`](../planning-artifacts/manage-subscription-screen-design.md), produced by a dedicated multi-agent design pass (our design-DNA analysis + current mobile-UX research + platform-compliance research → synthesis → two adversarial critiques → finalize), with explicit attention to **mobile non-clickable / unsafe zones** (SafeArea top+bottom, no tap target under the home-indicator, nothing draggable in the edge-back-swipe gutters, ≥44dp tap targets). The **entry link stays minimal** on the Scenarios hub (a quiet, tier-neutral grey `Account` line) so the small app's main screen is not cluttered. **Read the design doc — it is the single source of truth for Task 7's UI.** One copy item still needs Walid sign-off before/at dev (see "Open copy sign-off" below).

- **D2 — A churned paid→free user returns to WHERE THEY WERE, not to a fresh 3.** Walid: *"un payant qui annule ne récupère [pas] 3 appels gratuits mais revient là où il en était — si il a utilisé 2 appels avant de payer, quand il annule il lui restera 1 appel."* So the free lifetime cap counts **only the calls made WHILE on the free tier** (paid-era calls never consume a free credit). Implementation = **stamp the tier on every `call_session` at initiate time** (`tier_at_call`), and count free usage as `calls made with tier_at_call='free'` (lifetime). This is robust across any number of free↔paid transitions (a single `tier_changed_at` timestamp cannot reconstruct multi-transition history; a per-call stamp can). Requires **migration 015** (Task 0).

- **D3 — Cancellation/expiry detection = WEBHOOKS (store-push), not polling.** Walid: *"si via webhook, c'est plus propre, on fait les choses propre."* Build **Apple App Store Server Notifications V2** + **Google Play Real-Time Developer Notifications (RTDN)** receiver endpoints as the primary lifecycle signal (renew / expire / cancel / refund / revoke / grace), with a lighter periodic **safety-net sweep kept as a backstop** (defense-in-depth — webhooks can be missed/misconfigured). The Apple notification body is a **signed JWS verifiable OFFLINE** with the SAME `SignedDataVerifier` infra 8.1 already uses → **no App Store Server API key needed to receive+verify notifications** (this is why D3 webhooks are compatible with D4's defer). See Task 5.

- **D4 — DEFER the Apple App Store Server API (online PULL) path.** Walid: *"ok on branche pas pour l'instant."* Keep `apple_issuer_id` / `apple_key_id` / `apple_private_key_p8` UNSET (as 8.1 reserved them); leave the in-code TODO. Note: ASSN webhooks (D3) do **not** need these — they verify the pushed JWS offline. The pull API (server-initiated transaction-history/status lookup) is the deferred piece.

- **D5 — BUILD `GET /user/profile`.** Walid: *"oui si vraiment utile … le projet a évolué … oui."* It is genuinely useful (the new Manage Subscription screen reads it for the expiry date, which no steady-state endpoint exposes today) — not just an AC literal. Build it (Task 2).

**Copy — APPROVED by Walid 2026-06-18 (closes the design doc's R-copy):** paid-plan display label = **`Premium`**; CTA strings = **`Subscribe`** (free) / **`Manage subscription`** (paid). ⚠️ **`Premium` is a display label only — the tier value stays `'paid'` (ADR 002). Do NOT add a `'premium'` tier string** (it would break the `users.tier` CHECK + `compute_call_usage`).

---

## Tasks / Subtasks

### Task 0 — Server: migration 015 (D2 per-call tier stamp + D3 webhook dedup)

- [x] New `server/db/migrations/015_tier_at_call_and_subscription_events.sql`. **ADD-only, no table rebuild** (so no `PRAGMA foreign_keys` toggle; replays cleanly on the prod snapshot — same posture as 008/014):
  - [x] `ALTER TABLE call_sessions ADD COLUMN tier_at_call TEXT CHECK(tier_at_call IS NULL OR tier_at_call IN ('free','paid'));` — nullable, no default. **Legacy rows stay NULL and are treated as `'free'` via `COALESCE(tier_at_call,'free')` in the count** (prod history is effectively all free-era; documented assumption). Going forward, `/calls/initiate` stamps the user's tier at call time.
  - [x] `CREATE TABLE IF NOT EXISTS subscription_events (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL CHECK(provider IN ('apple','google')), notification_id TEXT NOT NULL UNIQUE, notification_type TEXT, received_at TEXT NOT NULL, processed_at TEXT);` — the webhook idempotency/audit ledger (`notification_id` = Apple `notificationUUID` / Google Pub/Sub `messageId`; `UNIQUE` makes replays no-ops).
- [x] Add `test_migration_015_*` to `server/tests/test_migrations.py` mirroring `test_migration_014_subscriptions` (assert the new column via `PRAGMA table_info`, the CHECK rejections via `sqlite3.IntegrityError`, the `subscription_events` table + UNIQUE). **Keep `test_migrations_apply_against_prod_snapshot_with_no_violations` green** (it replays 001→015 on `tests/fixtures/prod_snapshot.sqlite`).
- [x] Post-deploy: refresh + commit the snapshot — `cd server && python scripts/refresh_prod_snapshot.py` (the established post-deploy step, as for 011/012/013/014). Done 2026-06-18 (snapshot now carries migration 015 + `subscription_events`; `test_migrations` green, FK violations 0).

### Task 1 — Server: tier-transition-aware free-call counting (AC6, D2) ⟵ the headline server fix

- [x] **Stamp the tier at call time.** In `server/api/routes_calls.py` `/calls/initiate`, pass the loaded `user["tier"]` into the call-session INSERT; add a `tier_at_call` arg to the `insert_call_session(...)` query in `server/db/queries.py`.
- [x] **Count free usage as free-era only.** Add an optional `tier_at_call: str | None = None` filter to `count_user_call_sessions_total` and `count_user_call_sessions_since` (`server/db/queries.py`); when provided, append `AND COALESCE(tier_at_call,'free') = ?`.
- [x] In `server/api/usage.py` `compute_call_usage`:
  - [x] **Free path:** `used = await count_user_call_sessions_total(db, user_id, tier_at_call='free')`; `period = "lifetime"`. (Counts only calls made while free, lifetime → a reverted user keeps their prior free-era count = "returns where they were".)
  - [x] **Paid path:** `used = await count_user_call_sessions_since(db, user_id, _utc_day_start_iso(now), tier_at_call='paid')`; `period = "day"`. (Paid daily cap counts only today's *paid-era* calls → a fresh upgrader gets a clean 3 even if they made a free call earlier today.)
  - [x] `calls_remaining = max(0, CALLS_PER_PERIOD - used)`; keep the `ValueError` on tier ∉ {free,paid}.
- [x] Both `compute_call_usage` callers (`routes_calls.py` initiate gate, `routes_scenarios.py` meta) need no signature change (tier already passed; the tier_at_call filter is internal to usage.py).
- [x] Tests in `server/tests/test_call_usage.py`: never-paid free user counts all free calls (regression); a user with 2 free-era + N paid-era calls who is now free → `calls_remaining == 1` (Walid's exact example); paid daily ignores earlier same-day free calls; `failed` sessions still excluded; legacy NULL `tier_at_call` counts as free.

### Task 2 — Server: `GET /user/profile` endpoint (AC5, D5)

- [x] New route module `server/api/routes_user.py`: `APIRouter(prefix="/user", tags=["user"], dependencies=[AUTH_DEPENDENCY])`, `GET /user/profile`. Register in `server/api/app.py` alongside the other routers.
- [x] Handler: resolve `user_id` → `get_user_by_id` → `compute_call_usage(db, user_id, user["tier"])` → `expiry = await get_active_entitlement_expiry(db, user_id)`. Return via `ok(...)` `{data, meta}`.
- [x] New query `get_active_entitlement_expiry(db, user_id) -> str | None` in `server/db/queries.py`: latest `expires_at` among `purchases WHERE user_id=? AND validation_status='valid' AND expires_at IS NOT NULL` ordered `expires_at DESC LIMIT 1`. No raw SQL in the route (Boundary 4).
- [x] Response model `UserProfileOut` in `server/models/schemas.py`: `tier: Literal["free","paid"]`, `calls_remaining: int`, `calls_per_period: int`, `period: str`, `subscription_expires_at: str | None`. snake_case; `subscription_expires_at: null` is meaningful (no subscription on record) → keep it explicit.
- [x] Tests `server/tests/test_user_profile.py`: 401 without JWT; free user → `tier:"free"` + correct `calls_remaining` + `subscription_expires_at: null`; paid user with a valid future-dated purchase → `tier:"paid"` + expiry echoed; envelope `{data, meta}`.

### Task 3 — Server: full tier/limit enforcement on `POST /calls/initiate` (AC2, AC5)

- [x] In `server/api/routes_calls.py` initiate handler, BEFORE the existing `CALL_LIMIT_REACHED` check, add a **scenario-tier gate**: if `user["tier"] == "free"` AND the target scenario is **not free** (`scenario["is_free"]` falsy) → `HTTPException(403, {"code": "TIER_RESTRICTED", "message": "..."})`. Today the paid-scenario gate is client-only (8.2) — a free user could bypass the paywall by hitting the API directly; this closes it server-side.
  - [x] Re-assert inside the `BEGIN IMMEDIATE` block (mirror the existing TOCTOU re-check for the limit) so the gate holds under concurrency, before the INSERT.
- [x] Keep `CALL_LIMIT_REACHED` 403 (now powered by Task 1's free-era count). Both use the canonical `{"error":{"code","message"}}` envelope.
- [x] Tests `server/tests/test_calls.py`: free user + paid scenario → 403 `TIER_RESTRICTED` (no row, no LiveKit token); free user + free scenario at cap → 403 `CALL_LIMIT_REACHED`; paid user + paid scenario under cap → 200 (and the inserted row carries `tier_at_call='paid'`).

### Task 4 — Server: expiry enforcement + downgrade backstop (AC6, F11/F12)

- [x] **Fix the Google validator (deferred F11/F12)** `server/billing/google_validator.py` (the bug is at lines 166-179):
  - [x] **F12** (line 171, `expires_at = max(expiries)`): select `expiryTime` **chronologically** — parse each matching line-item `expiryTime` (RFC3339; tolerate fractional seconds + `Z`) to an aware `datetime`, take the max by datetime, return its ISO string. Today `max()` over raw strings is lexicographic.
  - [x] **F11** (the `if state in _ACTIVE_STATES` branch, line 173): after the state check, **also reject when the chosen expiry parses to `≤ now`** → `ValidationResult(valid=False, status="invalid", reason="expired")`, mirroring the Apple guard (`apple_validator.py` already rejects `expiresDate <= now`).
- [x] **Expiry-downgrade backstop sweep** in `server/billing/revalidation.py`: new `async def downgrade_expired_entitlements(db, *, now=None) -> int`. New query `get_users_with_expired_entitlement(db, now)` → users where `tier='paid'` AND there is **no** `valid` purchase with `expires_at > now`. For each, atomically (`BEGIN IMMEDIATE`) `update_user_tier(db, user_id, "free", tier_changed_at=now_iso())`. **Do NOT mutate the purchase row** (it was validly issued; it stops granting purely because `expires_at ≤ now`). Idempotent; fail-soft per user.
- [x] Wire `downgrade_expired_entitlements` into the existing 5-min loop `_subscription_revalidation_loop` (`server/api/app.py`), right after `revalidate_pending_purchases`, on the shared `stop_event`. This is the **backstop**; webhooks (Task 5) are the primary path.
- [x] **AC6 "retains access to all past debriefs":** verify debriefs are never tier-gated; add a one-line test that a `free` user can still read a previously-created debrief.
- [x] Tests: `test_billing.py` — Google `ACTIVE` state but past `expiryTime` → `invalid` (the missing F11 case); chronological vs lexicographic expiry pick (F12, fractional-second strings). `test_subscription.py` — `downgrade_expired_entitlements` flips an expired-paid user → free + stamps `tier_changed_at`; leaves a future-dated paid user alone; leaves a free user alone; a user with one expired + one future-valid purchase stays paid.

### Task 5 — Server: subscription lifecycle WEBHOOKS (AC6, D3) — primary detection path

> Both endpoints are **unauthenticated to the app JWT** (Apple/Google POST to them), secured instead by verifying the signed payload / Pub/Sub token, and **idempotent** via `subscription_events`. Each must **return 200 quickly** (Apple & Pub/Sub retry on non-2xx). They are **structurally buildable + unit-testable now**; the live store wiring (App Store Connect notification URL; Google Pub/Sub topic + push subscription) is **store-config-gated** like everything IAP (8.1-D4 + 10-4) → flag as deferred-to-live.

- [x] **Apple — `POST /subscription/webhook/apple`** (no `AUTH_DEPENDENCY`). Body `{ "signedPayload": "<JWS>" }`. **Verify the JWS OFFLINE** with the same `app-store-server-library` verifier infra used in `billing/apple_validator.py` (no App Store Server API key — D4 stays deferred). Decode `ResponseBodyV2DecodedPayload` → `notificationType` (+ `subtype`) and the nested `signedTransactionInfo` / `signedRenewalInfo` (verify these too). Map:
  - `DID_RENEW` → re-stamp `expires_at` (from the renewal/transaction info), keep `paid`.
  - `EXPIRED`, `GRACE_PERIOD_EXPIRED` → downgrade user to `free` (stamp `tier_changed_at`).
  - `REFUND`, `REVOKE` → downgrade to `free` immediately.
  - `DID_CHANGE_RENEWAL_STATUS` (subtype `AUTO_RENEW_DISABLED`) → record cancellation intent; **keep `paid` until `expires_at`** (correct subscription behavior — see the design doc's "Access until" state).
  - Dedup on `notificationUUID` via `subscription_events` (insert-or-skip).
- [x] **Google — `POST /subscription/webhook/google`** (no `AUTH_DEPENDENCY`). Body = Pub/Sub push envelope `{ "message": { "data": "<base64 JSON>", "messageId": "..." } }`. **Secure it** by verifying the Pub/Sub OIDC bearer token (audience check) — or, acceptable interim, a hard-to-guess secret path segment configured on the push subscription; document the choice. Decode `data` → `{ subscriptionNotification: { purchaseToken, notificationType, subscriptionId }, packageName }`. On any lifecycle `notificationType` (`SUBSCRIPTION_RENEWED`, `SUBSCRIPTION_EXPIRED`, `SUBSCRIPTION_CANCELED`, `SUBSCRIPTION_REVOKED`, `SUBSCRIPTION_IN_GRACE_PERIOD`, `SUBSCRIPTION_ON_HOLD`, …) **re-call `validate_google(purchase_token)`** (already built in 8.1) to get the authoritative state, then update the matching `purchases` row + `users.tier` accordingly (active/grace → keep paid + refresh `expires_at`; expired/revoked/on-hold-past-grace → downgrade to free). Dedup on `messageId`.
- [x] Resolve a notification's `purchaseToken`/`transaction_id` back to a user via the `purchases` table (`verification_token` / `transaction_id`). If no matching purchase row exists, ACK 200 and log (a notification for an unknown token is not an error).
- [x] Config: add the webhook-security knobs to `server/config.py` (e.g. `google_pubsub_audience`/secret), default-empty so the server boots without them; the Apple path needs only the existing `apple_bundle_id` + roots.
- [x] Tests `server/tests/test_subscription_webhooks.py`: Apple — a crafted/mocked-verified `EXPIRED` payload downgrades the user; `DID_RENEW` refreshes `expires_at` + keeps paid; `DID_CHANGE_RENEWAL_STATUS/AUTO_RENEW_DISABLED` keeps paid; a forged/invalid JWS is rejected (no tier change); replay of the same `notificationUUID` is a no-op. Google — `SUBSCRIPTION_EXPIRED` (with `validate_google` mocked to `invalid`/expired) downgrades; `SUBSCRIPTION_RENEWED` (mocked `valid`) keeps paid + refreshes expiry; bad/missing Pub/Sub token → 401/403; duplicate `messageId` is a no-op; unknown `purchaseToken` → 200 + logged. Always-200-on-handled-error contract asserted.

### Task 6 — Client: app-lifetime `purchaseStream` listener (AC6, deferred F4-func)

- [x] New app-scoped service `client/lib/features/subscription/services/purchase_sync_service.dart` (mirror the `EndCallRetryService` app-singleton precedent in `main.dart`). Holds `InAppPurchaseService` + `SubscriptionRepository`. `.listen()`s to `purchaseStream` for the **whole app lifetime**; for each re-delivered `purchased`/`restored` transaction it `verifyPurchase(...)` then `complete(...)` (reuse 8.1 plumbing — no duplicate verify logic), independent of whether the paywall is open. Expose a `Stream<void> onEntitlementChanged` (or `ValueListenable`) that fires after a successful verify.
- [x] Construct it in `client/lib/main.dart` `bootstrap()` BEFORE `runApp` (next to `EndCallRetryService`); provide via `RepositoryProvider.value` in `app.dart`. On `onEntitlementChanged`, the hub dispatches a silent `RefreshScenariosEvent` so tier re-flows from `/scenarios` meta.
- [x] **Do NOT** remove/alter the paywall bloc's own (sheet-scoped) stream subscription — both coexist; `complete()` + the verify endpoint are idempotent (409-guarded server-side), so a duplicate verify is safe. Preserve restore semantics (8.2 F16 intentional).
- [x] Tests: a fake `InAppPurchaseService` emits a `purchased` event while no paywall is mounted → the service `verifyPurchase` + `complete` + fires `onEntitlementChanged`. `FlutterSecureStorage.setMockInitialValues({})` in `setUp`; never `pumpAndSettle` on spinners.

### Task 7 — Client: the Manage Subscription screen (AC1) + minimalist hub entry + CallUsage clamp ⟵ build to the binding design doc

> **The binding UI spec is [`manage-subscription-screen-design.md`](../planning-artifacts/manage-subscription-screen-design.md).** Implement it exactly (it already resolves layout, tokens, copy, states A–F, mobile safe/unsafe zones, accessibility, navigation, and the reuse map). Highlights below; the doc governs on any conflict.

- [x] **`UserProfile` model + read path.** New `client/lib/features/subscription/models/user_profile.dart` (mirror `CallUsage`/`SubscriptionStatus`; `tier`/`callsRemaining`/`callsPerPeriod`/`period`/`subscriptionExpiresAt`). New `UserRepository.getProfile()` (or extend `SubscriptionRepository`) → `GET /user/profile`, reusing `ApiClient`. A `UserProfileBloc`/`Cubit` (4 base states) drives the screen.
- [x] **`ManageSubscriptionScreen`** — dark app surface, route-pushed, no AppBar; pinned-CTA structure (the `EmpatheticErrorScreen` pattern); states A (free), B (paid renews), C (paid cancelled-until-expiry; default to "Renews" if no auto-renew flag — design R3), D (expired/reverted), E (loading skeleton), F (error → reuse `EmpatheticErrorScreen`). Use ONLY existing tokens (no new `AppColors` — keep `theme_tokens_test` count==16; no inline hex). `Subscribe` → `PaywallSheet.show`; `Manage subscription` → native handoff (Task 7b); `Restore purchases` → existing `RestorePressed` flow; legal footer (Terms/Privacy flat `Text.rich` links). All tap targets ≥44dp; SafeArea top+bottom; nothing under the home indicator; no horizontally-draggable controls.
- [x] **`_AccountHubLine`** on the Scenarios hub — a quiet, **trailing (right-aligned)**, tier-neutral grey `Account` line stacked directly above `_DifficultyHubLine`, ≥44dp hit box, on the 18-rail. `onTap` → `context.push(AppRoutes.account)`. **Minimal — no tier badge, invisible tiers preserved (UX-DR16).** (Per Walid D1: keep the hub uncluttered while the app is small.)
- [x] **Router:** add `AppRoutes.account = '/account'` + a `GoRoute` using the existing `_fadePage`.
- [x] **Task 7b — native manage handoff (`StoreLinks` helper).** `url_launcher` (already a dep), `LaunchMode.externalApplication`. iOS: `https://apps.apple.com/account/subscriptions` (fallback `itms-apps://…`). Android: `https://play.google.com/store/account/subscriptions?sku=stt_weekly_199&package=<applicationId>` (both params required; get `<applicationId>` at runtime from `PackageInfo.fromPlatform()` — **add `package_info_plus`**). Inline `AppColors.destructive` text on launch failure; never a dialog.
- [x] **New deps:** `intl` (format `subscription_expires_at` as `d MMM yyyy`; never show raw ISO), `package_info_plus` (Android package id).
- [x] **`CallUsage` negative clamp** (deferred item — triggered because the new screen displays `calls_remaining`): in `client/lib/features/scenarios/models/call_usage.dart` `fromMeta`, `callsRemaining = max(0, json['calls_remaining'] as int)`; assert `calls_per_period > 0` else `FormatException`. Mirror in the `UserProfile` parse.
- [x] Tests (per the design doc §10 R5 + house patterns): screen renders each state via the bloc seam; `StoreLinks` launches the correct per-platform URL (mock `url_launcher`); free→Subscribe opens the paywall; paid→Manage launches the store; Restore success → toast + flip, empty → "Nothing to restore."; overflow test at `Size(320,480)` × `textScaler 2.0`; theme-token count unchanged; `_AccountHubLine` pushes the route and shows no tier signal. `FlutterSecureStorage.setMockInitialValues({})`; `pump(Duration)` not `pumpAndSettle` for any timed UI.

### Task 8 — Client: AC3/AC4 live-state verification (mostly already built — verify + close gaps)

- [x] **AC4 BOC matrix** is already implemented (`bottom_overlay_card.dart` `_variantFor`): free+calls→"Unlock all scenarios", free/0→"Subscribe to keep calling", paid+calls→hidden (`SizedBox.shrink`), paid/0→"No more calls today"/"Come back tomorrow". **Verify it reflects LIVE status after a tier change** (purchase, expiry-downgrade) via the post-event `/scenarios` reload. Keep widget tests for all 4 variants.
- [x] **AC3 call-icon disablement at 0 calls.** Confirm that when `usage.callsRemaining == 0` the per-scenario call icons are **non-functional** (tapping must NOT initiate a call). The server returns 403 and the client routes it to the paywall; make the client also reflect the inert affordance proactively (no reliance on a round-trip). Widget test: 0 calls → tapping a call icon does not dispatch `_startCall`/`InitiateCall`.
- [x] **Do NOT** restyle the BOC or add tier badges to cards (UX-DR16).

### Task 9 — Tests + gates (all green before commit, per CLAUDE.md)

- [x] Server: `cd server && python -m ruff check . && python -m ruff format --check . && <venv> -m pytest` — all green (warm `import aiohttp` once if cold). Includes `test_migrations` (with 015).
- [x] Client: `cd client && flutter analyze` → "No issues found!" (zero infos) and `flutter test` → all pass.
- [x] Update the story File List + Completion Notes + declare any deviations.

### Task 10 — Deploy + Smoke Test Gate (server) + on-device deferral

- [x] Deploy to VPS (migration 015 auto-applies; pre-deploy DB backup via `deploy-server.yml`); confirm `/health` git_sha matches. Refresh + commit `prod_snapshot.sqlite` post-deploy. Done 2026-06-18 (CI run 27756245681; `/health` git_sha=f6d69ee; backup db.pre-f6d69ee.sqlite; snapshot refreshed + committed).
- [x] Fill the **Smoke Test Gate (Server)** boxes with real output. Done (all 8 boxes above filled from prod).
- [x] **On-device IAP gate + live webhooks are DEFERRED** (real purchase/renewal/restore/manage-deep-link/store-push untestable until 8.1-D4 store config lands AND Story 10-4 ships the iOS pipeline) — same posture as 8.1/8.2. Server enforcement (count rework, `/user/profile`, `TIER_RESTRICTED`, expiry sweep, webhook handlers with crafted payloads) is fully pytest-testable now; the Android `url_launcher` manage path + the screen are widget-testable. Note this explicitly in the review summary so the story isn't blocked on an ungated capability.

---

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** Included — this story ships migration 015, `GET /user/profile`, changed `POST /calls/initiate` enforcement, two webhook endpoints, and an extended revalidation loop. **DB-migration boxes APPLY (015).**
>
> **Transition rule:** Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output as proof.

_All boxes verified on prod (SHA `f6d69ee`, 2026-06-18 ~11:32-11:34 UTC) via the CI deploy + SSH. Live store-push (Apple/Google) is deferred to 8.1-D4 store config + Story 10-4; those paths are unit-tested (15 webhook tests) + the routes are proven reachable below._

- [x] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ CI deploy-server run 27756245681 success; `systemctl is-active` → `active` (MainPID 1276256); `/health` → `{"status":"ok","db":"ok","git_sha":"f6d69ee98fec..."}` (matches HEAD).

- [x] **`GET /user/profile` happy path.** Authenticated curl returns `{data:{tier, calls_remaining, calls_per_period, period, subscription_expires_at}, meta}` + HTTP 200.
  - _Command:_ `curl -sS -H "Authorization: Bearer $JWT" http://127.0.0.1/user/profile` (user 1)
  - _Actual:_ `200 {"data":{"tier":"free","calls_remaining":0,"calls_per_period":3,"period":"lifetime","subscription_expires_at":null},"meta":{"timestamp":"2026-06-18T11:32:17Z"}}`

- [x] **`TIER_RESTRICTED` + `CALL_LIMIT_REACHED` enforcement.** A `free` user calling a **paid** scenario via `POST /calls/initiate` → 403 `{"error":{"code":"TIER_RESTRICTED",...}}`; an at-cap free user on a free scenario → 403 `CALL_LIMIT_REACHED`. Canonical error envelope (not a raw 500).
  - _Command:_ `POST /calls/initiate` user 1 (free, 0 calls) — paid `cop_hard_01` then free `girlfriend_medium_01`.
  - _Actual:_ paid → `HTTP 403 {"error":{"code":"TIER_RESTRICTED","message":"This scenario is for subscribers."}}`; free → `HTTP 403 {"error":{"code":"CALL_LIMIT_REACHED","message":"You've used all your calls for now."}}`. (Both 403 BEFORE any INSERT/bot/token — no side-effect.)

- [x] **DB side-effect — D2 free-era counting.** Confirm `call_sessions.tier_at_call` is stamped on new initiates and that a user with free-era + paid-era calls computes `calls_remaining` from free-era only. Read back via the venv stdlib (no `sqlite3` CLI on the VPS).
  - _Actual:_ `PRAGMA table_info(call_sessions)` carries `tier_at_call`; user 1 rows = `[(None,'completed',74),(None,'failed',176)]` (legacy NULL = free-era via COALESCE) → free count 74 ≥ 3 → `/user/profile` `calls_remaining=0` (matches). New-initiate stamping (`tier_at_call='paid'` on a paid-user initiate) is unit-tested (`test_initiate_paid_user_paid_scenario_succeeds_and_stamps_paid`); not run live to avoid spawning a prod bot.

- [x] **DB side-effect — expiry-downgrade backstop.** Seed an expired `valid` purchase for a throwaway/test user, confirm `users.tier` flipped to `'free'` + fresh `tier_changed_at`. (Pre-deploy backup taken; throwaway deleted after.)
  - _Actual:_ throwaway uid 2 (paid + `expires_at=2020-01-01`): `before=('paid',None)`, `downgrade_expired_entitlements` returned `1`, `after=('free','2026-06-18T11:33:39Z')`; cleanup → 0 user / 0 purchase rows left. (Ran the sweep directly rather than waiting the 5-min loop tick.)

- [x] **Webhook endpoints reachable + idempotent (server-side, crafted payload).** The Apple/Google webhook routes accept a well-formed (verified/mocked) notification and are no-ops on replay (`subscription_events` UNIQUE). Live store-push is deferred; this box proves the handler + dedup work on prod.
  - _Actual:_ routes reachable — `POST /subscription/webhook/apple` → `503 SUBSCRIPTION_UNAVAILABLE` (APPLE_BUNDLE_ID absent, pre-D4); `POST /subscription/webhook/google` (no `?token=`) → `503 SUBSCRIPTION_UNAVAILABLE` (GOOGLE_PUBSUB_VERIFICATION_TOKEN absent). Full verify→tier-flip + `subscription_events` dedup + always-200-on-handled-error proven by the 15 `test_subscription_webhooks.py` tests. Live store push N/A pre store config.

- [x] **DB backup taken BEFORE deploy (migration 015).** Snapshot the prod DB so the migration is reversible.
  - _Proof:_ `deploy-server.yml` auto-backup produced `/opt/survive-the-talk/backups/db.pre-f6d69ee.sqlite`.

- [x] **Server logs clean on the happy path.** `journalctl -u pipecat.service` shows no ERROR/Traceback for the requests above, the webhook handlers, or the revalidation loop tick.
  - _Proof:_ no tracebacks/exceptions on the happy-path requests (/health, /user/profile, the two 403s, the downgrade). The only ERROR lines are the two DELIBERATE config-absent webhook probes (`apple webhook unavailable (config absent)` / `google webhook hit but ... unset`) — the intentional pre-store-config 503 path, not a crash.

---

## Dev Notes

### What already exists — REUSE, do not re-invent

**Server (Story 8.1):**
- `server/billing/` — `validate_apple`, `validate_google`, `ValidationResult{valid,status,transaction_id,expires_at,reason}`, `BillingConfigError`, `apple_roots.py` (pinned Apple Root CA-G3, used by the `SignedDataVerifier` — **the same verifier the Apple webhook reuses offline, Task 5**), `revalidation.py`.
- `POST /subscription/verify` (`server/api/routes_subscription.py`) — synchronous validate-then-flip; 200/402 `PURCHASE_INVALID`/409 `PURCHASE_CONFLICT`/503 `SUBSCRIPTION_UNAVAILABLE`. Idempotent, two-TX, cross-user-replay guarded.
- 5-min `_subscription_revalidation_loop` in `server/api/app.py` (re-checks `pending` rows only today; Task 4 adds the expiry-downgrade backstop here).
- Queries: `get_user_by_id`, `update_user_tier(...,*,tier_changed_at,commit=)`, `insert_purchase`, `update_purchase_validation`, `count_user_valid_purchases`, `get_pending_purchases`, `get_latest_purchase_by_token`, `count_user_call_sessions_total`, `count_user_call_sessions_since`, `insert_call_session`. [Source: `server/db/queries.py`]
- Migration 014 added `users.tier_changed_at` (nullable, stamped on every flip) + the `purchases` table. **Highest migration = 014 (007 is intentionally skipped); 8.3's new one = `015`.**
- Config (`server/config.py`): `apple_bundle_id`, `apple_app_apple_id`, `apple_accept_sandbox`, `google_play_package_name`, `google_service_account_json` (base64), `iap_product_id="stt_weekly_199"`. **`apple_issuer_id`/`apple_key_id`/`apple_private_key_p8` exist but UNSET — D4 = keep them UNSET; the ASSN webhook does not need them.**

**Client (Stories 8.1/8.2):**
- `client/lib/features/subscription/` — `InAppPurchaseService` (`purchaseStream`, `loadProduct`, `buy`, `complete`, `restore`, `kIapWeeklyProductId`), `SubscriptionRepository.verifyPurchase`, `SubscriptionBloc` (events `SubscribePressed`/`RestorePressed`/`RestoreLapsed`/internal `PurchaseUpdated`/`PurchaseTimedOut`; states `SubscriptionInitial`/`Loading`/`Purchased`/`Failed(code)`/`Cancelled`/`RestoreEmpty`), `SubscriptionStatus{tier,productId,expiresAt,status,isPaid}`.
- `PaywallSheet.show(context) -> Future<bool>` (native `showModalBottomSheet`, 4 states, `debugBlocBuilder` seam) + the 3 entry points in `scenario_list_screen.dart` + the `CALL_LIMIT_REACHED` ApiException → paywall route. **AC2 already satisfied client-side; Task 3 adds the server guarantee.**
- `BottomOverlayCard` 4-state `_variantFor` (AC4 implemented). `CallUsage.fromMeta` reads `/scenarios` meta `{tier,calls_remaining,calls_per_period,period}` (no clamp yet — Task 7). `ScenariosBloc` `LoadScenariosEvent` (post-purchase) + `RefreshScenariosEvent` (silent, post-call-return).
- `EndCallRetryService` app-singleton in `main.dart` `bootstrap()` (+ `RepositoryProvider.value` in `app.dart`) — **the exact precedent for the app-lifetime purchase listener (Task 6)**.
- `url_launcher: ^6.3.2` already a dep (used in `consent_screen.dart`). `EmpatheticErrorScreen`, `AppToast`, the dark theme tokens (`AppColors`/`AppTypography`/`AppSpacing`), the briefing eyebrow + paywall CTA recipes — all reused by the new screen (see the design doc reuse map §9).

### The exact tier/quota mechanism AS IMPLEMENTED (trust the code, not architecture.md)

architecture.md predates Stories 8.1/8.2 and is stale on billing/tier. As built (and as 8.3 changes it):
- `users.tier TEXT CHECK(tier IN ('free','paid'))` (canonical `'paid'`, ADR-002 — never `'full'`) + `users.tier_changed_at TEXT` (nullable).
- `compute_call_usage` (`server/api/usage.py`): **free = 3 lifetime, paid = 3 per UTC-day**; `CALLS_PER_PERIOD = 3`. **8.3 (D2) makes free count only `tier_at_call='free'` calls** so paid-era calls never burn a free credit (a churned user "returns where they were"). `tier_changed_at` stays an audit/profile field; the per-call `tier_at_call` stamp (migration 015) is what the count reads.
- `call_sessions.status CHECK(pending|completed|failed)` (008). Count queries filter `status IN ('pending','completed')` → `failed` rows refunded. 8.3 adds the `tier_at_call` column-filter on top.
- Enforced at `POST /calls/initiate` (`routes_calls.py`) → 403 `CALL_LIMIT_REACHED` (8.3 adds `TIER_RESTRICTED`). Surfaced via `GET /scenarios` meta; 8.3 adds the canonical `GET /user/profile`.
- **Google validator expiry bug is at `server/billing/google_validator.py:166-179`** — `expires_at = max(expiries)` is lexicographic (F12, line 171) and the `ACTIVE`-state branch (line 173) never checks `expiryTime ≤ now` (F11). Task 4 fixes both.

### Declared-deviation landmines inherited from 8.1/8.2 (do not trip)

- 8.1 #2 / **F4-func**: paywall bloc's stream listener is sheet-scoped — Task 6 adds an app-lifetime listener; do not change the sheet bloc's lifecycle to "fix" it.
- 8.1 #1: Google validator uses `pyjwt`+`httpx` (not `google-auth`) — stay async, add no deps when touching it (Task 4).
- 8.2 #1 + on-device defer: native `showModalBottomSheet` swipe/scrim can't be programmatically blocked mid-sheet; the custom-route attempt was reverted on-device 2026-06-18. **Do NOT re-attempt a custom paywall route.** `PopScope` blocking back is the shipped behavior.
- 8.2 F16: `restored` auto-flipping tier is intentional (the restore feature) — Task 6's listener must preserve it.
- `compute_call_usage` raises `ValueError` for tier ∉ {free,paid} (swallowed by a broad 500) — keep the canonical set `{free, paid}`.

### Architecture & cross-cutting constraints (binding)

- **Tier is server-authoritative.** The client paywall/gate is UX; the real gate is `POST /calls/initiate` (Task 3). Never set tier locally; the client learns it from `/scenarios` meta + `/user/profile`. [architecture.md FR-mapping; ADR-002]
- **API envelope (non-negotiable):** success `{data, meta}`, error `{"error":{"code","message"}}`, all JSON `snake_case`, 403 for tier/limit, JWT-required routes via `AUTH_DEPENDENCY`. **Exception:** the two webhook routes are NOT app-JWT routes (Apple/Google post to them) — secure them by signed-payload / Pub/Sub-token verification instead (Task 5).
- **DB access only via `server/db/queries.py`** — no raw SQL in route handlers.
- **Migration safety:** 015 must keep `tests/test_migrations.py` green against `prod_snapshot.sqlite`; ADD-only so no `PRAGMA foreign_keys` toggle; refresh + commit the snapshot post-deploy. [project CLAUDE.md §Database Migrations; server/CLAUDE.md §2]
- **Billing failures fail-open to free-tier behavior** — never hard-block app usage on a verify/validation/webhook error; webhook handlers return 200 even on a handled internal error (Apple/Google retry otherwise). [architecture.md degradation]
- **Design rulebook "The Handler's Brief" + the binding [`manage-subscription-screen-design.md`](../planning-artifacts/manage-subscription-screen-design.md)** govern the new screen: one left rail, two-ink (accent green is fill-only, never text/icon), zero furniture, A2/B1, banned-copy lint, ≥44dp targets, SafeArea + non-clickable-zone discipline. **Invisible tiers (UX-DR16):** no tier badges on scenario cards; the hub `Account` line is tier-neutral and minimal.

### Test Strategy (server fully testable now; live IAP/webhooks deferred)

- **Server (pytest, runnable now):** mock validators (patch at `api.routes_subscription.*` / `billing.revalidation.*` / the webhook verifier); never hit real stores. Follow `test_subscription.py`/`test_billing.py`/`test_call_usage.py`/`test_migrations.py` patterns + the new `test_user_profile.py` / `test_subscription_webhooks.py`. Loguru temp sink (not `caplog`, server/CLAUDE.md §3). The whole enforcement surface (count rework, `/user/profile`, `TIER_RESTRICTED`, Google expiry, expiry sweep, webhook handlers via crafted payloads) is verifiable here.
- **Client (flutter_test):** `mocktail` + `bloc_test`; `FlutterSecureStorage.setMockInitialValues({})` in every `setUp`; `registerFallbackValue` for sealed events; **never `pumpAndSettle` on a spinner — use `pump(Duration)`**; drive UI via the `debugBlocBuilder` seam + a `MockSubscriptionBloc`; `setSurfaceSize(Size(320,480))` + `textScaler 2.0` for overflow; theme-token test asserts exact token count (no inline hex).
- **On-device (DEFERRED):** real purchase/renewal/restore/native-manage-launch + live store webhooks blocked until 8.1-D4 store config + Story 10-4 iOS pipeline. State this in the review summary; the story reaches review-complete via code review + the server Smoke Test Gate + widget/unit tests, like 8.1/8.2.

### Project Structure Notes

- **New server files:** `server/db/migrations/015_tier_at_call_and_subscription_events.sql`, `server/api/routes_user.py`, `server/tests/test_user_profile.py`, `server/tests/test_subscription_webhooks.py`. New queries in `server/db/queries.py` (`get_active_entitlement_expiry`, `get_users_with_expired_entitlement`, the `tier_at_call` filter param, `subscription_events` insert/dedup). **Modified:** `server/api/usage.py`, `server/api/routes_calls.py`, `server/api/routes_scenarios.py` (no sig change), `server/api/routes_subscription.py` (webhook routes, or a new `routes_subscription_webhooks.py`), `server/api/app.py` (register routers + extend the 5-min loop), `server/billing/google_validator.py`, `server/billing/revalidation.py`, `server/billing/apple_validator.py` (expose the notification verify helper), `server/models/schemas.py`, `server/config.py`, plus tests + `test_migrations.py`.
- **New client files:** `purchase_sync_service.dart`, `models/user_profile.dart`, a `UserRepository` + `UserProfileBloc`/cubit, `ManageSubscriptionScreen` + `_AccountHubLine` + a `StoreLinks` helper. **Modified:** `main.dart`, `app/app.dart`, `app/router.dart`, `subscription_bloc.dart`/`subscription_state.dart` (F17 — Task moved into the bloc; see below), `paywall_sheet.dart` (F17 render), `call_usage.dart` (clamp), `scenario_list_screen.dart` (hub line + AC3) + tests. **New deps:** `intl`, `package_info_plus`.
- **F17 (pending-approval state)** — fold into Task 6/7: add `SubscriptionPendingApproval` to `subscription_state.dart`; `subscription_bloc.dart` `_onPurchaseUpdated` `case PurchaseStatus.pending:` emits it (instead of staying `Loading` forever); `paywall_sheet.dart` renders it dismissible with copy "Waiting for approval" / "You can close this." (declarative, no exclamation). When the stream later resolves, the bloc transitions normally.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-8-Story-8.3] — user story + AC1–AC6 verbatim; FR30/FR31; UX-DR5/UX-DR16.
- [Source: _bmad-output/planning-artifacts/prd.md] — FR20/FR21 (3 scenarios / 3 calls lifetime vs 3/day), FR28–FR31, NFR11 (zero payment data / native), NFR26 (optimistic access + revoke).
- [Source: _bmad-output/planning-artifacts/manage-subscription-screen-design.md] — **binding** UI spec for Task 7 (layout, tokens, copy, states A–F, safe/unsafe zones, a11y, navigation, reuse map, open items R-copy/R1–R7).
- [Source: _bmad-output/planning-artifacts/architecture.md] — tier model, `{data,meta}`/error envelope, migration conventions, BLoC + repository + feature-folder, server-authoritative security model, billing fail-open.
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md §47/§206/§546-547/§996-1020] — three-screen minimalism, invisible tiers (UX-DR16), BottomOverlayCard 4-state (UX-DR5).
- [Source: _bmad-output/implementation-artifacts/8-1-integrate-storekit-2-and-google-play-billing.md] — billing package, verify endpoint, migration 014, queries, 5-min loop, reserved Apple ASSA config fields, declared deviations.
- [Source: _bmad-output/implementation-artifacts/8-2-build-paywall-screen-with-invisible-tier-design.md] — PaywallSheet 4 states + entry points, Restore flow, FR29 thread, native-sheet revert, F16/F17 status.
- [Source: _bmad-output/implementation-artifacts/deferred-work.md] — the `count_user_call_sessions_total` tier-transition bug (Epic 8), F4-func (app-lifetime listener), F11/F12 (Google expiry), F17 (pending spinner), CallUsage negative clamp.
- [Source: server/CLAUDE.md §2] migration replay, §3 loguru sink; [project memory] `project_story_8_1_store_setup.md`, `feedback_review_required_before_done.md`, `project_design_rulebook_handlers_brief.md`, `feedback_sqlite_table_rebuild_fk.md`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (dev-story, 2026-06-18)

### Debug Log References

- Server gates: `python -m ruff check .` ✅, `ruff format --check .` ✅, full `pytest` → **994 passed** (warm `aiohttp`).
- Client gates: `flutter analyze` → **No issues found!**, `flutter test` → **635 passed**.

### Completion Notes List

Implementation complete for Tasks 0–9 (code + automated gates green). Task 10
(VPS deploy + on-prod Smoke Test Gate + `prod_snapshot` refresh) is OWED; the
on-device IAP / live-webhook gate is DEFERRED (8.1-D4 store config + Story 10-4),
same posture as 8.1/8.2.

- **Task 0 — migration 015.** ADD-only: `call_sessions.tier_at_call` (free/paid
  CHECK, nullable) + `subscription_events` (provider CHECK + UNIQUE
  notification_id). `test_migrations` green incl. the prod-snapshot replay.
  Snapshot refresh is post-deploy (owed).
- **Task 1 — free-era counting (D2).** `insert_call_session` stamps
  `tier_at_call`; the two count queries take an optional `tier_at_call` filter
  (`COALESCE(tier_at_call,'free')`); `compute_call_usage` free=free-era-lifetime,
  paid=today's-paid-era. The churned 2-free-then-paid→1-left case is tested.
- **Task 2 — `GET /user/profile`.** New `routes_user.py` + `UserProfileOut` +
  `get_active_entitlement_expiry`. 401 / free / paid+expiry / latest-valid /
  null-expiry covered.
- **Task 3 — server tier gate.** `/calls/initiate` 403 `TIER_RESTRICTED` (free +
  paid scenario), re-asserted inside `BEGIN IMMEDIATE` against a re-read tier;
  `CALL_LIMIT_REACHED` powered by the free-era count.
- **Task 4 — expiry enforcement.** Google validator F11 (active+past-expiry →
  invalid) + F12 (chronological RFC3339 max, nanosecond-tolerant);
  `downgrade_expired_entitlements` backstop wired into the 5-min loop; AC6
  debrief-access test added (debriefs not tier-gated).
- **Task 5 — webhooks.** Apple ASSN V2 offline-verify (`verify_apple_notification`
  reusing `SignedDataVerifier`, F1 env guard) + Google RTDN (Pub/Sub push,
  secret `?token=` gate, authoritative re-validate). New
  `routes_subscription_webhooks.py` (no AUTH_DEPENDENCY); dedup via
  `subscription_events`; always-200-on-handled-error.
- **Task 6 — app-lifetime listener.** `PurchaseSyncService` verifies+completes
  re-delivered purchases + `onEntitlementChanged`; wired in `bootstrap()` +
  provided in `app.dart`; hub silently refreshes on it.
- **Task 7 — Manage Subscription screen.** `UserProfile` (+clamp) +
  `UserRepository` + `UserProfileCubit` + `ManageSubscriptionScreen` (states
  A–F, pinned CTA, skeleton, error reuse) + `_AccountHubLine` (quiet trailing,
  ≥44dp) + `/account` route + `StoreLinks` + `intl` date + `CallUsage` clamp.
- **F17 — pending approval.** `SubscriptionPendingApproval` state; bloc emits it
  on `PurchaseStatus.pending`; paywall renders it dismissible.
- **Task 8 — AC3/AC4.** AC3 call-icon inert at 0 calls (free→paywall, paid→no-op,
  no round-trip) + 2 tests; AC4 BOC matrix verified.

**Declared deviations:**
1. **Legal footer links** — no client Terms/Privacy URL config exists (Story
   10-1 owns the legal pages); the paywall ships its legal as flat non-linked
   text. We link Terms/Privacy to the SAME real domain the consent screen
   already uses (`https://survivethe.talk/{terms,privacy}`), NOT a placeholder.
2. **State C ("Access until")** — `/user/profile` exposes no auto-renew flag
   (design R3), so the paid view always reads `Renews {date}`.
3. **Live price** — the price line uses the static `$1.99 per week` (design
   allows it) rather than loading `ProductDetails.price`.
4. **Google webhook security** — the interim secret `?token=` gate is
   implemented; `GOOGLE_PUBSUB_AUDIENCE` (OIDC) is reserved for prod hardening.
5. **Manage surface = a paid-only DRAWER, not a full-screen page (2026-06-18
   pivot, REVERSES D1's "real screen" ruling on the CLIENT side only).** After
   three on-device design passes Walid judged the full-page Manage screen
   over-engineered for its little content. The route-pushed
   `ManageSubscriptionScreen` + `/account` route + its 25 tests were DELETED and
   replaced by `manage_sheet.dart` — a paid-only white bottom-sheet **retention
   drawer** reusing the paywall scaffold (opens on value, ends on a quiet,
   de-emphasized "Manage subscription" handoff whose caption literally says
   "cancel"). Designed by a 7-agent retention/sales design pass + reviewed by a
   3-dimension adversarial workflow. The drawer carries NO Restore and NO
   `SubscriptionBloc` (a recognized member has nothing to restore). The hub
   `Account` line now shares ONE row with the difficulty line — Account LEADING,
   **paid-users only** (gated on `!usage.isFree`); free users see no Account line
   (their surface is the paywall). **Server side of 8.3 (migration 015, tier
   enforcement, `/user/profile`, webhooks, expiry sweep) is UNCHANGED.**
6. **Restore relocated to the paywall (REVERSES the 2026-06-18 "Restore moved
   OUT of the paywall" change).** Restore now lives on the `PaywallSheet`, in the
   slot the removed "Not now" dismiss button occupied (the sheet still dismisses
   via swipe / scrim / system-back). This is the correct Apple 3.1.1 home: a
   free-SEEN returning payer (reinstall / new device) lands on the paywall, never
   on the paid-only Manage drawer, so Restore must be reachable there. The
   paywall's previously-commented `_kRestore` is live again; `Subscription
   RestoreEmpty` renders a neutral "Nothing to restore." (no fake success, F16).

### File List

**New (server):** `db/migrations/015_tier_at_call_and_subscription_events.sql`,
`api/routes_user.py`, `api/routes_subscription_webhooks.py`,
`tests/test_user_profile.py`, `tests/test_subscription_webhooks.py`

**Modified (server):** `db/queries.py`, `api/usage.py`, `api/routes_calls.py`,
`api/app.py`, `billing/google_validator.py`, `billing/revalidation.py`,
`billing/apple_validator.py`, `billing/__init__.py`, `models/schemas.py`,
`config.py`, `tests/test_migrations.py`, `tests/test_call_usage.py`,
`tests/test_calls.py`, `tests/test_billing.py`, `tests/test_subscription.py`,
`tests/test_routes_debriefs.py`

**New (client):** `features/subscription/models/user_profile.dart`,
`features/subscription/repositories/user_repository.dart`,
`features/subscription/bloc/user_profile_cubit.dart`,
`features/subscription/services/purchase_sync_service.dart`,
`features/subscription/services/store_links.dart`,
`features/subscription/views/manage_subscription_screen.dart`, +
`test/features/subscription/{models/user_profile_test, services/store_links_test,
services/purchase_sync_service_test, views/manage_subscription_screen_test}.dart`

**Modified (client):** `lib/main.dart`, `lib/app/app.dart`, `lib/app/router.dart`,
`features/subscription/bloc/subscription_bloc.dart`,
`features/subscription/bloc/subscription_state.dart`,
`features/paywall/views/paywall_sheet.dart`,
`features/scenarios/models/call_usage.dart`,
`features/scenarios/views/scenario_list_screen.dart`, `pubspec.yaml`,
`pubspec.lock`, `test/features/scenarios/views/scenario_list_screen_test.dart`,
`test/features/paywall/views/paywall_sheet_test.dart`,
`test/features/subscription/bloc/subscription_bloc_test.dart`

**Client-UI rewrite (2026-06-18 pivot — see Declared deviations #5/#6):**
- **NEW:** `features/subscription/views/manage_sheet.dart` + `test/features/subscription/views/manage_sheet_test.dart` (the retention drawer, 11 tests).
- **DELETED:** `features/subscription/views/manage_subscription_screen.dart` + `test/.../manage_subscription_screen_test.dart` (the full-page screen + its 25 tests).
- **MODIFIED:** `features/subscription/services/store_links.dart` (+`isApplePlatform` getter for the drawer caption); `features/paywall/views/paywall_sheet.dart` (Restore back in, replacing "Not now"); `features/scenarios/views/scenario_list_screen.dart` (Account+difficulty share one row, Account paid-only leading); `lib/app/router.dart` (removed the `/account` route + `AppRoutes.account` + its 6 subscription imports). `scenario_list_screen_test.dart` (+3 hub-row tests) + `paywall_sheet_test.dart` (Restore-on-paywall tests).
- KEPT (still used by the drawer): `user_profile.dart`, `user_repository.dart`, `user_profile_cubit.dart`, `purchase_sync_service.dart`. **Server side of 8.3 untouched.** Gates re-green: `flutter analyze` clean, `flutter test` → 636 passed.

### Change Log

- 2026-06-18 — dev-story: implemented Tasks 0–9 (server full tier enforcement +
  `/user/profile` + expiry/webhooks; client Manage Subscription screen + hub
  entry + app-lifetime purchase listener + F17). Gates green (server pytest 994,
  client flutter 635, ruff + analyze clean). Status → review. Task 10 (deploy +
  server Smoke Test Gate + snapshot refresh) owed; on-device gate deferred.
- 2026-06-18 — deployed + server Smoke Test Gate PASSED (commit f6d69ee, CI
  27756245681; migration 015 live; 8/8 server boxes filled; prod_snapshot
  refreshed). Only `/bmad-code-review` owed for review→done.
- 2026-06-18 — Walid design feedback: (1) removed Restore from the paywall
  (lives only on the Subscription screen now); (2) "Let's go" + "Subscribe"
  CTAs → StadiumBorder pills (match "Pick up"); (3) **Manage Subscription screen
  REDESIGNED** via a multi-agent critical design pass (3 concepts → 4 adversarial
  critics → synthesis) into a hero "survival-ring" (free = remaining/cap usage
  ring + count; paid = full "Premium" membership medallion; 700ms entrance sweep,
  reduce-motion-gated) + a fixed centered-pill Restore. Zero new tokens/copy.
  Binding design doc amended. Gates re-green: analyze clean + flutter 641.
- 2026-06-18 — Walid action-block feedback (2nd design pass: 3 treatments → 3
  critics → synthesis): (1) Restore moved BELOW the primary CTA (quieter
  hierarchy, still reachable every state); (2) dropped the "Auto-renewable.
  Cancel anytime." footer line (compliance verdict: the paywall retains the
  disclosure at point-of-sale, so the status screen has no separate duty);
  (3) paid "Manage subscription" → quiet neutral-OUTLINED pill (1px
  textSecondary border, textPrimary label), accent FILL reserved for the free
  "Subscribe" conversion CTA (two-ink intact). Gates re-green: analyze clean +
  flutter 644.
- 2026-06-18 — Walid follow-up: moved "Restore purchases" back ABOVE the primary
  CTA (cleaner reading order). Pinned block = Restore → [msg] → CTA → Terms·
  Privacy. Tests flipped to assert Restore above the CTA (both tiers); flutter
  644, analyze clean.
- 2026-06-18 — Walid Pixel 9 malaise feedback (3rd design pass: UX + UI +
  copywriting, 11 agents): (1) hero now CENTERED in the vertical slack
  (LayoutBuilder + ConstrainedBox(minHeight) + IntrinsicHeight + Expanded(hero)
  — balances on tall, scrolls on SE; deleted _kHeroTitleGap); (2) the confusing
  "0" reframed — at 0 the caption reads "You have used your N free calls" (calm
  factual fact), ring semantics state-aware, Subscribe is the sole forward path
  (no sell line, no bore label); (3) spacing/sizing — CTA 48→64
  (hangUpButtonSize), Restore→CTA 24, CTA→legal 16, bottom inset 16. Zero new
  tokens; 1 new in-voice copy string. +4 tests (0-state copy, 0-state overflow,
  tall-screen balance, CTA height 64); flutter 648, analyze clean.
- 2026-06-18 — Walid PIVOT (Declared deviations #5/#6): the full-page Manage
  screen was judged over-engineered → REWRITTEN as a paid-only white retention
  DRAWER (`manage_sheet.dart`, reuses the paywall scaffold; opens on value, ends
  on a quiet de-emphasized "Manage subscription" handoff with a "cancel"
  caption; NO Restore, NO SubscriptionBloc). Deleted the full-page screen +
  `/account` route + 25 tests. Restore moved back ONTO the paywall (replacing
  "Not now"; the correct Apple 3.1.1 home). Hub `Account` line now shares one row
  with difficulty (Account LEADING, paid-only via `!usage.isFree`); free users
  see no Account line. Designed via a 7-agent retention design pass + a
  3-dimension adversarial review. Server side untouched. Gates re-green: analyze
  clean, flutter test 636. Net tests: −25 (old screen) +11 (drawer) +3 (hub) +2
  (paywall Restore) −2 (obsolete paywall).
- 2026-06-18 — Walid paywall tweak: Restore moved ABOVE the "Let's go" CTA;
  "Restore purchases" typography shrunk to caption (small/quiet) and the primary
  CTA height raised 48→64 (prominent). The empty-restore state now swaps the
  Restore button IN PLACE for a NON-tappable "Nothing to restore." info line of
  identical fixed height (`_kRestoreSlotHeight`) — no reflow of the CTA/legal;
  it resets to the tappable button when the sheet is reopened (fresh bloc).
  analyze clean, flutter test 638.
- 2026-06-19 — Walid manage-drawer tweak: "Manage subscription" became a
  clearly-tappable OUTLINED pill (same StadiumBorder / 64h shape as the paywall
  CTA, border-only — no accent fill, two-ink intact) with its "Update or cancel
  in the {store}." caption centered directly BELOW it (the CTA→legal pattern,
  replacing the borderless left-aligned text row); "Premium" enlarged 18→24 for
  hero presence. OutlinedButton carries its own button+label semantics. analyze
  clean, flutter test 638.

---

## Review Findings (code review 2026-06-19)

_Adversarial multi-agent review (8 parallel hunters → dedup → per-finding adversarial verification, 49 agents). 28 raw → 18 canonical → 17 survived, 1 dismissed. Diff = `f8633cf..HEAD` (all of Story 8.3). Reviewed with a different model/agent than the implementer. The webhook/payments cluster is **latent** today (Apple/Google live billing is store-deferred per 8.1 D4 + Story 10-4), but several are **deterministic** the moment billing goes live (e.g. F5 fires on the first Android cancel; F3 on the first weekly renewal)._

**✅ Resolution (2026-06-19, Walid chose "fix F3 now + fix all patches").** F3 (decision) + the 6 patches (F1/F4/F5/F6/F13/F14) all APPLIED + the F18 test gap closed; the 8 defers recorded in `deferred-work.md`; F11 dismissed. Summary of fixes:
- **F3** — migration 016 (`purchases.original_transaction_id`); `ValidationResult` + `AppleNotification` carry `original_transaction_id`; both Apple validators capture it; `/verify` + revalidation stamp it; webhook resolves by `get_purchase_by_original_transaction_id` (falls back to `transaction_id` for legacy rows); misleading `get_purchase_by_transaction_id` docstring corrected.
- **F1** (+F2/F17/F18) — `record_subscription_event` now returns `new`/`replay_unprocessed`/`replay_processed`; a processing failure returns **500** (store retries) instead of swallowing to 200, and a retry RE-DRIVES the unprocessed event; module + route docstrings rewritten.
- **F4** — Apple `EXPIRED`/`REFUND`/`REVOKE` downgrade now CONDITIONAL via new expiry-aware `user_has_active_entitlement(..., exclude_purchase_id=...)` (REFUND/REVOKE also mark the row invalid); won't clobber a user entitled via another valid+future purchase.
- **F5** — Google `SUBSCRIPTION_STATE_CANCELED`-with-future-expiry routed through the F11 guard (keep paid until expiry; reject once past; reject if no expiry).
- **F14** — Apple `DID_RENEW` + Google `valid` grants folded into one `BEGIN IMMEDIATE`.
- **F13** — boot-time min-length validator on `GOOGLE_PUBSUB_VERIFICATION_TOKEN` (production, ≥24 chars, empty still boots).
- **F6** — `_AccountHubLine` wrapped in `MergeSemantics` + `Semantics(button: true)`.

Gates GREEN post-fix: server `ruff check`/`ruff format` clean + **pytest 1006** (+12); client `flutter analyze` "No issues found!" + **flutter test 639** (+1). NEW migration 016 → refresh + commit `prod_snapshot.sqlite` at deploy time (post-deploy step, per the migration rule). **Story STAYS `review`**: code review complete, but the on-device IAP/live-webhook gate is DEFERRED (8.1 D4 store config + Story 10-4), same posture as 8.1 — the `review → done` flip awaits that gate (or Walid's explicit waiver).

### Decision-needed

- [x] [Review][Decision] **Apple resolves users by the per-renewal `transactionId`, so real renewals never re-stamp expiry and the sweep later downgrades a paying subscriber (F3, HIGH)** — `_process_apple_notification` resolves via `get_purchase_by_transaction_id(notif.transaction_id)`, but StoreKit2/ASSN V2 mints a NEW `transactionId` each auto-renewal; only `originalTransactionId` is renewal-stable and it is never stored or read anywhere. A genuine `DID_RENEW` finds no purchase row → the re-stamp branch is unreachable → `expires_at` stays frozen at period-1 → `downgrade_expired_entitlements` flips a renewed, paying customer to free. The same miss makes a `REFUND`/`REVOKE` on a renewed sub a no-op. The fix crosses a NEW migration (add `purchases.original_transaction_id`) + `ValidationResult`/`AppleNotification` shape change + resolver change. **DECISION: fix now, or formally defer as a documented pre-Apple-launch blocker?** [`server/api/routes_subscription_webhooks.py:79-108`, `server/billing/apple_validator.py:294-315`, `server/db/queries.py:754-770`]

### Patch (fix without further input)

- [x] [Review][Patch] **Webhook dedup row is committed on RECEIPT, not on successful PROCESSING — a transient processing failure permanently drops the lifecycle event (F1, HIGH)** — `record_subscription_event` INSERTs+COMMITs the dedup row before `_process_*` runs; on a raise the route still returns 200 and the row persists with `processed_at=NULL`, so a store retry of the same id dedups to a no-op and the tier flip is lost forever. Fold the dedup insert + side effects + `mark_processed` into ONE `BEGIN IMMEDIATE` (roll back on failure so the event stays re-deliverable), OR re-drive rows where `processed_at IS NULL` on replay. Resolves F2 (the `processed_at` "recoverable" framing) and F17 (Google `unreachable` RTDN marked processed and lost) in the same fix. Add the F18 regression test. [`server/api/routes_subscription_webhooks.py:159-179,307-322`, `server/db/queries.py:773-811`]
- [x] [Review][Patch] **Apple `EXPIRED`/`REFUND`/`REVOKE` downgrade is unconditional — clobbers a user still entitled via another valid+future purchase (F4, HIGH)** — the `_APPLE_DOWNGRADE_TYPES` branch calls `update_user_tier(free)` with no `still_entitled` guard, asymmetric with the Google webhook + both sweeps. Mirror Google: mark the lapsing purchase, then downgrade only if no OTHER currently-entitling purchase remains, under one `BEGIN IMMEDIATE`. NOTE: `count_user_valid_purchases` is NOT expiry-aware — add/borrow an `expires_at > now` check (mirror `get_users_with_expired_entitlement`) so the lapsing row doesn't count itself. [`server/api/routes_subscription_webhooks.py:106-108`]
- [x] [Review][Patch] **Google `CANCELED`-but-not-yet-expired subscription is downgraded to free immediately — breaks AC6 and Apple-parity (F5, HIGH)** — `_ACTIVE_STATES` omits `SUBSCRIPTION_STATE_CANCELED` (auto-renew off, still inside the paid window), so `validate_google` returns `invalid` and the RTDN flips the user to free weeks early, while the Apple side keeps paid until expiry. Route `CANCELED` through the F11 expiry guard (keep paid while `expiryTime > now`, reject once past). Add a billing test for CANCELED-future (valid) + CANCELED-past (invalid). [`server/billing/google_validator.py:38-40,212-237`]
- [x] [Review][Patch] **Apple `DID_RENEW` + Google `valid` grants write purchase + tier in two separate commits (non-atomic) (F14, LOW)** — a crash between commits leaves an inconsistent state; the rest of the module folds the pair into one `BEGIN IMMEDIATE`. Both helpers already accept `commit=False` — mechanical wrap. [`server/api/routes_subscription_webhooks.py:93-105,220-230`]
- [x] [Review][Patch] **`GOOGLE_PUBSUB_VERIFICATION_TOKEN` has no boot-time min-length/strength validator unlike `jwt_secret` (F13, LOW)** — the token is the entire authz boundary for the Google webhook; add a `@field_validator` mirroring `jwt_secret` (only enforce when non-empty + production). [`server/config.py:161`]
- [x] [Review][Patch] **Paid `Account` hub line is a bare `GestureDetector` with no button semantics (F6, LOW)** — reachable/activatable but missing the explicit button ROLE, deviating from the project's own `scenario_card` pattern (`MergeSemantics` + `Semantics(button:true)`). Wrap `_AccountHubLine` (the new 8.3 surface). [`client/lib/features/scenarios/views/scenario_list_screen.dart:522-557`]
- [x] [Review][Patch] **Test `test_google_processing_error_still_acks_200` gives false confidence — never proves a FAILED event is re-processed (F18, MEDIUM, test)** — add a test that re-POSTs the same `messageId` after a transient failure and asserts re-processing (will fail until F1 is fixed — that is the point). Bundled with the F1 fix. [`server/tests/test_subscription_webhooks.py`]

### Deferred (real, but not actionable in this story)

- [x] [Review][Defer] **Webhook inherits the unresolved buyer-binding gap — no `appAccountToken`/`obfuscatedAccountId` check (F15, MEDIUM)** [`server/api/routes_subscription_webhooks.py:90,207`] — deferred; real fix spans `/verify` + the device IAP flow + storage (a future story), reachable only under a shared/leaked-artifact precondition, bounded blast radius (the artifact-sharer). Inherited from 8.1's documented `PURCHASE_CONFLICT` deferral.
- [x] [Review][Defer] **Manage drawer renders "Active until {past date}" during the sweep race + cannot distinguish cancelled-future from renews-future (F7, LOW)** [`client/lib/features/subscription/views/manage_sheet.dart:304-317`] — deferred; cosmetic/trust only, proper fix needs a server `auto_renew`/`cancelled` flag on `UserProfileOut`. Bundle with the on-device billing gate.
- [x] [Review][Defer] **Google RTDN secret travels in the URL query string `?token=` instead of a Pub/Sub OIDC bearer (F12, LOW)** [`server/api/routes_subscription_webhooks.py:263`, `server/config.py:162`] — deferred pre-prod hardening; no log sink enabled today, forgery re-validates to a no-op, webhook unwired until store config. `google_pubsub_audience` is already reserved for the OIDC upgrade.
- [x] [Review][Defer] **Google `unreachable` RTDN is marked processed and not retried (F17, LOW)** [`server/api/routes_subscription_webhooks.py:259,319`] — same family as F1; an early-revoke RTDN during a Google API outage is lost, bounded by the expiry sweep to the remaining paid period. Addressed if F1's re-drive is implemented.
- [x] [Review][Defer] **Card-tap/briefing path lacks the AC3 proactive 0-calls inert guard (F8, LOW)** [`client/lib/features/scenarios/views/scenario_list_screen.dart:494-510`] — deferred; AC3 scopes the inert affordance to the call ICON (satisfied), the whole-card tap is intentionally tier-invisible browse, server 403 backstops it. Post-MVP UX polish.
- [x] [Review][Defer] **Dual purchaseStream listeners fire a redundant second `/subscription/verify` + `completePurchase` per transaction (F9, LOW)** [`client/lib/features/subscription/services/purchase_sync_service.dart:51-94`, `bloc/subscription_bloc.dart:136-173`] — deferred; fully absorbed by the server's idempotent verify (UNIQUE token + `_respond_existing`) and swallowed double-complete. Accepted coupling, already documented in-code.
- [x] [Review][Defer] **`onEntitlementChanged` refresh dropped when the hub is not in `ScenariosLoaded` (F10, LOW)** [`client/lib/features/scenarios/views/scenario_list_screen.dart:211-232`] — deferred; bounded + self-heals (the next `/scenarios` load that mounts the hub carries the correct tier). Optional latch hardening.
- [x] [Review][Defer] **Google webhook 403 on a token mismatch triggers unbounded Pub/Sub redelivery (F16, LOW)** [`server/api/routes_subscription_webhooks.py:270-290`] — deferred; intended security posture (reject, don't accept unauthenticated). Ops/observability item — verify the push `?token=` at store-wiring + alert on a sustained 403/503 warning rate. Entitlement correctness independently covered by the expiry sweep.

### Dismissed (1)

- **F11 — `UserProfile.fromJson` unguarded hard casts (LOW)** — dismissed (2/2 verifiers false-positive): the sole producer is the Pydantic `UserProfileOut` contract (every field present, ints never decode as double), and `UserProfileCubit.load()`'s blanket catch contains any error to the inline "Couldn't load your details." retry. No reachable production crash; optional defensive-parsing nicety only.
