# Story 8.2: Build Paywall Screen with Invisible Tier Design

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to see a clear subscription offer when I try to access paid content,
so that I can make an informed decision to subscribe at the moment I'm most interested.

## Story Type & Scope (read first)

**This is a CLIENT-ONLY story.** Every server piece this paywall needs already shipped in **Story 8.1** (commit `9e0590c`, deployed to prod, CI run `27682559788` green, migration 014 applied): `POST /subscription/verify`, the Apple JWS / Google `subscriptionsv2` validators, the `users.tier` flip, the `{data}/{error}` envelope, and the whole client purchase chain (`SubscriptionBloc` / `SubscriptionRepository` / `InAppPurchaseService` / `SubscriptionStatus` + a **minimal placeholder `PaywallSheet`**).

**Story 8.2 = pure Flutter UI + entry-point wiring. Do NOT touch the server. Do NOT rebuild the bloc/repo/service/model — reuse them.** The job is:
1. **Restyle** the placeholder `PaywallSheet` into the full, Walid-approved design in [paywall-screen-design.md](../planning-artifacts/paywall-screen-design.md) (4 states: Default / Loading / Success / Error).
2. **Wire the 3 entry points** (one already done, two NEW).
3. **Clean dismiss, no dark patterns, full accessibility.**

→ **Omit the server "Smoke Test Gate" — this story has zero server/DB/deploy impact.** An on-device (Android) gate section is included at the end instead.

**Hard scope boundary (do not cross):** server-side *tier enforcement* (403 `CALL_LIMIT_REACHED`/`TIER_RESTRICTED` blocking, `GET /user/profile`, expiry/cancellation, all-4-BOC-states-from-live-status) is **Story 8.3**. 8.2 only *presents and routes to* the paywall; it does not enforce limits server-side.

## Acceptance Criteria

_Verbatim from [epics.md → Epic 8 → Story 8.2](../planning-artifacts/epics.md). BDD as authored._

1. **Paid-scenario call gate (UX-DR16).** Given UX-DR16 defines invisible tiers — all scenario cards look identical — when a **free** user taps the **call icon** on a **paid** scenario, then the paywall is displayed **instead of initiating a call**. _(NEW — not implemented today; see Dev Notes §3.)_

2. **BottomOverlayCard gate (UX-DR5).** Given the BottomOverlayCard is tapped (free-user states), when the user taps the overlay card, then the paywall screen is displayed. _(Already wired in Story 8.1 G2 — keep working through the restyle; see Dev Notes §3.)_

3. **FR29 debrief gate.** Given FR29 defines paywall timing after the 3rd free scenario, when a free user **completes or fails their 3rd free scenario**, then the paywall is presented **on the debrief screen at the emotional peak**. _(NEW — not implemented today; **Decision D1 = LOCKED (Walid 2026-06-17): implement in 8.2**; see Dev Notes §4.)_

4. **Offer content + dark theme (Epic 2 design).** Given the paywall is displayed, when the user views the offer, then it shows the price (**$1.99/week**), the value proposition (all scenarios, more daily calls), and a clear subscribe CTA — **and** the visual follows the design with the established design tokens. _(The on-screen price string is split `$1.99` + `per week` per the design — see Dev Notes §2.)_

5. **Clean dismiss — no dark patterns.** Given the user dismisses the paywall, when they tap dismiss **or** system back **or** swipe down **or** tap the scrim, then they return to the previous context **unchanged** — no dark patterns, no confirmation dialog, no repeated prompts/nag.

6. **Accessibility.** Given a screen reader (VoiceOver/TalkBack) is active, when the paywall is shown, then it announces the price, the value proposition, and the available actions; all interactive targets are ≥48px.

### Additional acceptance criteria (engineering-derived, binding)

7. **Purchase wiring.** The subscribe CTA invokes the **existing Story 8.1 purchase flow** (`SubscriptionBloc` → `InAppPurchaseService` → `POST /subscription/verify`). On a confirmed purchase the sheet resolves `true` and the caller reloads `/scenarios` so the fresh `paid` tier re-flows (the G2 contract). 8.2 adds **no** new billing logic.

8. **Four screen states** render per [paywall-screen-design.md → Screen States](../planning-artifacts/paywall-screen-design.md): Default, Loading (in-CTA spinner, dismiss disabled), Success ("You're in", 1.5s hold / 5s with screen reader, auto-dismiss), Error (inline caption, re-tappable). `PopScope` blocks dismiss during Loading + Success-hold.

9. **No regressions.** `flutter analyze` clean (infos included) and `flutter test` fully green. The existing call/debrief/scenario-list flows (Stories 6.1, 7.2–7.5) keep working.

## Tasks / Subtasks

- [ ] **Task 1 — Design tokens (AC: #4, #8)**
  - [ ] In `client/lib/core/theme/app_colors.dart`, **add `paywallError = Color(0xFFC0392B)`** (darkened error for WCAG AA = 4.7:1 on the `#F0F0F0` light surface — the app-wide `destructive #E74C3C` only makes ~3.4:1 there, FAILS AA). Append it to the `values` list and **bump `theme_tokens_test.dart` count 15 → 16** (update the values list + the count assertion + a UX-DR1 rationale comment). **Decision D3 — baked in.** Do **not** inline the hex (gotcha #6).
  - [ ] Reuse the EXISTING token `AppColors.overlaySubtitle = #4C4C4C` for the paywall's secondary text (subtitle, period, dismiss, legal, drag handle) — it is already the design's `paywall-text-secondary`. Reuse `AppColors.textPrimary #F0F0F0` (sheet surface), `AppColors.background #1E1F23` (ink/CTA text), `AppColors.accent #00E5A0` (CTA fill + checkmarks).
  - [ ] Price style (36px Bold Inter): **local `const TextStyle`** in the paywall file (follow the 7.4/7.5 precedent — no new `AppTypography` token). Reuse `AppTypography.headline` (18 w600) for the title, `body` (16 w400) for subtitle/benefits/period/dismiss, `caption` (13 w400) for legal/error. CTA label = Inter 14 SemiBold.

- [ ] **Task 2 — Restyle `PaywallSheet` to the full design (AC: #4, #5, #6, #7, #8)**
  - [ ] Rebuild `client/lib/features/paywall/views/paywall_sheet.dart` `_PaywallSheetBody` to the layout in [paywall-screen-design.md → Screen Layout](../planning-artifacts/paywall-screen-design.md): drag handle (40×4, `#4C4C4C`) → 32 → title `Speak English for real` (18 SemiBold center) → 24 → subtitle `Practice with characters who won't go easy on you.` (16 Regular, max 2 lines) → 32 → price `$1.99` (36 Bold) + `per week` (16 Regular, tight) → 32 → 3 left-aligned benefits (accent check + 12 + text), 8 between → 32 → CTA `Let's go` (FilledButton, accent bg / `#1E1F23` text, full-width, 48h, radius 12) → 16 → dismiss `Not now` (TextButton, 48px target) → 32 → legal `Auto-renewable. 3 calls per day. Cancel anytime.` (13 Regular) → 20 + SafeArea.
  - [ ] **Change `_topRadius` 42.0 → 16.0** per the design (**Decision D4** — design-doc authority; declared deviation from the placeholder's BOC-lineage 42). Keep `backgroundColor: AppColors.textPrimary` (`#F0F0F0`). Wrap content in `SingleChildScrollView` (mandatory — iPhone-SE ~552px content overflows the sheet) inside a bottom-only `SafeArea`.
  - [ ] Benefit copy (verbatim): `All scenarios unlocked.` / `Daily calls. Daily progress.` / `Know exactly what you're doing wrong`. Checkmark icons are **decorative** → `ExcludeSemantics` (benefit text carries the meaning; justifies the 1.6:1 accent-on-light icon contrast under SC 1.4.11).
  - [ ] **Keep the existing public seam unchanged:** `PaywallSheet.show(BuildContext) → Future<bool>` (true=purchased, false=dismissed) and the `@visibleForTesting static SubscriptionBloc Function()? debugBlocBuilder` + `_buildBloc()` production wiring. Both call sites and all tests depend on these.
  - [ ] **States** (drive off `SubscriptionState`): Default; Loading (`SubscriptionLoading` → CTA shows 24px `CircularProgressIndicator` `#1E1F23`, CTA disabled, "Not now" disabled @40%); Success (`SubscriptionPurchased` → title → `You're in`, accent check replaces CTA, 200ms crossfade, hold 1.5s / **5s if a screen reader is active**, then auto-`pop(true)`); Error (`SubscriptionFailed` → CTA back to `Let's go`, inline `paywallError` caption `Something went wrong. Try again.` 8px below CTA, re-tap clears → Loading).
  - [ ] **`PopScope`**: `canPop` = `false` during Loading and Success-hold, `true` otherwise. System back in Default/Error == "Not now".
  - [ ] **`SubscriptionCancelled`** (user cancelled native sheet) → return to **Default** state (do not pop, do not show error). Closes the 8.1 deferred gap F4/«cancelled has no UI feedback».

- [ ] **Task 3 — Entry point #1: paid-scenario call gate (AC: #1)** — `client/lib/features/scenarios/views/scenario_list_screen.dart`
  - [ ] In `_ListState`, gate the call-icon path: at the **top of `_onCallTap`** (before the briefing push), if `widget.usage.isFree && !scenario.isFree` → `await PaywallSheet.show(context)`; on `true` && mounted → `context.read<ScenariosBloc>().add(const LoadScenariosEvent())`; **return without initiating** (no briefing, no call) — matches "paywall instead of initiating a call".
  - [ ] Add the same `isFree`-gate at the **top of `_startCall`** as the convergence safety net so the **card-tap browse** path (`_onCardTap` → briefing → `_startCall`) also converts a paid scenario to the paywall on "Pick up". (Browsing a paid scenario's briefing stays free — invisible tiers; the gate fires only on the call action.)
  - [ ] Leave the existing `CALL_LIMIT_REACHED` handler in `_startCall` intact (server-side cap → paywall; coexists with the new tier gate).

- [ ] **Task 4 — Entry point #2: BottomOverlayCard (AC: #2)**
  - [ ] No new wiring — `_OverlayHost.onPaywallTap` already calls `PaywallSheet.show` + reloads on purchase (Story 8.1 G2). **Verify it still works after the restyle**; ensure `BottomOverlayCard` actionable states (`freeWithCalls`, `freeExhausted`) still route here and `paidExhausted` stays informational (non-tappable).

- [ ] **Task 5 — Entry point #3: FR29 debrief gate (AC: #3)** — **Decision D1 = LOCKED (Walid 2026-06-17): IMPLEMENT in 8.2**
  - [ ] Compute `isFinalFreeScenario` at call initiation in `_startCall`: `final isFinalFreeScenario = widget.usage.isFree && widget.usage.callsRemaining <= 1;` (free tier = 3 calls lifetime; at the start of the 3rd/last free call `callsRemaining == 1`, so after it 0 remain → this is the FR29 scenario, whether completed or failed).
  - [ ] Thread the flag through the call→debrief handoff: `CallScreen` constructor → the push of `CallEndedScreen` (`CallEndedScreen.route(...)`) → `CallEndedScreen._debriefRoute()` → `DebriefScreen` constructor (new optional `bool presentPaywallOnLoad = false`). Keep the existing `@visibleForTesting debugDebriefRouteBuilder` seam working.
  - [ ] In `DebriefScreen`, when `presentPaywallOnLoad` is true, present the paywall **immediately on load (0ms, Open-Q1)** once the screen is mounted (the debrief content stays visible behind the scrim; dismiss → user keeps reading the debrief). Use `PaywallSheet.show`. The debrief is **not** modified by dismiss; no reload needed there (the scenario list reloads on its own next visit, and a purchase still resolves `true`).
  - [ ] If a screen reader, network, or product-unavailable condition means the paywall can't show, fail open silently (no crash, debrief stays).

- [ ] **Task 6 — Product-unavailable + timeout polish (AC: #8; Open-Q2, Open-Q3)**
  - [ ] **Open-Q2 (product unavailable):** if `InAppPurchaseService.loadProduct(kIapWeeklyProductId)` returns null / store unavailable, **do not present a non-functional paywall** — the CTA must never be tappable without a valid product. Recommended: on `SubscriptionFailed('product_unavailable' | 'product_query_failed')` show the Error state with the dismiss enabled (user can leave cleanly); never spin forever. _(The bloc already emits these codes — render them, don't invent new logic.)_
  - [ ] **Open-Q3 (15s timeout vs native sheet):** the bloc's 15s `sheetTimeout` may fire while the user is in the native Face-ID/password sheet. Recommended: the paywall surface should not punish an in-progress native auth — keep the spinner during the native sheet; the bloc's existing `PurchaseTimedOut` only flips to Error after 15s of no store response. If feasible without bloc surgery, note (do not necessarily fix) that suspending the timer on app-background is the ideal; a bloc change is **out of 8.2 scope** unless trivial — flag as a declared deviation if not done.
  - [ ] **Decision D2 = LOCKED (Walid 2026-06-17): INCLUDE Restore.** Add `Future<void> restore()` to `InAppPurchaseService` (wraps `InAppPurchase.instance.restorePurchases()`; restored events already flow through the bloc's `purchaseStream`) and a minimal `Restore purchases` `TextButton` on the paywall (below "Not now" or in the legal row). Apple App Review **requires** a visible Restore affordance for auto-renewable subs — this **closes 8.1's deferred F13** (MUST-DO before iOS submission). Add a test that the affordance renders and invokes `restore()`.
  - [ ] **Restore edge case (closes 8.1 F16):** a restore with nothing to restore must NOT show the Success "You're in" state — return to Default with a neutral inline line (e.g. `Nothing to restore.`), no false confirmation. Distinguish a genuine restored subscription (→ verify → `paid`) from an empty restore.

- [ ] **Task 7 — Tests (AC: #1–#9)**
  - [ ] **Rewrite** `client/test/features/paywall/views/paywall_sheet_test.dart` for the new design (the current assertions target the placeholder: "Unlock all scenarios", "Subscribe — $1.99/week", radius 42, fill `AppColors.textPrimary`). New assertions: copy deck verbatim, radius 16, the 4 states, `pop(true)` on `SubscriptionPurchased` (G2), dismiss paths, `PopScope` gating, accessibility semantics (price/CTA/dismiss labels). Drive via `PaywallSheet.debugBlocBuilder` + `MockSubscriptionBloc` + `whenListen`.
  - [ ] AC1 gate tests in `scenario_list_screen` tests: free user + paid scenario → call-icon tap shows paywall, **no `initiateCall`** fired; free user + free scenario → normal flow; paid user → never gated.
  - [ ] FR29 test (if D1 accepted): `DebriefScreen(presentPaywallOnLoad: true)` presents the paywall on load; `false` does not. Thread-through assertion in the call-ended → debrief route test.
  - [ ] Follow client test gotchas: `FlutterSecureStorage.setMockInitialValues({})` in every `setUp`; `registerFallbackValue` concrete events (#2); **never `pumpAndSettle`** with the spinner — use `pump(Duration)` (#3); force phone viewport `setSurfaceSize(Size(320, 480))` for the iPhone-SE overflow check (#7).

## Dev Notes

### 1. The plumbing you REUSE (built in Story 8.1 — do not rebuild)

All under `client/lib/features/subscription/`:

- **`services/in_app_purchase_service.dart`** — `const kIapWeeklyProductId = 'stt_weekly_199'` (matches the server default `IAP_PRODUCT_ID`, leave unset server-side). Methods: `Stream<List<PurchaseDetails>> get purchaseStream`, `Future<bool> isAvailable()`, `Future<ProductDetails?> loadProduct(String productId)` (null = store didn't return it), `Future<bool> buy(ProductDetails)` (bool = "request sent" only), `Future<void> complete(PurchaseDetails)`. **No `restore()` yet** — Decision D2 adds it if accepted.
- **`models/subscription_status.dart`** — `SubscriptionStatus { tier, productId?, expiresAt?, status; bool get isPaid => tier == 'paid'; }`, manual `fromJson`.
- **`repositories/subscription_repository.dart`** — `SubscriptionRepository(ApiClient)` → `Future<SubscriptionStatus> verifyPurchase({platform, productId, verificationData})` POSTs `/subscription/verify`, unwraps `data`, propagates `ApiException`.
- **`bloc/subscription_bloc.dart` (+ `_event.dart`, `_state.dart`)** — `SubscriptionBloc({required repository, required iapService, Duration sheetTimeout = 15s})`.
  - **Events** (sealed): `SubscribePressed`, `PurchaseUpdated(List<PurchaseDetails>)` (internal), `PurchaseTimedOut` (internal).
  - **States** (sealed): `SubscriptionInitial`, `SubscriptionLoading`, `SubscriptionPurchased`, `SubscriptionFailed(String code)`, `SubscriptionCancelled`.
  - Failure `code` values the UI keys on: `product_unavailable`, `product_query_failed`, `buy_failed`, `timeout`, `verification_failed`, plus passthrough store/server codes. The bloc listens to `purchaseStream` for its whole lifetime; the 15s timeout only flips UI state.

**Server (DONE — do NOT touch):** `POST /subscription/verify` (auth) → `{data: {tier, product_id, expires_at, status}, meta}`; errors `402 PURCHASE_INVALID`, `409 PURCHASE_CONFLICT` (cross-user replay), `503 SUBSCRIPTION_UNAVAILABLE` (config missing — current prod state until store config + D4 land). Tier flip via migration 014. **Tier is server-owned**: the client learns it ONLY from `GET /scenarios` `meta` (`CallUsage.fromMeta` → `tier`, `calls_remaining`, `calls_per_period`, `period`). There is no `/user/profile` yet (that's 8.3). After purchase, refresh tier by dispatching `LoadScenariosEvent` — **already wired at the call sites**. Never set tier locally.

### 2. The binding design spec

[paywall-screen-design.md](../planning-artifacts/paywall-screen-design.md) is the **fully-resolved, Walid-approved** Story-2.5 output, explicitly "Consumed by: Epic 8, Story 8.2." Build to it exactly — it specifies layout (px gaps), the 4 states, animations, accessibility announcements, contrast math, and widget mapping. **No new design pass is needed.** Key copy deck (verbatim):

| Slot | String |
|---|---|
| Title | `Speak English for real` |
| Subtitle | `Practice with characters who won't go easy on you.` |
| Price | `$1.99` + `per week` (two lines — NOT "$1.99/week") |
| Benefit 1 | `All scenarios unlocked.` |
| Benefit 2 | `Daily calls. Daily progress.` |
| Benefit 3 | `Know exactly what you're doing wrong` |
| CTA | `Let's go` |
| Dismiss | `Not now` |
| Legal | `Auto-renewable. 3 calls per day. Cancel anytime.` |
| Success title | `You're in` |
| Error | `Something went wrong. Try again.` |

**Form factor = Material `showModalBottomSheet`** (resolved over full-screen by the design; keep the existing `PaywallSheet.show` mechanism — NOT a GoRoute). Screen-reader announcements, focus order, live-region politeness, and the 5s screen-reader success hold are all specified in the design's Accessibility section — implement them for AC#6.

### 3. Entry points — current code state (where AC1/AC2 live)

`client/lib/features/scenarios/views/scenario_list_screen.dart`:
- **AC2 (BOC) — DONE:** `_OverlayHost.onPaywallTap` (≈line 142) already does `PaywallSheet.show` + reload-on-true.
- **`CALL_LIMIT_REACHED` — DONE:** `_startCall`'s `ApiException` switch (≈line 344) already routes to the paywall.
- **AC1 (paid-scenario tap) — MISSING:** `Scenario.isFree` (parsed from `is_free`) is **never consulted** in `_onCallTap`/`_startCall`. There is currently NO "free user taps call on a paid scenario → paywall" gate. **You add it** (Task 3). `CallUsage.isFree` and `Scenario.isFree` both already exist — use them.
- The call flow has a `_initiating` debounce held across the whole flow and a Story-7.4 briefing gate in `_onCallTap`/`_onCardTap` before `_startCall`. The paid gate in `_onCallTap` must fire **before** the briefing push (call-icon → paywall directly); the gate in `_startCall` covers the browse→briefing→"Pick up" path.

### 4. FR29 (AC3) — the one genuinely new mechanism (Decision D1)

There is **no free-scenario counter anywhere** today (grep-confirmed; FR29 lives only in planning docs). The debrief is reached post-call via `CallScreen → CallEndedScreen._exit() → pushReplacement(DebriefScreen)` (NOT the `/:scenarioId` GoRoute, which still points at `DebriefPlaceholderScreen`). `DebriefScreen` is a **StatefulWidget, no bloc** (mirrors `CallEndedScreen`), with a 3-phase state machine + poll fallback. The post-call flow does **not** currently carry `CallUsage`.

**LOCKED — Decision D1 (Walid 2026-06-17): implement in 8.2 — derive the trigger at call-init, thread a bool to the debrief.** `usage.isFree && usage.callsRemaining <= 1` at `_startCall` time uniquely identifies the 3rd/last free scenario (3 calls lifetime). No extra network call; no dependency on the not-yet-built profile endpoint. Cost = threading one `bool` through `CallScreen` → `CallEndedScreen` → `DebriefScreen` (stable 7.x files — touch carefully, keep the `debugDebriefRouteBuilder`/`debugBlocBuilder` test seams).

_(Not chosen — for the record: the alternative was to defer FR29/AC3 to Story 8.3, where `GET /user/profile` gives a clean server-side signal. Walid chose to implement now — FR29 is the PRD's emotional-peak conversion moment.)_

### 5. Design-rulebook note (resolved — no action needed beyond awareness)

The cross-screen rulebook "The Handler's Brief" (project memory `project_design_rulebook_handlers_brief`, Walid-validated 2026-06-12) mandates one left rail / nothing centered / accent-never-as-text-or-icon, for the **dark** one-rail screens. The paywall is a **light, transactional commerce sheet** authored earlier (2026-04-02) with a deliberately **centered** layout and **accent-green check icons** — a different surface class. **Decision D5 (baked in): follow the dedicated paywall-screen-design.md** (centered, green decorative checkmarks). The paywall's copy already satisfies the rulebook's banned-copy lint (no exclamations/praise/emoji/urgency; "Let's go"/"Not now" are short, neutral, A2/B1-parseable). If you prefer to neutralize the green-icon tension, recoloring checkmarks to `#1E1F23` is acceptable — but the design's accent checks are the approved default.

### Project Structure Notes

- New/changed files stay inside the established feature dirs — no structural drift:
  - `client/lib/features/paywall/views/paywall_sheet.dart` (restyle — the file already exists)
  - `client/lib/features/subscription/services/in_app_purchase_service.dart` (only if D2: add `restore()`)
  - `client/lib/features/scenarios/views/scenario_list_screen.dart` (AC1 gate + FR29 flag compute)
  - `client/lib/features/call/views/call_screen.dart` + `call_ended_screen.dart`, `client/lib/features/debrief/views/debrief_screen.dart` (FR29 thread, if D1=implement)
  - `client/lib/core/theme/app_colors.dart` + `client/test/core/theme/theme_tokens_test.dart` (paywallError token)
  - `client/test/features/paywall/views/paywall_sheet_test.dart` (rewrite) + scenario-list / debrief tests
- Conventions (architecture.md + client/CLAUDE.md): BLoC + repository + `showModalBottomSheet` (not GoRoute) + MD3 dark tokens + `snake_case`↔`camelCase` `fromJson`. DI for the sheet stays local (`BlocProvider.create` inside `PaywallSheet.show` + the `debugBlocBuilder` seam) — do **not** promote `SubscriptionBloc` to the app-level `MultiBlocProvider`.

### References

- [epics.md → Epic 8 → Story 8.2](../planning-artifacts/epics.md) — user story + ACs (verbatim above)
- [prd.md → Monetization (FR28–FR31), In-App Purchase Integration, NFR11/NFR26](../planning-artifacts/prd.md) — $1.99/week, free=3 calls lifetime, paid=3/day, native-only billing, optimistic-then-validate
- [paywall-screen-design.md](../planning-artifacts/paywall-screen-design.md) — **binding** layout, copy, 4 states, a11y, animations, Open Questions Q1–Q3
- [ux-design-specification.md → invisible tiers (UX-DR16), BottomOverlayCard (UX-DR5)](../planning-artifacts/ux-design-specification.md)
- [architecture.md → Frontend Architecture, FR→Structure Mapping, API Response Format](../planning-artifacts/architecture.md) — BLoC/GoRouter/Dio/MD3, tier server-owned, `{data}/{meta}/{error}`
- Story 8.1 spec: [8-1-integrate-storekit-2-and-google-play-billing.md](8-1-integrate-storekit-2-and-google-play-billing.md) — the plumbing + deferred F13 (Restore)
- `client/CLAUDE.md` — Flutter gotchas (#1 secure-storage mock, #2 sealed fallback, #3 no `pumpAndSettle`, #6 no hex literals, #7 phone viewport, #10 inline error UX)

## On-Device Smoke Gate (Client — Android; iOS blocked until 10-4)

> Client-only story → the server "Smoke Test Gate" is intentionally omitted (zero server/DB/deploy impact). This is the on-device gate instead. **The real purchase path is BLOCKED on store config (Story 8.1 Decision D4 — Google Play account not yet created; Apple sandbox needs `APPLE_ACCEPT_SANDBOX=1`).** So this gate validates everything *except* a completed real purchase; the purchase-completion half stays owed until store config lands (track with 8.1's on-device gate). iOS is fully blocked until Story 10-4 (no iOS build pipeline).

Testable now on a Pixel 9 from a release APK (no real purchase needed):
- [ ] **AC1** — as a **free** user, tap the call icon on a **paid** scenario → the paywall sheet appears; **no call starts**. (Reset user to free/paid + reset quota as needed — see [[infra_reset_daily_call_quota]].)
- [ ] **AC4/AC8 visual** — the sheet matches the design: title/subtitle/$1.99·per week/3 benefits/`Let's go`/`Not now`/legal, light surface, radius 16, no overflow on the device.
- [ ] **AC5** — `Not now`, system back, swipe-down, and scrim-tap all dismiss cleanly back to the unchanged scenario list; tapping the same paid scenario again re-opens it (no nag, no lockout).
- [ ] **AC2** — tap the BottomOverlayCard (free state) → same paywall.
- [ ] **AC3 (if D1=implement)** — drive a free user to their 3rd free call; on the debrief, the paywall auto-appears at load; dismiss → debrief stays readable.
- [ ] **AC6** — with TalkBack on, the sheet announces the price + value prop + CTA/dismiss; targets are reachable.
- [ ] **Purchase completion (OWED until store config):** tapping `Let's go` → native Play sheet → on success the sheet shows `You're in`, resolves, and the list reflects `paid`. _Cannot run until the Google Play product + signed AAB on Internal testing exist (8.1 D4)._

## Pre-Dev Decisions (all RESOLVED — ready for `dev-story`)

| # | Decision | Resolution | Notes |
|---|----------|------------|-------|
| **D1** | **FR29 / AC3 scope** | ✅ **LOCKED (Walid 2026-06-17): IMPLEMENT in 8.2.** Derive `isFinalFreeScenario` (`free && callsRemaining<=1`) at call-init, thread a bool to the debrief, auto-present paywall on debrief load (0ms). | The debrief trigger is the PRD's "emotional-peak" conversion moment (capability #6). Cost = threading one bool through the call→debrief chain. |
| **D2** | **Restore Purchases (8.1 F13)** | ✅ **LOCKED (Walid 2026-06-17): INCLUDE** a minimal `Restore purchases` affordance (+ `InAppPurchaseService.restore()`). | Closes 8.1's deferred F13 (Apple-required for iOS submission); the paywall is its canonical home. Empty-restore must not fake Success (F16). |
| D3 | Error color token | ✅ Baked in: **add `AppColors.paywallError #C0392B`** (count 15→16) for WCAG AA (4.7:1) on the light surface. | `destructive #E74C3C` fails AA on `#F0F0F0`. Design did the contrast math. |
| D4 | Sheet radius | ✅ Baked in: **16** (design doc) over the placeholder's 42. | Design-doc authority; declared deviation. |
| D5 | Centered layout + green checks vs "Handler's Brief" rail | ✅ Baked in: **follow paywall-screen-design.md** (centered, accent checks). | Transactional commerce sheet ≠ the dark one-rail screens; checks decorative/`ExcludeSemantics`. |

## Dev Agent Record

### Agent Model Used

(to be filled by dev-story)

### Debug Log References

### Completion Notes List

### File List
