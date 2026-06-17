# Story 8.1: Integrate StoreKit 2 and Google Play Billing

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to purchase a weekly subscription through the native app store payment system,
so that I can unlock all scenarios with a seamless, trusted payment experience.

> **Epic 8 opener.** This is the first story of Epic 8 (Monetization). It builds the **purchase plumbing + server-side validation + tier flip** ONLY. It does **NOT** build the real paywall UI (Story 8.2) or full tier enforcement / subscription-management / cancellation handling (Story 8.3). Scope boundaries are spelled out per-task below.

## Acceptance Criteria

1. **AC1 — Single weekly product, both platforms.** StoreKit 2 (iOS) and Google Play Billing (Android) are integrated through the official `in_app_purchase` Flutter plugin with **one** auto-renewable weekly subscription product priced at **$1.99/week**. The app loads the product from the store, presents the native payment sheet, and completes the transaction. _(epics.md:1410–1412, FR28)_

2. **AC2 — Successful purchase flips tier to `paid`.** When the native payment flow completes successfully, the client sends the platform verification artifact (iOS: the StoreKit 2 signed-transaction JWS; Android: the `purchaseToken`) to the server. The server validates it and sets `users.tier = 'paid'`, granting immediate access (optimistic access per **NFR26**). _(epics.md:1414–1417)_

3. **AC3 — Failed validation reverts to `free`, no data lost.** If validation ultimately fails, the user's tier is reverted to `free` and reflected on the next API call. The user keeps access to debriefs created during paid-tier calls (debriefs are not tier-gated). _(epics.md:1419–1422)_

4. **AC4 — Zero payment data handled directly (NFR11).** No credit-card numbers, no payment tokens, no cardholder data are ever stored or seen by our server. Only the store **verification artifacts** (JWS / purchaseToken — which are NOT payment instruments) are received, used for validation, and optionally persisted for audit/renewal checks. No PCI-DSS scope. _(epics.md:1424–1426, prd.md:503)_

5. **AC5 — Gates green.** `cd client && flutter analyze` prints **"No issues found!"** and `flutter test` is all-green; `cd server && python -m ruff check . && python -m ruff format --check . && python -m pytest` all pass (including `test_migrations.py` replay against the prod snapshot). _(epics.md:1428–1430)_

---

## ✅ Pre-Dev Decisions — ALL RESOLVED (Walid confirmed the recommended defaults, 2026-06-16)

This story carried genuine design forks. **Walid confirmed "prends tes recos par défaut" on 2026-06-16 → every recommended option below is LOCKED**, and all are already baked into the Tasks. No open forks remain; the dev agent proceeds on the defaults as written. (D1 was already settled by the architecture.)

- **D1 — Library: native `in_app_purchase` + our own server validation (NOT RevenueCat). ✅ SETTLED.**
  Architecture lists "Apple StoreKit 2" and "Google Play Billing" as the integrations (architecture.md:47, :445–446); NFR11 says payment is "delegated entirely to StoreKit 2 / Google Play Billing." RevenueCat appears nowhere in the planning artifacts and would insert a third-party receipt validator. → Use the official `in_app_purchase` ^3.3.0 plugin (iOS uses **StoreKit 2 by default**; Android uses Google Play Billing) + first-party server validation.

- **D2 — Validation timing (the NFR26 tension). ✅ CONFIRMED (Walid 2026-06-16) → synchronous validate-then-flip + optimistic fallback only when the validator is unreachable.**
  NFR26 reads literally as "grant paid **immediately**, validate **async**, revoke if it fails." A pure-optimistic flip on an *unvalidated* receipt is a fraud window: a forged artifact buys up to the paid daily call-cap (3 calls ≈ $0.15 of API abuse) before the async check reverts it.
  **LOCKED (baked in): synchronous validation in the happy path.** Validate against Apple/Google *inside* the request (~1–4 s); flip `tier='paid'` only on a **valid** result. Fall back to **optimistic grant + `validation_status='pending'` + background re-check** ONLY when the validator is *unreachable* (Apple/Google timeout/5xx) — this preserves NFR26's real intent (never permanently block a paying user on a validator outage) while closing the fraud window in the normal case. AC2/AC3/AC4 are all satisfied either way.
  **Alternative:** literal NFR26 — always flip first, always validate in the background. Simpler request path, wider abuse window.

- **D3 — Tier-transition call-count bug / `users.tier_changed_at`. ✅ CONFIRMED (Walid 2026-06-16) → add the column now, defer the counting rework to 8.3.**
  Known deferred bug (deferred-work.md:401–403): free-tier call counting is **lifetime**, so a user who goes free→paid→free is hard-capped at 0 forever (their paid-era calls count against the free lifetime cap). deferred-work flags this for "Epic 8 — the moment a user can leave free tier."
  **LOCKED (baked in): add the `users.tier_changed_at` column in migration 014 now and stamp it on every tier flip, but DEFER the call-counting rework to Story 8.3.** Rationale: in 8.1 the only paid→free path is a *validation failure* (effectively fraud), where a 0-cap is acceptable; legitimate downgrades (cancellation) arrive in 8.3, which owns the counting fix. Adding the column now avoids a second migration.
  **Alternative:** do the full counting rework here (scope creep), or add nothing now (a second migration in 8.3).

- **D4 — Store product configuration is Walid-owned and BLOCKS the live smoke gate. ✅ CONFIRMED (Walid 2026-06-16) → product ID `stt_weekly_199` LOCKED; store setup remains Walid's action and still blocks the on-device gate.**
  The actual products must be created in **App Store Connect** (iOS) and **Google Play Console** (Android) — both require Walid's developer accounts, a paid Apple Developer membership, an uploaded build, and sandbox/license-test accounts. The code uses the shared constant **`stt_weekly_199`** (lowercase, store-portable) for both `IAP_PRODUCT_ID` (server) and `kIapWeeklyProductId` (client) — the store products MUST be created with this exact ID. Until the products exist + are in a testable state, the on-device purchase smoke gate cannot run. iOS additionally can't be device-validated until Story 10-4 (no iOS test pipeline yet — `project_ios_test_pipeline_deferred.md`).

---

## Tasks / Subtasks

### A. Server — schema & query layer

- [x] **Task A1 — Migration `014_subscriptions.sql` (AC2, AC3, AC4; D3).**
  - [x] Create `server/db/migrations/014_subscriptions.sql` (next free number — confirmed 013 is the latest).
  - [x] `ALTER TABLE users ADD COLUMN tier_changed_at TEXT;` — nullable, ISO-8601 UTC, stamped on every tier flip (D3). **No table rebuild / no PRAGMA dance needed** — `ADD COLUMN` is safe (contrast migration 003 which rebuilt for a CHECK change).
  - [x] Create the audit table:
        ```sql
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL CHECK(platform IN ('ios','android')),
            product_id TEXT NOT NULL,
            verification_token TEXT NOT NULL,     -- JWS (iOS) / purchaseToken (Android); a store artifact, NOT payment data (NFR11)
            transaction_id TEXT,                  -- Apple transactionId / Google orderId, once known
            validation_status TEXT NOT NULL DEFAULT 'pending'
                CHECK(validation_status IN ('pending','valid','invalid')),
            expires_at TEXT,                      -- subscription expiry from the validation response
            created_at TEXT NOT NULL,
            validated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id);
        ```
  - [x] Keep it idempotent (`IF NOT EXISTS`) — the runner replays by lexical filename order and records applied versions in `schema_migrations` (`db/database.py:run_migrations`).
  - [x] **NFR11 note in the migration header comment:** `verification_token` stores a store verification artifact (JWS / purchaseToken), never a card number or payment token.
  - [x] After writing: `tests/test_migrations.py` stays green — added `test_migration_014_subscriptions` (column nullability + CHECK + index) and the prod-snapshot replay passes (7/7). **Snapshot refresh DEFERRED to post-deploy** (declared deviation #6): migration 014 replays on TOP of the pre-014 snapshot exactly as it will on prod, so the test gate validates against the real prod shape now; the snapshot only gains 014 after it ships + the fixture is re-pulled — the same post-deploy pattern as 011/012/013 (documented in `test_migrations.py`).

- [x] **Task A2 — Query functions in `server/db/queries.py` (AC2, AC3; D3).** Follow the existing `update_user_jwt_hash` pattern exactly (queries.py:50–59 — async, takes an open `aiosqlite.Connection`, commits before returning, Architecture Boundary 4: NO raw SQL in routes).
  - [x] `async def update_user_tier(db, user_id: int, tier: str, *, tier_changed_at: str) -> None` → `UPDATE users SET tier = ?, tier_changed_at = ? WHERE id = ?`. (Stamps D3's column on every flip.)
  - [x] `async def insert_purchase(db, *, user_id, platform, product_id, verification_token, created_at) -> int` (returns id; assert `lastrowid is not None` like `insert_user`).
  - [x] `async def update_purchase_validation(db, purchase_id: int, *, validation_status, transaction_id, expires_at, validated_at) -> None`.
  - [x] `async def get_latest_purchase_by_token(db, verification_token: str) -> aiosqlite.Row | None` — idempotency guard so re-POSTing the same artifact doesn't double-insert. (Also added `get_pending_purchases` for the C2 sweep.)

### B. Server — validation module

- [x] **Task B1 — New `server/billing/` package (mirrors the `auth/` package layout).** Keep the public interface library-agnostic so the internal validator lib is swappable.
  - [x] `billing/models.py` — a `ValidationResult` dataclass: `valid: bool`, `status: Literal['valid','invalid','unreachable']`, `transaction_id: str | None`, `expires_at: str | None`, `reason: str | None`. The `'unreachable'` status is what triggers D2's optimistic fallback. (Also added `BillingConfigError` → 503 on missing config.)
  - [x] `billing/apple_validator.py` — `validate_apple(...)` via Apple's `app-store-server-library` `SignedDataVerifier` (offline JWS x5c verification, online checks OFF). Apple Root CA-G3 pinned + fingerprint-checked in `billing/apple_roots.py` (the lib does NOT bundle roots — declared deviation vs the spec note). Sandbox/Production resolved from the unverified payload's `environment`; product/expiry/revocation asserted. Added `app_apple_id` kwarg (lib requires it for PRODUCTION).
  - [x] `billing/google_validator.py` — `validate_google(...)` against the **subscriptionsv2** endpoint. **Declared deviation #1: uses `pyjwt` (RS256 service-account assertion) + `httpx`, NOT `google-auth`** — google-auth's default transport is the sync `requests` lib (not installed) and forces a thread hop; pyjwt+httpx keep the path fully async and add zero deps. `ACTIVE`/`IN_GRACE_PERIOD` → valid; transport/5xx → `unreachable`; token-exchange 4xx / 401-403 → `BillingConfigError`.
  - [x] `billing/__init__.py` — exports the two validators + `ValidationResult` + `BillingConfigError`.
  - [x] Added ONLY `app-store-server-library` via `uv add` (pyproject + uv.lock updated, installs clean; `import billing` verified, full pytest green). google-auth intentionally NOT added (deviation #1).

- [x] **Task B2 — Config fields in `server/config.py` (AC2, AC4).** Follow the optional-field pattern (empty-string default so a missing secret degrades cleanly rather than failing boot — like `cartesia_api_key`):
  - [x] `apple_bundle_id: str = ""` (`APPLE_BUNDLE_ID`) — must match the iOS bundle identifier.
  - [x] App Store Connect API-key fields: `apple_issuer_id`, `apple_key_id`, `apple_private_key_p8` (all `str = ""`, reserved for the 8.3 online-revocation path). Also added `apple_app_apple_id: int | None` — the lib requires the numeric app id to verify a PRODUCTION transaction (declared deviation #3; sandbox doesn't need it).
  - [x] `google_play_package_name: str = ""` (`GOOGLE_PLAY_PACKAGE_NAME`) — must equal the Android `applicationId` (`com.surviveTheTalk.client`).
  - [x] `google_service_account_json: str = ""` (`GOOGLE_SERVICE_ACCOUNT_JSON`, base64-encoded) — `field_validator` base64-decodes + `json.loads` to fail loud on a malformed value (only when non-empty).
  - [x] `iap_product_id: str = "stt_weekly_199"` (`IAP_PRODUCT_ID`) — the expected product id, shared with the client constant (D4).

### C. Server — endpoint

- [x] **Task C1 — `POST /subscription/verify` in new `server/api/routes_subscription.py` (AC2, AC3, AC4; D2).**
  - [x] `router = APIRouter(prefix="/subscription", tags=["subscription"], dependencies=[AUTH_DEPENDENCY])` — reuse the auth dependency from `api/middleware.py:103` (resolves `request.state.user_id`; 401 `AUTH_UNAUTHORIZED` on a bad/absent JWT, identical to every other protected route).
  - [x] Request model `SubscriptionVerifyIn` (put in `models/schemas.py` next to the other Pydantic models): `platform: Literal['ios','android']`, `product_id: str`, `verification_data: str`.
  - [x] Handler flow (recommended D2 — synchronous-validate-then-flip with unreachable fallback): + a 503 `SUBSCRIPTION_UNAVAILABLE` branch on `BillingConfigError` (missing store config ≠ outage ≠ fraud → never an optimistic grant).
        1. `user_id = request.state.user_id`.
        2. Idempotency: if `get_latest_purchase_by_token` already exists and is `'valid'`, return the current tier without re-validating.
        3. `insert_purchase(..., created_at=now_iso())` with `validation_status='pending'`.
        4. Validate via `validate_apple` / `validate_google` (branch on `platform`), passing `settings.iap_product_id` as `expected_product_id`.
        5. If `valid` → `update_user_tier(db, user_id, 'paid', tier_changed_at=now_iso())` + `update_purchase_validation(... 'valid' ...)`.
        6. If `invalid` → leave tier untouched (do NOT flip), mark purchase `'invalid'`, return HTTP 402/400 with `{"code": "PURCHASE_INVALID", "message": ...}` (use the `HTTPException(detail={"code","message"})` convention — `api/app.py:202` turns it into the `{error}` envelope).
        7. If `unreachable` (D2 fallback) → optimistic: `update_user_tier(... 'paid' ...)`, keep purchase `'pending'`, and schedule a background re-check (see Task C2). Return success.
  - [x] Response model `SubscriptionVerifyOut`: `tier: Literal['free','paid']`, `product_id: str`, `expires_at: str | None`, `status: str`. Wrap with `ok(...)` from `api/responses.py:23`.
  - [x] Register the router in `api/app.py`: `app.include_router(subscription_router)`.

- [x] **Task C2 — Background re-validation for `'pending'` purchases (D2 fallback only).** Implemented `billing/revalidation.py::revalidate_pending_purchases` (mirrors `db/janitor.py`) + a second lifespan task `_subscription_revalidation_loop` on the SHARED `stop_event` (5-min cadence, same fail-soft backoff). On a definitive `invalid` it flips the user back to `'free'` (stamps `tier_changed_at`) + marks the row `'invalid'`; `unreachable`/config-absent rows stay `'pending'` for the next sweep.

### D. Server — tests

- [x] **Task D1 — `server/tests/test_subscription.py` (AC2, AC3, AC4, AC5).** Use `conftest.py` fixtures (`client`, `test_db_path`, the `register_user` / `issue_token` helpers). Validators mocked (patched at `api.routes_subscription.*` / `billing.revalidation.*` — never hit real stores). Also added `tests/test_billing.py` (validator guards + Google HTTP branching with a fake httpx client) + config tests. Cover:
  - [x] No JWT → 401 `AUTH_UNAUTHORIZED`.
  - [x] Valid iOS JWS → 200, `users.tier == 'paid'`, `tier_changed_at` set, a `purchases` row `'valid'`.
  - [x] Valid Android token → 200, tier flipped.
  - [x] Invalid artifact → tier stays `'free'`, purchase `'invalid'`, `{error: {code: PURCHASE_INVALID}}` envelope.
  - [x] Validator `unreachable` → tier optimistically `'paid'`, purchase `'pending'` (D2 fallback). + `BillingConfigError` → 503.
  - [x] Idempotent re-POST of the same valid token → no double flip, no duplicate `'valid'` row.
  - [x] Background re-check on a `'pending'`-then-`invalid` row reverts tier to `'free'`; still-`unreachable` stays `'pending'`.
  - [x] `test_migrations.py` stays green (Task A1).

### E. Client — dependency & platform config

- [x] **Task E1 — Add the plugin (AC1).** `client/pubspec.yaml`: added `in_app_purchase: ^3.3.0` (resolved 3.3.0; iOS uses StoreKit 2 by default, Android wraps Google Play Billing). `flutter pub get` clean.
- [x] **Task E2 — Android config (AC1).** Flutter's default `flutter.minSdkVersion` already resolves to 24; pinned explicitly as `minSdk = maxOf(flutter.minSdkVersion, 24)` so the in_app_purchase 3.x floor is encoded at the call site (defensive against future Flutter drift). `applicationId = "com.surviveTheTalk.client"` confirmed (= `GOOGLE_PLAY_PACKAGE_NAME`).
- [x] **Task E3 — iOS config (AC1).** iOS deployment target is already **13.0** in `Runner.xcodeproj` (3 build configs) — satisfies the plugin's >=13.0 requirement, no change needed. **Declared deviation #4: skipped the optional `Configuration.storekit` test file** (only useful on a local Xcode/simulator dev loop, which isn't set up — iOS is gated until Story 10-4) and left the bundle id as `$(PRODUCT_BUNDLE_IDENTIFIER)` (its literal value feeds `APPLE_BUNDLE_ID`, Walid-owned at D4 store setup).

### F. Client — feature implementation (`lib/features/subscription/`)

- [x] **Task F1 — `services/in_app_purchase_service.dart` (AC1).** Thin mockable wrapper: `loadProduct`, `buy` (→`buyNonConsumable`, returns the plugin's bool send-result), `purchaseStream`, `complete`, `isAvailable`. Reads `verificationData.serverVerificationData` (JWS / purchaseToken). Constant `kIapWeeklyProductId = 'stt_weekly_199'` (= `IAP_PRODUCT_ID`).
- [x] **Task F2 — `models/subscription_status.dart` (AC2).** Manual `fromJson` (`tier`, `productId`, `expiresAt`, `status`) + `bool get isPaid`.
- [x] **Task F3 — `repositories/subscription_repository.dart` (AC2).** Takes `ApiClient`; `verifyPurchase(...)` POSTs `/subscription/verify`, extracts `data`, returns `SubscriptionStatus.fromJson`; lets `ApiException` propagate.
- [x] **Task F4 — `bloc/subscription_bloc.dart` + events/states (AC1, AC2, AC3).** Sealed events (`SubscribePressed` + internal `PurchaseUpdated`/`PurchaseTimedOut`) / states (`Initial`/`Loading`/`Purchased`/`Failed(code)`/`Cancelled`). **Declared deviation #2: the purchase stream is subscribed for the bloc's WHOLE lifetime (not per-press)** so a purchase landing after the 15 s window still verifies (closes the "charged but tier never flipped" hole) — the 15 s timeout only changes the UI STATE, never stops listening. `purchased`/`restored` → verify → Purchased; `error`→Failed; `canceled`→Cancelled; always `complete()`. Timeout injectable for tests.

### G. Client — wiring & tier refresh

- [x] **Task G1 — Wire the existing paywall placeholder to drive the purchase (AC1, AC2).** `_PaywallSheetBody` is now a `BlocProvider<SubscriptionBloc>` + `BlocConsumer`: "Subscribe — $1.99/week" `FilledButton` → `SubscribePressed`, a spinner while `SubscriptionLoading`, an inline `AppColors.destructive` error line on `SubscriptionFailed`. Kept minimal (8.2 restyles). `PaywallSheet.show` now returns `Future<bool>` (true on purchase) and gained a `@visibleForTesting debugBlocBuilder` seam so the two internal call sites stay plugin-free in widget tests. Invocation points unchanged.
- [x] **Task G2 — Refresh tier after success (AC2, AC3).** On `SubscriptionPurchased` the sheet pops `true`; BOTH paywall call sites in `scenario_list_screen.dart` (BOC `onPaywallTap` + the `CALL_LIMIT_REACHED` handler) await it and dispatch `LoadScenariosEvent` so the fresh `CallUsage.tier` re-flows from `/scenarios` `meta` (no cached tier; no `GET /user/profile`).

### H. Client — tests

- [x] **Task H1 — `client/test/features/subscription/...` (AC5).** `mocktail` + `bloc_test`; `FlutterSecureStorage.setMockInitialValues({})` in every `setUp`. Cover:
  - [x] `SubscriptionRepository.verifyPurchase` parses the `{data}` envelope → `SubscriptionStatus(isPaid == true)`; posts the right body; propagates `ApiException`.
  - [x] `SubscriptionBloc`: purchased → `[Loading, Purchased]` (+verify+complete); error → `[Loading, Failed]`; cancel → `[Loading, Cancelled]`; verify-`ApiException` → `Failed(code)`; product-unavailable → `Failed`; timeout → `Failed(timeout)`; foreign product id ignored. Mock `InAppPurchaseService`.
  - [x] `SubscriptionStatus.fromJson` happy + missing-optionals + malformed (throws).
  - [x] Updated `paywall_sheet_test.dart` to the new minimal UI (via the `debugBlocBuilder` seam). Full suite: **flutter analyze clean + flutter test 567 passed** (553 → 567).

---

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story touches a server endpoint + a DB migration + a VPS deploy → the gate applies. The **on-device purchase** half is **BLOCKED on D4** (store products + sandbox/license-test accounts; iOS device-validation is gated until Story 10-4). Run the server-side boxes now; mark the on-device purchase boxes **PENDING (Walid store setup)** until the products exist.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->

- [ ] **Happy-path endpoint round-trip.** With a mocked-store fixture or a real sandbox artifact, `POST http://167.235.63.129/subscription/verify` (Bearer JWT) returns the `{data, meta}` envelope with `tier: "paid"`.
  - _Command:_ <!-- curl -sS -X POST -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" -d '{"platform":"android","product_id":"stt_weekly_199","verification_data":"<token>"}' http://167.235.63.129/subscription/verify -->
  - _Expected:_ <!-- 200 + {"data":{"tier":"paid",...}} -->
  - _Actual:_ <!-- paste output -->

- [ ] **Unauth path produces the `{error}` envelope.** No/invalid JWT → 401 `AUTH_UNAUTHORIZED` (canonical error shape, not a raw 500).
  - _Command:_ <!-- curl -sS -X POST http://167.235.63.129/subscription/verify -d '{}' -->
  - _Expected:_ <!-- 401 + {"error":{"code":"AUTH_UNAUTHORIZED",...}} -->
  - _Actual:_ <!-- paste output -->

- [ ] **DB side-effect verified.** After a successful verify, read back prod DB: the user's `tier` is `paid`, `tier_changed_at` is set, and a `purchases` row exists with `validation_status`.
  - _Command:_ <!-- /opt/survive-the-talk/current/server/.venv/bin/python -c 'import sqlite3;c=sqlite3.connect("/opt/survive-the-talk/data/db.sqlite");[print(r) for r in c.execute("SELECT id,tier,tier_changed_at FROM users WHERE id=?",(UID,))];[print(r) for r in c.execute("SELECT user_id,platform,validation_status FROM purchases ORDER BY id DESC LIMIT 3")]' -->
  - _Actual:_ <!-- paste rows -->

- [ ] **DB backup taken BEFORE deploy (migration story).** Snapshot prod DB so migration 014 is reversible.
  - _Command:_ `ssh root@167.235.63.129 "cp /opt/survive-the-talk/data/db.sqlite /opt/survive-the-talk/data/db.sqlite.bak-pre-8.1-$(date +%Y%m%d-%H%M%S)"`
  - _Proof:_ <!-- paste the resulting filename -->

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 50 --since "5 min ago"` shows no ERROR/Traceback for the verify request(s).
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

- [ ] **(On-device, PENDING D4) Native purchase smoke gate.** Android (Play license-test account) + iOS (sandbox, post-10-4): tap subscribe in the paywall placeholder → native sheet → purchase → tier flips → `BottomOverlayCard` disappears. **Cannot run until Walid configures the store products + test accounts.**

---

## Dev Notes

### Verified anchor points (reuse these — do NOT reinvent)

**Server**
- Users/tier: `tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','paid'))` — `db/migrations/001_init.sql:9–15`, CHECK finalized by `003_tier_rename_full_to_paid.sql:17`. Canonical value is `'paid'` (ADR 002). No `subscription_expires_at`/`tier_changed_at` today (D3 adds the latter).
- Query layer: `db/queries.py` — `get_user_by_id` (:22), `insert_user` (:30, the `lastrowid` assert idiom), `update_user_jwt_hash` (:50, the mutate-and-commit template for `update_user_tier`). **Architecture Boundary 4: routes never build SQL — go through `queries.py`.**
- Migration runner: `db/database.py:run_migrations` — lexical filename order, `schema_migrations` ledger, `BEGIN IMMEDIATE`. Migration test gate: `tests/test_migrations.py` (replays vs `tests/fixtures/prod_snapshot.sqlite`).
- Call-limit/tier enforcement (the consumer of `paid`): `api/usage.py:compute_call_usage` (free = lifetime total, paid = per-day) + `api/routes_calls.py:197–216` (`CALL_LIMIT_REACHED`, 403). **Do not regress this.** After flip to `paid`, paid counting is per-day → fresh cap; the downgrade lifetime-count bug is D3.
- Envelopes: `api/responses.py` — `ok(data, extra_meta=)` (:23), `err(code, message, detail=)` (:59). HTTPException→`{error}` conversion: `api/app.py:191–213` (raise `HTTPException(detail={"code","message"})`).
- Auth dependency: `api/middleware.py:require_auth` (:27) → `AUTH_DEPENDENCY = Depends(require_auth)` (:103); sets `request.state.user_id`. Router registration: `api/app.py:169–174`.
- Outbound HTTP template: `auth/email_service.py:44–80` (`httpx.AsyncClient`, status-code branching, domain exceptions, redacted logging). Background-task template: `api/app.py:54–97` + lifespan `:129–156` (`asyncio.create_task` + `Event`, fail-soft backoff).
- Config: `config.py` — Pydantic `Settings`, required fields no-default (fail-loud), optional fields `= ""` (degrade cleanly). Secrets live in `/opt/survive-the-talk/.env`, applied via `systemctl restart pipecat.service`.
- Tests: `tests/conftest.py` (`register_user`, `issue_token`), `tests/test_calls.py` (route-test pattern: mocked externals, `Authorization: Bearer` header, `{data,meta}` asserts). Loguru logs need a temp sink, not `caplog` (server/CLAUDE.md §3).

**Client**
- No `in_app_purchase` dependency yet (`pubspec.yaml`). State = `flutter_bloc ^9.1.1`; HTTP = `dio ^5.9.2` via `core/api/api_client.dart` (auto-adds `Authorization: Bearer` except `/auth/*`; maps errors to `ApiException`). Secure storage = `flutter_secure_storage ^10.0.0`.
- Repository template: `features/scenarios/repositories/scenarios_repository.dart` (ctor takes `ApiClient`, extract `response.data!['data']`, `Model.fromJson`). Bloc template: `features/scenarios/bloc/scenarios_bloc.dart` (sealed events/states, `ApiException` classification, spam guard).
- Tier in the client: `features/scenarios/models/call_usage.dart` (`tier`, `isFree`) — fetched in `GET /scenarios` `meta` (NOT a separate profile call). `BottomOverlayCard` renders the 4 UX-DR5 states; paid+calls-remaining → no card.
- Paywall placeholder to wire: `features/paywall/views/paywall_sheet.dart` (`PaywallSheet.show()` modal; `_PaywallSheetBody` is the "coming in 8.2" stub). Invoked from `scenario_list_screen.dart:142–145`.
- Model convention: manual `fromJson` (e.g. `features/call/models/call_session.dart`) — no `freezed`/`json_serializable`.
- Service-wrapper-for-testability convention: `PermissionService`, `core/services/connectivity_service.dart`.
- Tests: `mocktail` + `bloc_test`; `FlutterSecureStorage.setMockInitialValues({})` in `setUp` (mandatory). `flutter analyze` must print "No issues found!" before commit.
- Error UX: full-screen `EmpatheticErrorScreen` for unrecoverable ops; `AppToast` for transient hints; inline `AppColors.destructive` text for field errors (project convention — see client CLAUDE.md).

### Latest tech (verified June 2026)

- **`in_app_purchase` 3.3.0** (latest, ~June 2026). iOS 13+, Android SDK 24+, macOS 10.15+. **iOS uses StoreKit 2 by default**; Android wraps Google Play Billing. Ships **no** server validation — we build it. Use `purchaseDetails.verificationData.serverVerificationData` (JWS on iOS, purchaseToken on Android).
- **Apple validation:** `verifyReceipt` is **DEPRECATED**. Modern path = forward the StoreKit 2 **signed-transaction JWS** to the server; verify the JWS (x5c chain → Apple root) and/or call the **App Store Server API** `GET https://api.storekit.itunes.apple.com/inApps/v1/transactions/{transactionId}` (JWT signed with an App Store Connect API key). Apple's official `app-store-server-library` (Python) does both; handle sandbox vs production environments.
- **Google validation:** `GET https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{packageName}/purchases/subscriptionsv2/tokens/{token}`, OAuth scope `androidpublisher`, service-account credentials. Response = `SubscriptionPurchaseV2`; grant on `subscriptionState ∈ {ACTIVE, IN_GRACE_PERIOD}`.

### Anti-patterns to avoid

- ❌ Storing any card data / using Apple's deprecated `verifyReceipt`. ❌ RevenueCat (D1). ❌ Raw SQL in routes (Boundary 4). ❌ Trusting the client's word that a purchase happened — the server MUST validate the artifact (or, in D2's outage fallback, validate eventually). ❌ Flipping tier without stamping `tier_changed_at` (D3). ❌ Adding `GET /user/profile` here (that's 8.3 — refresh via `/scenarios`). ❌ Building the full paywall UI (that's 8.2 — keep G1 minimal). ❌ Skipping `refresh_prod_snapshot.py` after adding the `purchases` table. ❌ Forgetting `FlutterSecureStorage.setMockInitialValues({})` in client tests. ❌ Hard-coding the product id in two places that can drift — share `IAP_PRODUCT_ID` ↔ `kIapWeeklyProductId`.

### Project Structure Notes

- New server package `server/billing/` mirrors `server/auth/`. New route file `server/api/routes_subscription.py` mirrors `routes_calls.py`/`routes_scenarios.py`; register in `api/app.py`. Migration `014_subscriptions.sql` follows the `db/migrations/NNN_*.sql` convention.
- New client feature `lib/features/subscription/` (`services/ repositories/ bloc/ models/`) mirrors `features/scenarios/` / `features/call/`. The paywall stays in `features/paywall/` (8.2 owns its UI); 8.1 only swaps the placeholder body.
- No conflicts with the unified structure detected. One naming note: architecture.md mentions `GET /user/profile` for tier — deliberately **not** built here (Story 8.3 owns it); tier is served via the existing `/scenarios` `meta` envelope.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 8.1] — AC source (lines 1402–1431).
- [Source: _bmad-output/planning-artifacts/prd.md] — FR28–FR31 (:455–458), NFR11 (:503), NFR26 (:535).
- [Source: _bmad-output/planning-artifacts/architecture.md] — integrations + failure modes (:47, :445–446), users.tier (:245), monetization mapping (:906).
- [Source: _bmad-output/planning-artifacts/adr/002-tier-naming.md] — canonical `'free'`/`'paid'`.
- [Source: _bmad-output/planning-artifacts/paywall-screen-design.md] — CTA + 15 s timeout (:287, :401) (consumed by 8.2; the timeout applies to 8.1's purchase flow).
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md] — UX-DR16 invisible tiers (:546–547), UX-DR5 BottomOverlayCard states (:1013–1018).
- [Source: _bmad-output/implementation-artifacts/deferred-work.md] — tier-transition lifetime-count bug (:401–403), tier-enum 500 (:406–409) — D3.
- [Source: server/CLAUDE.md §2] — migrations replay vs prod snapshot. [project-root CLAUDE.md §Database Migrations] — `refresh_prod_snapshot.py`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Opus 4.8, 1M context) — dev-story workflow, 2026-06-16.

### Debug Log References

- Server gates (warmed sandbox): `python -m ruff check .` clean, `ruff format --check .` clean, `python -m pytest` → **934 passed** (was 910; +24: subscription/billing/config/migration), incl. `test_migrations.py` replay vs `prod_snapshot.sqlite`.
- Client gates: `flutter analyze` → **No issues found!**; `flutter test` → **567 passed** (was 553; +14 subscription/paywall).
- Apple Root CA-G3 pinned from `apple.com/certificateauthority/AppleRootCA-G3.cer`, SHA-256 `63343abf…653e9179` asserted at import.

### Completion Notes List

**What shipped (purchase plumbing only — paywall UI = 8.2, full tier-enforcement/cancellation = 8.3):**

- **Server.** Migration 014 (`users.tier_changed_at` + `purchases` audit table; replay-proven on the prod snapshot). Query layer (`update_user_tier`, `insert_purchase`, `update_purchase_validation`, `get_latest_purchase_by_token`, `get_pending_purchases`). New `billing/` package: library-agnostic `ValidationResult`/`BillingConfigError`, `validate_apple` (Apple `app-store-server-library` offline JWS verify + pinned root), `validate_google` (pyjwt+httpx async service-account → subscriptionsv2), `revalidate_pending_purchases` (D2 sweep). `POST /subscription/verify` (D2 synchronous-validate-then-flip; optimistic grant only when the validator is `unreachable`; 402 on invalid; 503 on missing config) + a 5-min lifespan re-validation loop. Config secrets + the base64 service-account validator.
- **Client.** `in_app_purchase ^3.3.0`, Android `minSdk>=24`, iOS already 13.0. New `lib/features/subscription/` (service wrapper + model + repo + bloc). Paywall placeholder body replaced with the minimal subscribe control; both paywall entry points reload `/scenarios` on a completed purchase so the `paid` tier re-flows (UX-DR5).

**🚩 Decisions / trade-offs surfaced (per the surface-trade-offs-as-decisions rule):**

1. **Google validator uses `pyjwt`+`httpx`, not `google-auth`** (the spec's recommended lib). google-auth's default transport is the sync `requests` lib (not installed) and forces a thread hop; pyjwt+httpx keep the path fully async and add ZERO deps. The validator interface stays library-agnostic (B1's explicit allowance). Only `app-store-server-library` was added.
2. **The bloc subscribes to the purchase stream for its WHOLE lifetime, and the 15 s timeout only changes the UI state** (it never stops listening). This closes a "charged by the store but tier never flipped" hole a per-press subscription would open. ⚠️ **Known gap deferred to 8.2/8.3:** there is no APP-STARTUP `purchaseStream` listener yet, so a purchase the store re-delivers on next launch (e.g. an "ask-to-buy"/parental-approval that resolves after the sheet closed) is only verified if the paywall bloc happens to be alive. The minimal 8.1 surface accepts this; 8.2/8.3 own the app-level re-delivery listener.
3. **`apple_app_apple_id` config added** (not in B2's list) — `app-store-server-library` REQUIRES the numeric App Store app id to verify a PRODUCTION transaction (sandbox doesn't need it). Optional/None default.
4. **Skipped the optional iOS `Configuration.storekit` test file** + left the bundle id as `$(PRODUCT_BUNDLE_IDENTIFIER)` — both only matter on a local Xcode/simulator dev loop, and iOS is gated until Story 10-4.
5. **Live validation coverage limit:** neither validator runs LIVE in 8.1 — Apple is gated on D4 + Story 10-4, Google on D4 (store products + service account). Tests mock the validators; the real crypto/HTTP paths are structurally correct + unit-tested (Google branching via a fake httpx client; Apple via config-guard + pinned-root integrity) but mock-tested only until the stores exist.
6. **prod_snapshot NOT refreshed pre-deploy** — migration 014 replays on top of the pre-014 snapshot exactly as it deploys to prod, and the replay test is green. The refresh is the established post-deploy step (same as 011/012/013; documented in `test_migrations.py`).

**Who-does-what (recap for Walid):** I merged/deployed nothing yet — this is dev-complete, flipped to `review`. The server side is fully runnable now; the on-device purchase smoke gate is BLOCKED on D4 (you create the `stt_weekly_199` products in App Store Connect + Play Console with the test accounts) — iOS additionally waits on Story 10-4. Next: a `/bmad-code-review`, then the Pixel-9 smoke gate clears the `review → done` flip.

### File List

**Server — new**
- `server/db/migrations/014_subscriptions.sql`
- `server/billing/__init__.py`
- `server/billing/models.py`
- `server/billing/apple_roots.py`
- `server/billing/apple_validator.py`
- `server/billing/google_validator.py`
- `server/billing/revalidation.py`
- `server/api/routes_subscription.py`
- `server/tests/test_subscription.py`
- `server/tests/test_billing.py`

**Server — modified**
- `server/pyproject.toml` (+`app-store-server-library`)
- `server/uv.lock` (resolved new deps)
- `server/config.py` (billing config fields + base64 validator)
- `server/db/queries.py` (subscription query functions)
- `server/api/app.py` (router registration + re-validation lifespan loop)
- `server/models/schemas.py` (`SubscriptionVerifyIn`/`SubscriptionVerifyOut`)
- `server/tests/test_migrations.py` (`test_migration_014_subscriptions`)
- `server/tests/test_config.py` (IAP config tests)

**Client — new**
- `client/lib/features/subscription/services/in_app_purchase_service.dart`
- `client/lib/features/subscription/models/subscription_status.dart`
- `client/lib/features/subscription/repositories/subscription_repository.dart`
- `client/lib/features/subscription/bloc/subscription_event.dart`
- `client/lib/features/subscription/bloc/subscription_state.dart`
- `client/lib/features/subscription/bloc/subscription_bloc.dart`
- `client/test/features/subscription/models/subscription_status_test.dart`
- `client/test/features/subscription/repositories/subscription_repository_test.dart`
- `client/test/features/subscription/bloc/subscription_bloc_test.dart`

**Client — modified**
- `client/pubspec.yaml` + `client/pubspec.lock` (`in_app_purchase ^3.3.0`)
- `client/android/app/build.gradle.kts` (`minSdk = maxOf(flutter.minSdkVersion, 24)`)
- `client/lib/features/paywall/views/paywall_sheet.dart` (minimal subscribe control + `debugBlocBuilder` seam)
- `client/lib/features/scenarios/views/scenario_list_screen.dart` (G2 tier-refresh at both paywall call sites)
- `client/test/features/paywall/views/paywall_sheet_test.dart` (new UI assertions)

### Change Log

- 2026-06-16 — Story 8.1 dev-story: StoreKit 2 + Google Play Billing purchase plumbing + first-party server validation (`POST /subscription/verify`, D2 validate-then-flip) + migration 014 (`tier_changed_at` + `purchases`) + tier flip + client subscription feature wired into the paywall placeholder. Gates: server ruff clean + pytest 934; client analyze clean + flutter 567. Status `ready-for-dev` → `in-progress` → `review`.

---

## Review Findings (formal `/bmad-code-review`, 2026-06-17)

> Adversarial multi-layer review (9 auditors: blind / edge-case / acceptance / payment-fraud / crypto-validator / async-lifespan / migration / flutter / test-quality → dedup → per-finding adversarial verification). 48 raw → 25 canonical findings. AC5 gates **independently re-run green** by the reviewer: server `ruff` clean + `pytest` **934 passed**; client `flutter analyze` clean + `flutter test` **567 passed**.
>
> ⚠️ The per-finding verification phase hit API rate-limiting, so F9–F25 were auto-classed "rejected" with 0 verifier votes — those are **infra false-rejections, not refutations**. The reviewer personally re-triaged every one against the code; the classifications below are the reviewer's, not the raw machine verdict.
>
> **AC status:** AC1 partial, **AC2 VIOLATED (F1)**, AC3 partial (F2), AC4 satisfied (minor F9), AC5 green-but-masks-test-gaps.

### ✅ Resolution (2026-06-17) — all patches applied, gates re-green

Walid's decisions: **F7 → minimal fix now** ((user_id, token) idempotency + cross-user reject), **F13 → defer to 8.2** (Apple-Restore is a 10-4-gated UI affordance; tracked in deferred-work), **patch batch → fix everything now**.

**Applied this session:**
- **🔴 F1** — `apple_validator.py` rejects any `environment ∉ {Production, Sandbox}` BEFORE building the verifier (Xcode/LocalTesting skip-path now unreachable); Sandbox gated behind default-off `APPLE_ACCEPT_SANDBOX`; the **forged-`Xcode`-JWS regression test** (F20) drives the real path and asserts `invalid`. **AC2 bypass closed.**
- **F2** — sweep revert is now conditional (`count_user_valid_purchases`) + atomic (`BEGIN IMMEDIATE`).
- **F3+F6+F7** — route rewritten to two short atomic transactions (TX1 check+insert / TX2 flip+stamp) with the network validation lock-free between; cross-user replay → 409 `PURCHASE_CONFLICT`; pending/invalid re-POST short-circuits; `UNIQUE(verification_token)` added to migration 014.
- **F5** — client `complete()` wrapped (`_safeComplete`) so a throw can't escape the handler or strand the transaction.
- **F8/F9/F10/F14/F19/F4-doc** — Google token URL-encoded; server-validated `product_id` persisted; both-or-neither Google config boot validator; `verification_data` cap 8192→16384; validator `reason` hardened; bloc docstring corrected.
- **Test gaps F20–F25** — Apple branch coverage (incl. F1 regression), Google 401/403 + IN_GRACE + 404 + URL-encoding, bloc complete/restored/pending/buy/close, paywall UI states + `pop(true)`, migration CHECK/FK-CASCADE/UNIQUE/restamp.

**Gates (reviewer re-ran):** server `ruff` clean + `pytest` **957 passed** (+23); client `flutter analyze` clean + `flutter test` **577 passed** (+10).

**Deferred to 8.2/8.3/10-4** (see deferred-work.md): F4-func (app-lifetime listener), F11/F12 (Google expiry semantics), F13 (Restore Purchases — **must-do before iOS submission**), F15/F16/F17/F18.

**Status:** Story **stays `review`** — the code review is complete, but the Pixel 9 / on-device purchase gate is BLOCKED on D4 (store setup) + Story 10-4 (iOS pipeline). It is review-complete; it waits ONLY on the on-device smoke gate for the `review → done` flip.

### 🔴 Decision-needed (RESOLVED)

- [ ] **[Review][Decision] F7 — Store token not bound to the buyer account (receipt-replay / account-sharing).** `get_latest_purchase_by_token` has no `user_id` predicate and neither validator checks Apple `appAccountToken` / Google `obfuscatedAccountId`, so a leaked/shared *valid* token entitles whichever account POSTs it first. Bounded ($1.99, 3 calls/day, one-upgrade-per-token, first-recorder-wins) and NOT in the declared deviations. **Choice:** (a) minimal in-scope fix now — key idempotency on `(user_id, verification_token)`, reject cross-user replay, `UNIQUE(transaction_id)`; or (b) defer full account-binding to 8.3 with a documented 8.1 limitation. [server/api/routes_subscription.py:86, server/db/queries.py:613]
- [ ] **[Review][Decision] F13 — No `restorePurchases` path.** `InAppPurchaseService` exposes no restore; a paying subscriber who reinstalls / switches device cannot recover paid, and Apple App Review *requires* a visible "Restore Purchases" affordance for auto-renewable subs (bites at the Story 10-4 iOS gate). **Choice:** add a minimal `restore()` now vs defer to 8.2 (paywall UI) with a tracked must-do-before-iOS-submission note. [client/lib/features/subscription/services/in_app_purchase_service.dart]

### 🩹 Patch (unambiguous, in-scope)

- [ ] **[Review][Patch] 🚨 F1 (BLOCKER, security) — Apple validator trusts the UNVERIFIED `environment` claim → complete iOS validation bypass.** `_verify_sync` reads `environment` from `jwt.decode(..., verify_signature=False)`; `Environment('Xcode')`/`Environment('LocalTesting')` are valid enum members and Apple's `SignedDataVerifier` **skips signature + x5c-chain verification** for those environments. A forged unsigned JWS `{environment:'Xcode', bundleId:ours, productId:ours, expiresDate:future}` returns `status='valid'` → `tier='paid'`, no Apple key / cert / real receipt (empirically reproduced by the crypto-validator agent end-to-end). Latent ONLY because `apple_bundle_id=""` → 503 today; **goes live the instant `APPLE_BUNDLE_ID` is set** (which 8.1's own store-setup plan does for the gate). FIX: reject `environment not in (PRODUCTION, SANDBOX)` BEFORE building the verifier; gate SANDBOX acceptance behind an explicit `APPLE_ACCEPT_SANDBOX` flag (default off in prod) so free sandbox receipts can't grant paid on prod; + regression test. [server/billing/apple_validator.py:65-87, server/api/routes_subscription.py:124]
- [ ] **[Review][Patch] F2 (HIGH, concurrency) — Background revert to `free` is unconditional + not atomic vs the verify route.** The sweep flips the user to `free` on a single invalid pending row without checking for another still-valid purchase and with no `BEGIN IMMEDIATE`, so it can clobber a legitimately re-subscribed user / race the verify route (last-writer-wins). FIX: only downgrade when the user has no other valid+unexpired purchase; wrap status-write + tier-write in one `BEGIN IMMEDIATE`. [server/billing/revalidation.py:94-106]
- [ ] **[Review][Patch] F3 (+F6) (MED-HIGH, concurrency) — Verify route check-then-write is not atomic; no `UNIQUE(verification_token)`; idempotency guard only short-circuits on `'valid'`.** Concurrent duplicate POSTs both pass the guard and double-insert/re-validate; the tier flip + audit stamp are two separate commits (crash between → `paid` row stuck `pending`); a forged-invalid token is re-POSTable unbounded. FIX: wrap SELECT→insert→flip→stamp in one `BEGIN IMMEDIATE`; add `UNIQUE(verification_token)` (migration 014) and treat IntegrityError as idempotent re-entry; broaden the guard to handle `pending`/`invalid`. This is the lone money path that omits `BEGIN IMMEDIATE` (cf. routes_calls.py:281). [server/api/routes_subscription.py:82-184, server/db/migrations/014_subscriptions.sql]
- [ ] **[Review][Patch] F5 (MEDIUM, client) — `complete()` is called unguarded in `finally`; a throw escapes the handler AND leaves the transaction unfinished** (iOS re-delivers it every launch + blocks re-buy). FIX: `try/catch` each `complete()` (verify finally + error/canceled branches); log + rely on next-launch re-delivery. [client/lib/features/subscription/bloc/subscription_bloc.dart:106,112,142]
- [ ] **[Review][Patch] F8 (LOW, security) — Google `purchaseToken` interpolated raw into the API URL path** (no `urllib.parse.quote`); attacker bytes reshape the request (fails closed to `invalid`, but defense-in-depth). FIX: `quote(purchase_token, safe='')`. [server/billing/google_validator.py:90-93]
- [ ] **[Review][Patch] F9 (LOW, correctness) — `insert_purchase` stores the unvalidated client `product_id`**, not the server-validated id → misleading audit trail. FIX: persist `settings.iap_product_id`. [server/api/routes_subscription.py:100]
- [ ] **[Review][Patch] F4-doc (LOW) — Bloc docstring overclaims** ("the plugin re-delivers on next launch — still gets verified" is false; the listener is sheet-scoped). FIX: soften the docstring to scope the guarantee to the sheet/bloc lifetime (the functional gap is declared deviation #2, deferred below). [client/lib/features/subscription/bloc/subscription_bloc.dart:13-21]
- [ ] **[Review][Patch] F10 (LOW) — Asymmetric Google config boots clean then 503s every Android buyer.** FIX: boot-time "both-or-neither" validator for `google_play_package_name` / `google_service_account_json`. [server/config.py]
- [ ] **[Review][Patch] F14 (LOW) — `verification_data` capped at 8192** with no margin; a larger StoreKit 2 JWS would 422 a real iOS buyer pre-validation. FIX: raise to 16384 / drop the upper bound. [server/models/schemas.py]
- [ ] **[Review][Patch] F19 (LOW, hardening) — Raw Apple `VerificationException` text interpolated into logged `reason`.** No secret leak today (keys/JSON never interpolated), but keep reason strings to stable codes. [server/billing/apple_validator.py:94]
- [ ] **[Review][Patch] F20–F25 (test-gaps) — The money/fraud surface is green-but-uncovered.** F20: no test drives a JWS through the Apple verifier (a single forged-`Xcode` negative test would have caught F1). F21: Google 401/403→`BillingConfigError` untested. F22: bloc `complete()` guard / `restored` / `pending` branches + the sweep's `pending→valid` arm untested. F23: paywall_sheet never drives the bloc UI states / `pop(true)` G2 contract. F24: idempotency tested only same-user-sequential (no cross-user replay, no concurrent, no Google IN_GRACE_PERIOD / 400-404-410). F25: migration test asserts only the platform CHECK (not validation_status CHECK / FK CASCADE / `tier_changed_at` restamp). FIX: add the listed negative/adversarial tests alongside the patches above.

### ✅ Defer (real, but 8.2 / 8.3 / 10-4 scope)

- [x] **[Review][Defer] F4-func — No app-lifetime `purchaseStream` listener** (interrupted / Ask-to-Buy / next-launch re-delivery only verified if the sheet is open). Declared deviation #2 → 8.2/8.3 app-scope listener.
- [x] **[Review][Defer] F11 — Google valid path never cross-checks `expiryTime` vs now** (ACTIVE + past expiry stays valid; inconsistent with the Apple expiry guard). → 8.3 expiry enforcement.
- [x] **[Review][Defer] F12 — Google `expiryTime` picked by lexicographic `max()` on RFC3339 strings** (`expires_at` only stored/echoed in 8.1). → 8.3.
- [x] **[Review][Defer] F16 — `restored` stream updates auto-flip tier / pop the sheet without a user tap** (benign, server re-verifies). → 8.2 paywall UX.
- [x] **[Review][Defer] F17 — A `pending` purchase parks the paywall on a perpetual spinner** with no progress copy (modal is dismissible). → 8.2 paywall UX.
- [x] **[Review][Defer] F18 — Lifespan shutdown swallows `CancelledError` per-task** (no leak; `stop_event.set()` covers it). → low-pri robustness.
- [x] **[Review][Defer] F15 — Client `_platform` maps every non-iOS target to `'android'`** (harmless for the iOS+Android shipping target). → low-pri guard.

### 🟢 Nits (intended no-ops for the minimal 8.1 surface)

- `SubscriptionCancelled` has no UI feedback (sheet stays open) — intended for minimal 8.1 (8.2 owns copy).
- No bloc test proves `_purchaseSub` is cancelled on `close()` — add a teardown test with the other test-gap fixes.
