# Story 8.1: Integrate StoreKit 2 and Google Play Billing

Status: ready-for-dev

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

## ⚠️ Pre-Dev Decisions (recommended defaults baked in — Walid may override)

This story carries genuine design forks. The recommended option is **already baked into the Tasks below** so the dev agent can proceed without blocking. Walid should confirm or override **D2, D3, D4** before/at dev start (D1 is settled by the architecture).

- **D1 — Library: native `in_app_purchase` + our own server validation (NOT RevenueCat). ✅ SETTLED.**
  Architecture lists "Apple StoreKit 2" and "Google Play Billing" as the integrations (architecture.md:47, :445–446); NFR11 says payment is "delegated entirely to StoreKit 2 / Google Play Billing." RevenueCat appears nowhere in the planning artifacts and would insert a third-party receipt validator. → Use the official `in_app_purchase` ^3.3.0 plugin (iOS uses **StoreKit 2 by default**; Android uses Google Play Billing) + first-party server validation.

- **D2 — Validation timing (the NFR26 tension). ⚠️ CONFIRM.**
  NFR26 reads literally as "grant paid **immediately**, validate **async**, revoke if it fails." A pure-optimistic flip on an *unvalidated* receipt is a fraud window: a forged artifact buys up to the paid daily call-cap (3 calls ≈ $0.15 of API abuse) before the async check reverts it.
  **Recommended (baked in): synchronous validation in the happy path.** Validate against Apple/Google *inside* the request (~1–4 s); flip `tier='paid'` only on a **valid** result. Fall back to **optimistic grant + `validation_status='pending'` + background re-check** ONLY when the validator is *unreachable* (Apple/Google timeout/5xx) — this preserves NFR26's real intent (never permanently block a paying user on a validator outage) while closing the fraud window in the normal case. AC2/AC3/AC4 are all satisfied either way.
  **Alternative:** literal NFR26 — always flip first, always validate in the background. Simpler request path, wider abuse window.

- **D3 — Tier-transition call-count bug / `users.tier_changed_at`. ⚠️ CONFIRM.**
  Known deferred bug (deferred-work.md:401–403): free-tier call counting is **lifetime**, so a user who goes free→paid→free is hard-capped at 0 forever (their paid-era calls count against the free lifetime cap). deferred-work flags this for "Epic 8 — the moment a user can leave free tier."
  **Recommended (baked in): add the `users.tier_changed_at` column in migration 014 now and stamp it on every tier flip, but DEFER the call-counting rework to Story 8.3.** Rationale: in 8.1 the only paid→free path is a *validation failure* (effectively fraud), where a 0-cap is acceptable; legitimate downgrades (cancellation) arrive in 8.3, which owns the counting fix. Adding the column now avoids a second migration.
  **Alternative:** do the full counting rework here (scope creep), or add nothing now (a second migration in 8.3).

- **D4 — Store product configuration is Walid-owned and BLOCKS the live smoke gate. 🔑 ACTION REQUIRED.**
  The actual products must be created in **App Store Connect** (iOS) and **Google Play Console** (Android) — both require Walid's developer accounts, a paid Apple Developer membership, an uploaded build, and sandbox/license-test accounts. The product ID must match the shared constant the code uses. **Proposed product ID: `stt_weekly_199`** (lowercase, store-portable). Confirm or change. Until the products exist + are in a testable state, the on-device purchase smoke gate cannot run. iOS additionally can't be device-validated until Story 10-4 (no iOS test pipeline yet — `project_ios_test_pipeline_deferred.md`).

---

## Tasks / Subtasks

### A. Server — schema & query layer

- [ ] **Task A1 — Migration `014_subscriptions.sql` (AC2, AC3, AC4; D3).**
  - [ ] Create `server/db/migrations/014_subscriptions.sql` (next free number — confirmed 013 is the latest).
  - [ ] `ALTER TABLE users ADD COLUMN tier_changed_at TEXT;` — nullable, ISO-8601 UTC, stamped on every tier flip (D3). **No table rebuild / no PRAGMA dance needed** — `ADD COLUMN` is safe (contrast migration 003 which rebuilt for a CHECK change).
  - [ ] Create the audit table:
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
  - [ ] Keep it idempotent (`IF NOT EXISTS`) — the runner replays by lexical filename order and records applied versions in `schema_migrations` (`db/database.py:run_migrations`).
  - [ ] **NFR11 note in the migration header comment:** `verification_token` stores a store verification artifact (JWS / purchaseToken), never a card number or payment token.
  - [ ] After writing: `cd server && python -m pytest tests/test_migrations.py` MUST stay green (replays migrations against `tests/fixtures/prod_snapshot.sqlite`). Because this adds a **new table**, run `python scripts/refresh_prod_snapshot.py` and commit the refreshed snapshot alongside the migration (project-root CLAUDE.md §Database Migrations).

- [ ] **Task A2 — Query functions in `server/db/queries.py` (AC2, AC3; D3).** Follow the existing `update_user_jwt_hash` pattern exactly (queries.py:50–59 — async, takes an open `aiosqlite.Connection`, commits before returning, Architecture Boundary 4: NO raw SQL in routes).
  - [ ] `async def update_user_tier(db, user_id: int, tier: str, *, tier_changed_at: str) -> None` → `UPDATE users SET tier = ?, tier_changed_at = ? WHERE id = ?`. (Stamps D3's column on every flip.)
  - [ ] `async def insert_purchase(db, *, user_id, platform, product_id, verification_token, created_at) -> int` (returns id; assert `lastrowid is not None` like `insert_user`).
  - [ ] `async def update_purchase_validation(db, purchase_id: int, *, validation_status, transaction_id, expires_at, validated_at) -> None`.
  - [ ] `async def get_latest_purchase_by_token(db, verification_token: str) -> aiosqlite.Row | None` — idempotency guard so re-POSTing the same artifact doesn't double-insert.

### B. Server — validation module

- [ ] **Task B1 — New `server/billing/` package (mirrors the `auth/` package layout).** Keep the public interface library-agnostic so the internal validator lib is swappable.
  - [ ] `billing/models.py` — a `ValidationResult` dataclass: `valid: bool`, `status: Literal['valid','invalid','unreachable']`, `transaction_id: str | None`, `expires_at: str | None`, `reason: str | None`. The `'unreachable'` status is what triggers D2's optimistic fallback.
  - [ ] `billing/apple_validator.py` — `async def validate_apple(jws: str, *, bundle_id: str, expected_product_id: str) -> ValidationResult`. **`verifyReceipt` is DEPRECATED — do NOT use it.** Validate the StoreKit 2 signed-transaction **JWS**: verify the x5c certificate chain to Apple's root, then assert payload `bundleId == bundle_id`, `productId == expected_product_id`, and not expired/revoked. **Recommended lib:** Apple's official `app-store-server-library` (Python) which does signature verification + the App Store Server API client; add to `server/requirements*.txt`. Handle sandbox vs production environments (the JWS carries the environment). Network/5xx/timeout → return `status='unreachable'` (do not raise).
  - [ ] `billing/google_validator.py` — `async def validate_google(purchase_token: str, *, package_name: str, product_id: str, service_account_json: str) -> ValidationResult`. Call `GET https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{package_name}/purchases/subscriptionsv2/tokens/{purchase_token}` (the **subscriptionsv2** endpoint), OAuth scope `https://www.googleapis.com/auth/androidpublisher`, mint the token from the service account (recommended: `google-auth` to sign + `httpx` to call — mirror the `httpx.AsyncClient` pattern in `auth/email_service.py:44–80`). Treat `subscriptionState ∈ {ACTIVE, IN_GRACE_PERIOD}` as valid; read the line item's `expiryTime`. Network/5xx/timeout → `status='unreachable'`.
  - [ ] `billing/__init__.py` — export the two validators + `ValidationResult`.
  - [ ] Add any new Python deps (`app-store-server-library`, `google-auth`) to the server requirements file; verify they install in the venv and don't break `pytest` import (warm the sandbox per `feedback_sandbox_livekit_import_hang.md` if a cold import stalls).

- [ ] **Task B2 — Config fields in `server/config.py` (AC2, AC4).** Follow the optional-field pattern (empty-string default so a missing secret degrades cleanly rather than failing boot — like `cartesia_api_key`):
  - [ ] `apple_bundle_id: str = ""` (`APPLE_BUNDLE_ID`) — must match the iOS bundle identifier.
  - [ ] App Store Connect API-key fields for the App Store Server API: `apple_issuer_id`, `apple_key_id`, `apple_private_key_p8` (all `str = ""`). _(Only needed if calling the App Store Server API for revocation; offline JWS verification needs only the bundle id + Apple root certs bundled by the lib.)_
  - [ ] `google_play_package_name: str = ""` (`GOOGLE_PLAY_PACKAGE_NAME`) — must equal the Android `applicationId` (`com.surviveTheTalk.client`).
  - [ ] `google_service_account_json: str = ""` (`GOOGLE_SERVICE_ACCOUNT_JSON`, base64-encoded) — add a `field_validator` that base64-decodes + `json.loads` to fail loud on a malformed value (only when non-empty).
  - [ ] `iap_product_id: str = "stt_weekly_199"` (`IAP_PRODUCT_ID`) — the expected product id, shared with the client constant (D4).

### C. Server — endpoint

- [ ] **Task C1 — `POST /subscription/verify` in new `server/api/routes_subscription.py` (AC2, AC3, AC4; D2).**
  - [ ] `router = APIRouter(prefix="/subscription", tags=["subscription"], dependencies=[AUTH_DEPENDENCY])` — reuse the auth dependency from `api/middleware.py:103` (resolves `request.state.user_id`; 401 `AUTH_UNAUTHORIZED` on a bad/absent JWT, identical to every other protected route).
  - [ ] Request model `SubscriptionVerifyIn` (put in `models/schemas.py` next to the other Pydantic models): `platform: Literal['ios','android']`, `product_id: str`, `verification_data: str`.
  - [ ] Handler flow (recommended D2 — synchronous-validate-then-flip with unreachable fallback):
        1. `user_id = request.state.user_id`.
        2. Idempotency: if `get_latest_purchase_by_token` already exists and is `'valid'`, return the current tier without re-validating.
        3. `insert_purchase(..., created_at=now_iso())` with `validation_status='pending'`.
        4. Validate via `validate_apple` / `validate_google` (branch on `platform`), passing `settings.iap_product_id` as `expected_product_id`.
        5. If `valid` → `update_user_tier(db, user_id, 'paid', tier_changed_at=now_iso())` + `update_purchase_validation(... 'valid' ...)`.
        6. If `invalid` → leave tier untouched (do NOT flip), mark purchase `'invalid'`, return HTTP 402/400 with `{"code": "PURCHASE_INVALID", "message": ...}` (use the `HTTPException(detail={"code","message"})` convention — `api/app.py:202` turns it into the `{error}` envelope).
        7. If `unreachable` (D2 fallback) → optimistic: `update_user_tier(... 'paid' ...)`, keep purchase `'pending'`, and schedule a background re-check (see Task C2). Return success.
  - [ ] Response model `SubscriptionVerifyOut`: `tier: Literal['free','paid']`, `product_id: str`, `expires_at: str | None`, `status: str`. Wrap with `ok(...)` from `api/responses.py:23`.
  - [ ] Register the router in `api/app.py` after line 174: `app.include_router(subscription_router)`.

- [ ] **Task C2 — Background re-validation for `'pending'` purchases (D2 fallback only).** Reuse the existing janitor-loop pattern in `api/app.py:54–97` (lifespan `asyncio.create_task` + `asyncio.Event` stop, fail-soft with backoff). Add a periodic sweep that re-validates `purchases` rows still `'pending'`; on a definitive `invalid`, flip the user back to `'free'` (stamp `tier_changed_at`) and mark the row `'invalid'` — this is the concrete mechanism behind AC3 "reverted on the next API call." Keep it small; if D2 is overridden to literal-NFR26 this loop becomes the primary validator instead of a fallback.

### D. Server — tests

- [ ] **Task D1 — `server/tests/test_subscription.py` (AC2, AC3, AC4, AC5).** Use `conftest.py` fixtures (`client`, `test_db_path`, the `register_user` / `issue_token` helpers). Mock the outbound Apple/Google HTTP (patch the validator functions or the `httpx` call — never hit real stores in pytest). Cover:
  - [ ] No JWT → 401 `AUTH_UNAUTHORIZED`.
  - [ ] Valid iOS JWS → 200, `users.tier == 'paid'`, `tier_changed_at` set, a `purchases` row `'valid'`.
  - [ ] Valid Android token → 200, tier flipped.
  - [ ] Invalid artifact → tier stays `'free'`, purchase `'invalid'`, `{error: {code: PURCHASE_INVALID}}` envelope.
  - [ ] Validator `unreachable` → tier optimistically `'paid'`, purchase `'pending'` (D2 fallback).
  - [ ] Idempotent re-POST of the same valid token → no double flip, no duplicate `'valid'` row.
  - [ ] (If D2 = optimistic-then-revert) background re-check on a `'pending'`-then-`invalid` row reverts tier to `'free'`.
  - [ ] `test_migrations.py` stays green (Task A1).

### E. Client — dependency & platform config

- [ ] **Task E1 — Add the plugin (AC1).** `client/pubspec.yaml`: add `in_app_purchase: ^3.3.0` (current latest; iOS uses StoreKit 2 by default, Android wraps Google Play Billing). `flutter pub get`.
- [ ] **Task E2 — Android config (AC1).** In `client/android/app/build.gradle.kts`, ensure **`minSdk >= 24`** (the `in_app_purchase` 3.x Android requirement; the project currently uses `flutter.minSdkVersion`). If Flutter's default resolves below 24, pin `minSdk = 24` explicitly. Google Play Billing needs no manifest permission (the SDK declares it; `INTERNET` is already present). Confirm `applicationId = "com.surviveTheTalk.client"` equals `GOOGLE_PLAY_PACKAGE_NAME` (Task B2).
- [ ] **Task E3 — iOS config (AC1).** Ensure the iOS deployment target is **>= 13.0** (`ios/Podfile` platform + Xcode project). The in-app-purchase capability is implicit for the plugin. Add a local `Configuration.storekit` StoreKit-test file for simulator/dev testing (optional but recommended). Resolve the literal bundle identifier (currently `$(PRODUCT_BUNDLE_IDENTIFIER)` in Info.plist) and feed it to `APPLE_BUNDLE_ID` (Task B2).

### F. Client — feature implementation (`lib/features/subscription/`)

- [ ] **Task F1 — `services/in_app_purchase_service.dart` (AC1).** A thin, **mockable** wrapper over the `in_app_purchase` plugin (same wrapper-for-testability convention as `PermissionService` / `connectivity_service.dart`):
  - [ ] `Future<ProductDetails?> loadProduct(String productId)` (via `InAppPurchase.instance.queryProductDetails({productId})`).
  - [ ] `Future<void> buy(ProductDetails product)` → `buyNonConsumable(...)` (subscriptions go through the non-consumable buy API).
  - [ ] Expose `Stream<List<PurchaseDetails>> get purchaseStream` (forwards `InAppPurchase.instance.purchaseStream`) and `Future<void> complete(PurchaseDetails)` → `completePurchase(...)`.
  - [ ] Read the unified `purchaseDetails.verificationData.serverVerificationData` — on iOS (SK2) this is the JWS, on Android it's the purchaseToken. This single field is what gets POSTed.
  - [ ] Define the shared product-id constant: `const kIapWeeklyProductId = 'stt_weekly_199';` (must equal `IAP_PRODUCT_ID`, D4).
- [ ] **Task F2 — `models/subscription_status.dart` (AC2).** Manual `fromJson` (no codegen — project convention, e.g. `call_session.dart`): `tier`, `productId`, `expiresAt`, `status`. Add `bool get isPaid => tier == 'paid';`.
- [ ] **Task F3 — `repositories/subscription_repository.dart` (AC2).** Constructor takes `ApiClient` (template: `ScenariosRepository`). `Future<SubscriptionStatus> verifyPurchase({required String platform, required String productId, required String verificationData})` → `_apiClient.post('/subscription/verify', data: {...})`, extract `response.data!['data']`, return `SubscriptionStatus.fromJson(...)`. Let `ApiException` propagate (the bloc classifies it).
- [ ] **Task F4 — `bloc/subscription_bloc.dart` + events/states (AC1, AC2, AC3).** Sealed events/states (template: `scenarios_bloc.dart`). Events: `SubscribePressed`. States: `SubscriptionInitial`, `SubscriptionLoading` (native sheet in flight), `SubscriptionPurchased` (paid), `SubscriptionFailed(code)`, `SubscriptionCancelled` (user dismissed the native sheet). Flow: load product → `buy` → listen on `purchaseStream` → on `PurchaseStatus.purchased`/`restored` call `repository.verifyPurchase(...)` with the right `platform` string → emit `SubscriptionPurchased`; on `PurchaseStatus.error`/cancel → emit failed/cancelled; always `complete()` the purchase. **Enforce the 15-second timeout** (paywall-screen-design.md:401): if no native-sheet response in 15 s, emit a failed state so the UI can recover.

### G. Client — wiring & tier refresh

- [ ] **Task G1 — Wire the existing paywall placeholder to drive the purchase (AC1, AC2).** Replace the body of `lib/features/paywall/views/paywall_sheet.dart` (`_PaywallSheetBody`, currently the "coming in Story 8.2" placeholder) with a **minimal working** subscribe control: a "Subscribe — $1.99/week" button that provides a `SubscriptionBloc` and dispatches `SubscribePressed`, plus a loading spinner and a simple error line. **Keep it minimal — Story 8.2 restyles this into the real invisible-tier paywall.** Do NOT change where `PaywallSheet.show()` is invoked (`scenario_list_screen.dart:142–145`, from `BottomOverlayCard.onPaywallTap`).
- [ ] **Task G2 — Refresh tier after success (AC2, AC3).** On `SubscriptionPurchased`: pop the sheet and dispatch `LoadScenariosEvent` to the existing `ScenariosBloc` so the fresh `CallUsage.tier` (`'paid'`) re-flows from `GET /scenarios` `meta` and the `BottomOverlayCard` updates per UX-DR5 (paid + calls remaining → card hidden). Do **not** rely on a cached tier. (8.1 does **not** add `GET /user/profile`; that's Story 8.3's. Tier rides the existing `/scenarios` envelope — `call_usage.dart`.)

### H. Client — tests

- [ ] **Task H1 — `client/test/features/subscription/...` (AC5).** Use `mocktail` + `bloc_test`; put `FlutterSecureStorage.setMockInitialValues({})` in every `setUp` (project gotcha). Cover:
  - [ ] `SubscriptionRepository.verifyPurchase` parses the `{data}` envelope → `SubscriptionStatus(isPaid == true)`; propagates `ApiException`.
  - [ ] `SubscriptionBloc`: purchased → `[Loading, Purchased]`; error → `[Loading, Failed]`; cancel → `[Loading, Cancelled]`; 15 s timeout → failed. Mock `InAppPurchaseService`.
  - [ ] `SubscriptionStatus.fromJson` happy + malformed-defensive.
  - [ ] Run the FULL suite (`flutter test`, no args) — purchasing wiring touches the scenario-list flow; confirm no regression there.

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

### Debug Log References

### Completion Notes List

### File List
