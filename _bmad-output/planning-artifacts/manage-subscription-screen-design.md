# Manage Subscription Screen — Design Specification
Status: binding (Story 8.3)

> Buildable once the two named dependencies in §10 clear. The screen is dark-surface, route-pushed, and reuses the existing `SubscriptionBloc`, `PaywallSheet`, `EmpatheticErrorScreen`, and `AppToast` plumbing. Every token below is verbatim from `client/lib/core/theme/`. One prerequisite gates the **paid** view (a hard blocker, not a soft risk): the steady-state data source `GET /user/profile` (Story 8.3 Task 2). Copy is locked (Walid 2026-06-18: paid-plan display label `Premium`; CTAs `Subscribe` / `Manage subscription`). The **free** view is fully buildable today against the existing `CallUsage` data.
>
> _Origin: produced by a multi-agent design workflow (our design-DNA analysis + current mobile-UX research + platform-compliance research → synthesis → two adversarial critiques [design-DNA fit + mobile ergonomics/a11y] → finalize). 2026-06-18._

---

## REDESIGN AMENDMENT — hero-ring (2026-06-18, supersedes the flat status block below where they conflict)

The first build shipped the §3 flat status block (eyebrow + plan + calls line). Walid rejected it on device as **empty / not pretty**, and flagged a mis-calibrated Restore button. A second multi-agent design pass (3 concepts → 4 adversarial critics → synthesis) produced the binding hero-ring redesign now implemented in `manage_subscription_screen.dart`:

- **Focal hero ring (the debrief gauge visual language).** A centered 180px ring (stroke 12, `gaugeTrack` groove, `accent` value arc — the exact `_ScoreGaugePainter` geometry, 270° speedometer) that **sweeps in once over 700ms** (`Curves.easeOutCubic`, reduce-motion paints the final frame, no count-up). This is the screen's center of gravity and fills the void purposefully (on-brand, no foreign motif).
- **FREE = usage ring.** Arc fraction = `callsRemaining / callsPerPeriod` (full when calls remain, drains as spent — ring and number always agree; a fresh user sees a near-full ring, not the old empty void). Bore shows the **count only** (`AppTypography.display`, `FittedBox`); **no inner label** (`'calls left'`/`'CALLS LEFT'` dropped). Caption below (centered, `MergeSemantics`): `'Free plan'` + `'{n} of {cap} free calls left'` (verbatim).
- **PAID = membership medallion, NOT a daily meter.** Arc fraction = **1.0** always (a full ring = active entitlement). A paid `/user/profile` is a point-in-time daily count, so a `remaining/cap` ring would show an *alarming empty ring on Premium at end of day* — so the paid ring does NOT visualize the daily allowance. Bore shows the word **`Premium`** (`AppTypography.headline`, `FittedBox`); caption = `'$1.99 per week'` + `'Renews {date}'` (the plan word is in the ring, not repeated).
- **State D (expired/reverted-free)** = the free ring + a quiet `'Subscription ended {date}'` line in `textSecondary` (historical, never red). **Loading** = groove-only ring (`fraction:0`) + the two dim bars. **Error** = `EmpatheticErrorScreen` (unchanged).
- **Restore affordance fixed.** Replaced the full-width zero-padding left-glued `TextButton` (label glued left, full-width highlight flash) with a **centered, intrinsic-width `StadiumBorder` text button** (`textSecondary` chrome ink, ≥48dp, padding 16, ripple hugs the label). In-flight → bounded spinner + disabled. Present in every purchasable state (Apple 3.1.1).
- **Restore moved OUT of the paywall** (Walid 2026-06-18) — it lives only here now; the paywall is a pure buy moment.
- **F17** — the new `_kRestorePending = 'Waiting for approval.'` restore-outcome copy (Ask-to-Buy / SCA hold) + the `SubscriptionCancelled` branch (clears the message) were added to `_onSubscriptionState`.
- **Tokens / copy:** ZERO new `AppColors` (count stays 16) and ZERO new shared typography token; the new consts are dimension/timing locals (the `_kGaugeSize` precedent). Two-ink intact (accent is fill-only on the arc + CTA). CTAs = `StadiumBorder` accent pills matching "Pick up". The `'PLAN'` eyebrow is dropped (the ring + caption carry the hierarchy).

### Action-block refinement (2026-06-18, 2nd pass — supersedes §5 button emphasis + footer)

A follow-up UX/parcours + store-compliance design pass (3 footer treatments → 3 critics → synthesis) set the bottom action block:

- **Asymmetric CTA emphasis by tier.** FREE `Subscribe` stays the LOUD accent FILL pill (the conversion we want). PAID `Manage subscription` becomes a **quiet neutral-OUTLINED pill** — transparent fill, **1px `textSecondary` border**, **`textPrimary` label**, same `StadiumBorder`+48 geometry. We don't push a paying user toward the exit, but the exit is never hidden/faint/buried (full-width, 48dp, 13.5:1 label, ~4:1 border — Apple 3.1.1 + anti-dark-pattern satisfied). **Two-ink intact: accent is FILL-only** (free pill + ring arc), NEVER a border/text — so the outline uses a neutral border, not accent. (`OutlinedButton` with an explicit `side` in both states so Material can't recolor it to a theme default.)
- **Restore moved BELOW the primary CTA**, into the pinned block (`CTA → 16 → Restore → [msg] → cardGap 12 → Terms·Privacy`). Quieter, cleaner hierarchy; still its centered `StadiumBorder` text button, still reachable + enabled in every purchasable state (free/paid/loading) → Apple 3.1.1.
- **"Auto-renewable. Cancel anytime." DROPPED from the status footer. Compliance verdict: COMPLIANT** — Apple 3.1.2 / Google Play attach the auto-renew disclosure to the POINT OF SALE; the paywall retains the full disclosure there, so a post-purchase status screen carries no separate duty. `Terms · Privacy` links kept (hygiene); footer is now tier-independent.
- Zero new tokens; `Colors.transparent` is a Material const (not a scanned hex literal).

Everything in §§4–9 below about data source, copy locks (`Premium`/`Subscribe`/`Manage subscription`/`Restore purchases`), navigation, a11y, safe zones, and the no-new-token discipline still holds; the §3 *visual layout* is superseded by the ring hero, and the §5 *button emphasis + footer* by the action-block refinement above.

---

## 1. Purpose & scope

A single, flat **account/subscription status screen** reached from a quiet hub affordance. It shows the user where they stand and offers the one right action:

- **Free user** → see "Free plan" + remaining free calls, and a single honest **Subscribe** action that opens the existing `PaywallSheet`.
- **Paid user** → see plan + price + **renewal/expiry date** + a **Manage subscription** action that hands off to the OS (App Store / Play), plus **Restore purchases**.

**What it must NOT become:**

- **Not a settings hub.** No profile editing, no notifications, no language, no logout pile-up. The "three-screen minimalism / no settings screen" rule (ux-design-specification.md §47/§206) stands — this screen is *subscription status only*, justified by FR30/FR31 (Story 8.3 AC1/AC5). Resist scope creep into an "Account" page.
- **Invisible tiers preserved.** The Scenarios hub must not gain tier badges, locks, "PRO" ribbons, or "Upgrade!" furniture on the scenario cards (UX-DR16). The cards stay exactly as they are. The entry point is one quiet, tier-neutral grey line (§2).
- **No commerce dark patterns.** Cancel is never buried, never styled faint-against-bright; no fake urgency, no confirm-shaming, no retention interrogation. Cancellation is the OS handoff — symmetric with subscribing.

This is the **dark app surface** (`AppColors.background` = `#1E1F23`), not the light paywall sheet. The light `#F0F0F0` treatment is reserved for the *purchase moment* (the paywall). A status screen reached from inside the app is dark, like debrief / briefing / error.

---

## 2. Entry point on the Scenarios hub

### Placement

The hub column is built in `_ListState.build` (`scenario_list_screen.dart`, the `Column` whose first child is `_DifficultyHubLine`). Top → bottom it is: `_DifficultyHubLine` → `SizedBox(height: AppSpacing.cardGap)` → `Expanded(ListView.separated)` → (pinned via the parent `Stack`) `BottomOverlayCard`.

`_DifficultyHubLine` is **right-aligned** (`MainAxisAlignment.end`). The new account affordance is a **second hub line, also right-aligned (trailing), stacked directly above the difficulty line** — both share the hub's existing horizontal envelope. Two reasons this is trailing, not leading:

1. **Edge-gesture safety.** A left-leading, full-bleed `GestureDetector` with `HitTestBehavior.opaque` sits exactly in the iOS edge-swipe-back / Android predictive-back origin strip and can swallow the *start* of an edge swipe on some OEM skins. The team has fought predictive-back before (ADR 003); keep all opaque hit areas out of the left gutter. Trailing placement keeps it clear.
2. **Overflow safety.** Two affordances on one `Row` (one leading, one trailing) overflow horizontally on a 320-wide device at 200% text scale. Two stacked single-affordance rows wrap cleanly.

```
                                                  [♺  Account]   ← new, trailing
                                                  [⚙  Difficulty: Hard]   ← existing
────────────────────────────────────────────────────────────────────────────
  <scenario cards…>
```

(Glyphs above are schematic. Real glyphs: difficulty uses `Icons.tune`; account uses `Icons.account_circle_outlined`. Both render in `AppColors.textSecondary` grey — no colored status dot, no gear.)

### Exact treatment

A new private widget `_AccountHubLine`, mirroring `_DifficultyHubLine` exactly (the established quiet-hub idiom):

- `Icon(Icons.account_circle_outlined, size: 15, color: AppColors.textSecondary)`.
- `SizedBox(width: 6)`.
- `Text('Account', style: TextStyle(fontFamily: AppTypography.fontFamily, fontSize: 13, fontWeight: FontWeight.w500, color: AppColors.textSecondary))` — the same inline `TextStyle` recipe `_DifficultyHubLine` uses, copied verbatim. No new typography token.
- `Row(mainAxisAlignment: MainAxisAlignment.end, …)` — trailing, like the difficulty line.
- Wrapped in `GestureDetector(behavior: HitTestBehavior.opaque, onTap: …)`.
- **Horizontal envelope: inherit the parent's `AppSpacing.screenHorizontalScenarioList` (18).** Add NO extra horizontal padding — the line must sit on the same 18-rail as `_DifficultyHubLine` and the cards. (Do not use `screenHorizontal` = 20 here; that is the *screen* rail in §3, not the hub rail.)

**Label copy:** `Account` — one word, tier-neutral, identical for free and paid users (invisible tiers: the hub never advertises status; the *screen* differentiates). A2/B1, no badge, no count, no "Premium"/"Upgrade".

**Tap target:** the visible glyph + text is ~15 dp tall. `_DifficultyHubLine` today wraps its content in `Padding(symmetric(vertical: 4))`, which is below the 44 dp floor. The new line should not copy that shortfall: wrap the tappable content so the gesture box is **≥ `AppSpacing.minTouchTarget` (44)** tall — e.g. `ConstrainedBox(constraints: BoxConstraints(minHeight: AppSpacing.minTouchTarget))` around a vertically-centered `Row`. 44 dp is the hard floor (WCAG 2.1 AA + iOS HIG, and the value the codebase's back arrows already use); do not shrink the hit area to the glyph.

**Why it stays quiet:** `textSecondary` grey reads as chrome, not a CTA; it is weight/position-neutral; it carries no tier signal; it is a rare, deliberate affordance (account is infrequent), which is exactly the kind of action that may sit slightly out of the primary thumb zone.

Both free and paid users see the same single `Account` line (see §10 R1 for the open product question of whether this affordance ships for both tiers or paid-only).

---

## 3. Screen layout

**Dark app surface, full screen, route-pushed (§8). No AppBar, no nav bar** — matching the briefing and error precedents.

The body uses the **pinned-CTA structure** proven by `EmpatheticErrorScreen` (`empathetic_error_screen.dart`): scrolling content in an `Expanded(SingleChildScrollView(…))`, and the **primary CTA pinned as a sibling below it** — never absorbed into the scroll view. This guarantees the primary action lands in the low thumb zone regardless of content height, and that it clears the home indicator.

```dart
Scaffold(
  backgroundColor: AppColors.background,
  body: SafeArea(
    top: true,
    bottom: true,                       // primary CTA sits low → bottom inset honored
    child: Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.screenHorizontal,   // 20 — deliberate screen rail
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Back arrow + title + status block + secondary action scroll here.
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [ /* §3 top→bottom, ending with Restore */ ],
              ),
            ),
          ),
          // Primary CTA pinned as a sibling (Manage / Subscribe) + legal footer.
          /* §5 */
        ],
      ),
    ),
  ),
)
```

One left rail, nothing centered, **zero furniture** — no cards, no dividers, no per-section icons. Spacing does the grouping.

### Scrolling content, top → bottom

**1. Back affordance** (top-left):
- `SizedBox(width: AppSpacing.minTouchTarget /*44*/, height: 44)` wrapping `IconButton(padding: EdgeInsets.zero, iconSize: AppSpacing.iconSmall /*24*/, color: AppColors.textPrimary, icon: Icon(Icons.arrow_back_ios_new), onPressed: () => context.pop())`, inside `Semantics(button: true, label: 'Back to scenarios')`. 44 dp box around a 24 dp glyph gives 10 dp slop per side — the codebase's established back-arrow size.
- `Icons.arrow_back_ios_new` (the chevron) is the deliberate cross-platform choice — the app standardizes on the iOS chevron on Android too, for visual consistency. A chevron carries heavy left optical whitespace; nudge the glyph right by **8 dp** (the established arrow optical-inset value) so it sits on the 20 rail.
- Gap below: `SizedBox(height: AppSpacing.screenVerticalList /*30*/)`.

**2. Screen title:**
- `Text('Subscription', style: AppTypography.headline.copyWith(color: AppColors.textPrimary))` (18/w600), inside `Semantics(header: true)`.
- Gap: `SizedBox(height: 32)` (local per-screen rhythm, inline `SizedBox` — the briefing/debrief convention).

**3. Status block** (no card — spacing + weight carry it):
- **Eyebrow** — a local `const TextStyle` mirroring the briefing `_eyebrowStyle` (12/w500/`letterSpacing: 1.0`/`AppColors.textSecondary`):
  ```dart
  const TextStyle _eyebrowStyle = TextStyle(
    fontFamily: AppTypography.fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w500,
    letterSpacing: 1.0,
    color: AppColors.textSecondary,
  );
  ```
  Render `Text('PLAN', style: _eyebrowStyle)`. **Do not** use `AppTypography.label` + `copyWith(letterSpacing:)` — `AppTypography.label` carries no tracking; the eyebrow idiom is a standalone `const TextStyle`, exactly as briefing and debrief declare it. This is the one style on the screen that does not map to an `AppTypography` token (no new token is added — it is a local `const`, the `_DifficultyHubLine` / content-warning-sheet precedent).
- `SizedBox(height: AppSpacing.base /*8*/)`.
- **Plan line** (the data, primary ink): `Text(<plan>, style: AppTypography.bodyEmphasis.copyWith(color: AppColors.textPrimary))` (16/w500) — "Free plan" (free) or "Premium" (paid); see §4.
- `SizedBox(height: AppSpacing.cardTextGap /*5*/)`.
- **Detail lines** (metadata): price + period, renewal/expiry date, etc. One `Text` per fact, stacked, `SizedBox(height: 4)` between. **Ink: `AppColors.errorBody` (#D8D8D8, documented 11.4:1 on background).** See the contrast note below. Exact strings in §4.
- Gap before the secondary action: `SizedBox(height: 40)` (the briefing "after-lockup" rhythm).

**4. Secondary action — `Restore purchases`** (§5), the last item *inside the scroll column*, separated from the pinned primary by the scroll/pin boundary plus the explicit gap in §5.

### Pinned below the scroll

**5. Primary CTA** (`Manage subscription` / `Subscribe`) pinned as a sibling — §5.

**6. Legal footer** (paid + free), beneath the primary, ink `AppColors.textSecondary`, with `SizedBox(height: AppSpacing.screenVerticalList /*30*/)` (or the pinned-button's `fromLTRB(…, 30)` bottom padding) so it never kisses the home indicator. See §5 for copy and link treatment.

> **Contrast — verified.** `AppColors.textSecondary` (#8A8A95) on `background` (#1E1F23) is **4.82 : 1** — it clears WCAG AA (4.5 : 1) for normal text, but with little headroom. Use `textSecondary` only for genuinely secondary chrome (the legal footer, the hub line). For the **status detail data the user came to read** (price, renewal/expiry date), use **`AppColors.errorBody`** (#D8D8D8, 11.4 : 1) — the documented dark-surface secondary ink, the same token the error screen body uses. **Never** carry `overlaySubtitle` (#4C4C4C) onto this dark surface: that token is validated only on the *light* paywall (5.7 : 1 on `textPrimary`) and fails AA on `background`.

> **No new color or typography token.** Every style is an existing `AppColors` value or an `AppTypography` style + `.copyWith(color:)`, plus the one local `const _eyebrowStyle`. **Do not add to `AppColors`** — it would break `theme_tokens_test.dart`'s `count == 16` assertion and force a UX-DR1 amendment for nothing. No inline `Color(0x…)` anywhere in the new files (the static hex-literal scan covers all of `lib/` outside `lib/core/theme/`).

---

## 4. Content by state

**Data source (steady state): `GET /user/profile`** → `{ tier, calls_remaining, calls_per_period, period, subscription_expires_at }`.

> This endpoint is delivered by Story 8.3 Task 2 (see §10 R2 — it is a hard prerequisite for the paid view's date). Today, tier/usage are exposed only via `/scenarios` meta → `CallUsage` (`tier`, `callsRemaining`, `callsPerPeriod`, `period`), which has **no expiry field**. Tier canonical values are `'free'` / `'paid'` (ADR 002); reuse the existing `CallUsage.isFree` (`tier == 'free'`) and `SubscriptionStatus.isPaid` (`tier == 'paid'`). A new `UserProfile` model mirrors these.

**Date formatting:** render `subscription_expires_at` (ISO 8601) as `d MMM yyyy` → "18 Jul 2026", via `intl`'s `DateFormat`. **`intl` is not yet a dependency — add it** (or write a tiny local month-name formatter). Never show the raw ISO string.

```dart
// COPY LINT — banned everywhere on this screen (The Handler's Brief, 2026-06-12):
//   no exclamation marks, no question marks in chrome, no praise
//   ("Good luck", "You've got this"), no emoji, no "don't worry",
//   no tips, no urgency cues. Tone: clinical, the app's voice.
//   A2/B1 parseability is required for all learner-facing copy; the sole
//   sanctioned exception is the store-mandated "Auto-renewable" disclosure
//   (see §5 legal), which ships as a compliance carve-out, NOT clean copy.
//   This is a data/utility screen: it intentionally exceeds the 2-voiced-slot
//   narrative budget (title + status + CTAs + legal). That is correct for a
//   status surface; the budget governs narrative beats, not utility chrome.
//   CTA strings are fixed + diegetic — Walid-approved 2026-06-18:
//   paid-plan display label "Premium"; CTAs "Subscribe" / "Manage subscription".
```

### A. Free user (`tier == 'free'`)
- Eyebrow: `PLAN`
- Plan line: `Free plan`
- Detail line (calls): `{calls_remaining} of {calls_per_period} free calls left` → e.g. "2 of 3 free calls left". *(`period == 'lifetime'` for free → no "per day" suffix.)*
- No renewal date, no Manage action (nothing to manage).
- Actions: **Subscribe** (primary) + **Restore purchases** (secondary). §5.

### B. Paid — active, renews (`tier == 'paid'`, future `subscription_expires_at`, auto-renew on)
- Eyebrow: `PLAN`
- Plan line: `Premium`
- Detail lines:
  - `$1.99 per week` *(prefer the live `ProductDetails.price` if loaded, else the static `$1.99 per week`; product id `stt_weekly_199`.)*
  - `Renews {date}` → "Renews 18 Jul 2026"
- Actions: **Manage subscription** (primary) + **Restore purchases** (secondary).

### C. Paid — cancelled but active until expiry (`tier == 'paid'`, future expiry, auto-renew off)
- Plan line: `Premium`
- Detail lines:
  - `$1.99 per week`
  - `Access until {date}` → "Access until 18 Jul 2026" *(stated as fact, no fear hook)*
- Actions: **Manage subscription** + **Restore purchases**.

> State C requires an auto-renew/cancelled flag that `GET /user/profile` may not expose (it returns `subscription_expires_at`, not necessarily a renewal-info boolean). **If that flag is unavailable, default the paid line to `Renews {date}`** and treat C as a later refinement gated on the store renewal-info flag. Do not fabricate a cancelled state the data can't back. See R3.

### D. Expired / reverted (`tier == 'free'`, past `subscription_expires_at`)
- Treated as a free user (tier is the source of truth — the server downgrades on lapse, Story 8.3 D3 sweep/webhooks).
- Plan line: `Free plan`
- Detail line: `{calls_remaining} of {calls_per_period} free calls left` (a reverted user returns to where they were — their pre-paid free-era calls still count, per Story 8.3 D2).
- Optional single line, only if a past expiry is present: `Subscription ended {date}` → "Subscription ended 11 Jun 2026". Flat, factual, no urgency.
- Actions: **Subscribe** + **Restore purchases** (identical to A).

### E. Loading
- **Skeleton of the status block, not a full-screen spinner.** Keep the back arrow + title rendered; replace the plan/detail lines with stable-height placeholders (dim `AppColors.avatarBg` bars at the line heights) so nothing jumps when data lands.
- **Primary CTA disabled while tier is unknown** (don't let a user tap "Manage"/"Subscribe" before we know which it is) — render it in its disabled style.
- **`Restore purchases` stays ENABLED during loading.** Restore does not depend on the profile fetch; a reinstalling payer stuck behind a slow/failing profile load must still be able to restore.
- Announce the resolved status on load (§7).
- **Never render "Free plan" while merely loading** — that would mislead a paying user. Show the skeleton until the profile resolves.

### F. Error / offline (profile fetch failed)
- **Graceful, calm, in-place** — the project's inline-error / "graceful bounce over retry banner" pattern, NOT a dialog or red snackbar.
- **Reuse `EmpatheticErrorScreen`** (`client/lib/core/widgets/empathetic_error_screen.dart`), wired to a retry that re-fetches the profile:
  ```dart
  EmpatheticErrorScreen(
    code: code,                 // 'NETWORK_ERROR' / 'SERVER_ERROR' / …
    onRetry: () => /* refetch profile */,
    retryCount: retryCount,
  )
  ```
  Its code-driven copy table supplies A2/B1 strings already validated for the app.
- **Render it as a direct child of `Scaffold.body`, NOT inside this screen's `SafeArea` + `Padding` envelope.** `EmpatheticErrorScreen` already supplies its own `SafeArea(top/bottom)` and its own `Padding(horizontal: AppSpacing.screenHorizontalErrorView /*36*/)`. Nesting it inside this screen's `SafeArea` + `Padding(20)` would double the SafeArea and sum the horizontal padding to 56 (visibly cramped). Swap the whole body to the error screen (the `scenario_list_screen.dart` pattern), do not nest it.
- If a last-known tier is cached (e.g. from the most recent `/scenarios` meta), it is acceptable to render that as a degraded view with a quiet retry — but **make clear it is a load failure, not a downgrade**; never silently show "Free plan" on a failed load for a known-paid user.

---

## 5. Actions

All buttons are composed inline from Material widgets per the house recipes (no shared Button widget exists). All tap targets ≥ 44 dp; the primary uses the comfortable 48 dp. The primary is **pinned** (§3); the secondary is the last scrolling item, with an explicit ≥ 24 dp visual separation from the pinned primary so the two full-width controls are never an adjacent fat-finger pair.

### Primary — "Manage subscription" (paid) / "Subscribe" (free)
Full-width accent button, **pinned at the bottom** (low green thumb zone).

- **Grammar:** match the paywall CTA recipe (`paywall_sheet.dart` `_CtaButton`): `SizedBox(width: double.infinity, height: AppSpacing.touchTargetComfortable /*48*/)` wrapping `FilledButton` with `FilledButton.styleFrom(backgroundColor: AppColors.accent, foregroundColor: AppColors.background, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)))`, label 14/w600. **Accent is the fill; the label ink is `background`** — the two-ink rule (never accent-as-text), exactly the paywall's validated commerce combo.
- **Free → "Subscribe":** label `Subscribe`. `onPressed` opens the existing paywall:
  ```dart
  final purchased = await PaywallSheet.show(context);   // Future<bool>
  if (purchased == true && context.mounted) {
    // refetch GET /user/profile (flip to paid) + signal hub reload (§8)
  }
  ```
  Disabled while in Loading.
- **Paid → "Manage subscription":** label `Manage subscription`. `onPressed` is the native handoff via `url_launcher` (`url_launcher: ^6.3.2`, already a dep). The true in-app StoreKit 2 `showManageSubscriptions` sheet is NOT exposed by `in_app_purchase` 3.3.0, so the store URL is the path (deferred polish would add a Swift platform channel):
  - **iOS:** try `https://apps.apple.com/account/subscriptions` first; if `canLaunchUrl` is false / `launchUrl` fails, fall back to `itms-apps://apps.apple.com/account/subscriptions`. Both forms target the native subscriptions pane; the scheme form is the more reliable opener on some iOS versions, so keep it as the fallback rather than dropping it. **The iOS URL is UNVERIFIED on-device** (R4) — confirm on a real device once 10-4 unblocks.
  - **Android:** launch the product-specific deep link
    `https://play.google.com/store/account/subscriptions?sku=stt_weekly_199&package=<applicationId>`
    — **both** `sku` and `package` must be present (`sku` alone is ignored). Obtain `<applicationId>` at runtime from `PackageInfo.fromPlatform()` (**`package_info_plus` is not yet a dependency — add it**); do not hardcode it. The only legitimate fallback is the generic `https://play.google.com/store/account/subscriptions` when `launchUrl` throws — not a "package unresolvable" branch (the package id is always resolvable at runtime).
  - Use `mode: LaunchMode.externalApplication`. If `launchUrl` returns false / throws, surface an inline `Text` in `AppColors.destructive`: `Store did not open. Try again.` — never a dialog. The product id `stt_weekly_199` is `kIapWeeklyProductId`.

### Secondary — "Restore purchases"
A quiet `TextButton`, the **last item in the scroll column** (rare action, kept physically separated from the pinned primary by ≥ 24 dp). `style: TextButton.styleFrom(minimumSize: const Size.fromHeight(AppSpacing.touchTargetComfortable /*48*/), foregroundColor: AppColors.textSecondary)`. Use **`AppColors.textSecondary`** (the dark-surface chrome ink) — **not** `overlaySubtitle`, which is tuned for the light paywall and fails AA here. Label `Restore purchases` (harmonizes verbatim with the paywall's `_kRestore`).

- **Reuse the existing restore flow.** Drive `SubscriptionBloc`: `context.read<SubscriptionBloc>().add(const RestorePressed())`. The bloc already handles both outcomes:
  - On `SubscriptionPurchased` (genuine restore → verified `status.isPaid`) → `AppToast.show(context, message: 'Subscription restored', type: AppToastType.success)` (the success toast is the one sanctioned non-inline confirmation; its accent check is a shared-component exception, not a screen-level two-ink violation) **and** refetch the profile so the view flips to paid.
  - On `SubscriptionRestoreEmpty` (the 3 s `restoreTimeout` lapsed with nothing) → inline chrome `Text('Nothing to restore.', style: AppTypography.caption.copyWith(color: AppColors.textSecondary))` (verbatim with the paywall's `_kNothingToRestore`). **Never** a fake success.
  - On `SubscriptionFailed` → inline `Text` in `AppColors.destructive`, not a snackbar.
- Restore is present in **every** state (A, B, C, D) — Apple Guideline 3.1.1 mandates a visible restore for auto-renewable subscriptions; a reinstalling payer lands here looking "free" until they restore.

### Legal footer (required, bottom)
Both stores require functional Terms (EULA) + Privacy links discoverable for subscriptions. Render the footer as **flat tappable `Text` spans** (`RichText` / `Text.rich` with `TapGestureRecognizer` on the link runs), ink `AppColors.textSecondary` — **not** `TextButton`s, which would add Material ink-splash + min-size button chrome to a zero-furniture screen (the paywall ships its legal line as a flat `Text`, not buttons). Each link run keeps a ≥ 44 dp effective hit height.

- `Terms` → launch the Terms URL (`url_launcher`).
- `Privacy` → launch the Privacy Policy URL.
- The Terms/Privacy URLs are config (App Store Connect / Play already require them) — thread them in, do not ship hardcoded placeholders.
- **Copy differs by tier** (so the disclosure is never inaccurate):
  - **Paid (B, C):** `Auto-renewable. Cancel anytime.` followed by the two links — mirroring the paywall's legal register. "Auto-renewable" is a store-required disclosure and ships as the sanctioned A2/B1 carve-out noted in the copy-lint block — it is compliance copy, not learner-clean copy.
  - **Free (A, D):** drop the "Auto-renewable" sentence (nothing is currently renewing — claiming it would be inaccurate). Show only the `Terms` / `Privacy` links (optionally prefixed by a neutral flat line).

### Action ordering summary
Paid view, top → bottom: status block → `Restore purchases` (scrolling, rarer/higher) → **[scroll/pin boundary, ≥ 24 dp gap]** → `Manage subscription` (pinned `FilledButton` accent, low green zone) → legal footer.
Free view: status block → `Restore purchases` → `Subscribe` (pinned) → legal footer.

---

## 6. Mobile non-clickable / safe zones

- **Top band (status bar / notch / Island):** `SafeArea(top: true)`. Back arrow + title sit below the inset. No manual `SystemUiOverlayStyle` — the dark MD3 theme owns the status bar.
- **Bottom band (home indicator / gesture-nav):** `SafeArea(bottom: true)`, and the **primary CTA is pinned as a sibling below the scroll view** (the `EmpatheticErrorScreen` structure), so it floats above the home indicator by construction. The pinned footer takes the inset directly. If any element ever needs explicit inset padding, use `MediaQuery.viewPaddingOf(context).bottom` (the codebase convention — survives the keyboard), **not** `MediaQuery.of(context).padding`. No tap target under the home indicator.
- **Left/right edges (back-swipe / system-gesture gutters):** all interactive content is inset by `AppSpacing.screenHorizontal` (20) from each vertical edge. **There are no horizontally-draggable controls** (no sliders, carousels, swipe-to-reveal rows) — deliberately, so Android predictive-back and iOS edge-swipe-back are never fought (ADR 003). Buttons are full-width, tap-only, gesture-safe. The hub entry point is trailing-aligned for the same reason (§2).
- **Reachability:** the pinned primary CTA sits low (green zone, ~96% tap accuracy); the back arrow top-left is the accepted platform convention but is paired with the working system back-swipe, so the corner is never *forced*. Restore (rare) sits higher than the primary — mild friction is correct for the less-common action, and the ≥ 24 dp gap prevents a mis-tap between the two full-width controls.

---

## 7. Accessibility

- **Control-level semantics:**
  - Back: `Semantics(button: true, label: 'Back to scenarios')`.
  - Primary `FilledButton` text gives `'Manage subscription'` / `'Subscribe'` → "…, button". Restore → "Restore purchases, button". Legal link runs → "Terms, link" / "Privacy, link".
- **Status as one sentence:** wrap the **plan line + detail lines** in `MergeSemantics` so a reader hears one node — "Free plan, 2 of 3 free calls left" or "<paid label>, renews 18 July 2026". **Do not also wrap the eyebrow in `Semantics(header: true)`** if it is inside the merge: `MergeSemantics` collapses the header role, so the two are mutually exclusive — pick the merged single-sentence reading (recommended) and drop the eyebrow's header role. Read the price as words where natural (mirror the paywall's price-semantics trick: "$1.99" → "one dollar ninety-nine per week").
- **State-change announcements (live regions):**
  - On restore-empty / failure → wrap the inline `Text` in `Semantics(liveRegion: true)` (the paywall does exactly this). Prefer the `liveRegion` wrapper over `SemanticsService.announce`, which carries a deprecated-API trap across Flutter versions (client/CLAUDE.md gotcha #9).
  - On restore success the toast carries the announcement visually + via its own live region.
- **Focus order:** accept the natural top-to-bottom traversal — back arrow → title → status → Restore → primary → legal. (Do not claim focus "lands on the status block": a pushed route lands default focus on the first traversable node, the back arrow, and programmatic focus-on-push is unreliable across TalkBack/VoiceOver. Top-to-bottom order is correct and the back arrow's label is clear.)
- **Dynamic Type to ~200%:** no fixed-height rows that clip text. Status rows are intrinsic-height `Text` in a `Column`; let them wrap. The scroll region handles overflow. (Tests in §10 R5.)
- **Contrast (AA):** `textPrimary` (14.5 : 1) for the title + plan line; `errorBody` (11.4 : 1) for the status detail data; `textSecondary` (4.82 : 1 — passes AA, low headroom) only for the legal footer + hub line; `destructive` (5.2 : 1) for inline failures. **Never** render a label, status word, date, or price in `accent` — green is fill-only here. Status (free vs paid, renews vs ended) is carried by **text**, not color — no colored status dots.

---

## 8. Navigation

- **Push as a real route via the app router.** Add to `AppRoutes`: `static const String account = '/account';` and a `GoRoute(path: AppRoutes.account, pageBuilder: (context, state) => _fadePage(... const ManageSubscriptionScreen()))` using the existing `_fadePage` 500 ms fade transition, consistent with every other route.
- **Entry:** `_AccountHubLine.onTap` does `context.push(AppRoutes.account)` (push, not go — a detail pushed over the hub; back returns to the hub).
- **Data + bloc wiring:** the route reads via a lightweight `UserProfileBloc`/`Cubit` over a `UserRepository(ApiClient())` hitting `GET /user/profile` (mirroring `ScenariosRepository` / `SubscriptionRepository`), and **provides a `SubscriptionBloc`** for the action side (Restore/verify), built the way `PaywallSheet` builds it (`SubscriptionRepository(ApiClient())` + `InAppPurchaseService()`).
- **Pop / back:** the back arrow and the system back-swipe both `context.pop()` (`Navigator.maybePop`). No `PopScope` block needed — there is no in-flight irreversible state on this screen (the paywall sheet owns its own `PopScope` during purchase). Returns to the Scenarios hub.
- **After Subscribe success** (`PaywallSheet.show` returns `true`): refetch `GET /user/profile` so this screen flips to the paid view, **and** signal the hub to reload — the established contract is `context.read<ScenariosBloc>().add(const LoadScenariosEvent())` after a purchase. Since this screen is pushed *over* the hub, refetch this screen's profile immediately; let the hub re-run `LoadScenariosEvent` when it regains focus (or return a `bool` from this route, the paywall pattern).
- **After Restore success:** identical to Subscribe success — refetch profile (flip to paid), success toast, signal hub reload.
- **After Manage handoff:** on app lifecycle resume (user returns from App Store / Play), refetch `GET /user/profile` so a cancel/resubscribe done in the store is reflected (the server may also be ≤ 5 min behind per Story 8.3 D3 polling backstop / near-instant via webhook — a refetch on resume is the instant client path).

---

## 9. Reuse map

| Concern | Reuse (existing) | Build new |
|---|---|---|
| Colors | `AppColors.*` — `background`, `textPrimary`, `errorBody` (status data), `textSecondary` (footer/hub), `accent` (primary fill), `destructive` (inline failure), `avatarBg` (skeleton bars) | **Nothing** (no new token — protects `theme_tokens_test` count==16) |
| Typography | `AppTypography.headline` (title), `.bodyEmphasis` (plan line), `.caption` (details/legal) + `.copyWith(color:)` | Local `const _eyebrowStyle` (12/w500/ls 1.0) like briefing; inline `TextStyle` for `_AccountHubLine` (copy `_DifficultyHubLine`'s) |
| Spacing | `AppSpacing.screenHorizontal` (20, screen rail), `screenHorizontalScenarioList` (18, hub rail), `screenVerticalList` (30), `base` (8), `cardTextGap` (5), `touchTargetComfortable` (48), `minTouchTarget` (44), `iconSmall` (24) | Local section gaps (32 / 40 / 24-gap) as inline `SizedBox` |
| Back arrow | the codebase back-arrow recipe (`SizedBox(44,44)` + `IconButton` zero-pad + `iconSize: 24` + 8 dp optical inset), as in the error/briefing surfaces | A copy in the new screen file |
| Eyebrow | briefing `_eyebrowStyle` recipe | Inline `const` |
| Primary CTA | paywall `_CtaButton` recipe — accent fill / `background` ink / r12 / h48 | Inline |
| Secondary / restore | paywall `TextButton` recipe — but `foregroundColor: AppColors.textSecondary` (not `overlaySubtitle`) for the dark surface | Inline |
| Pinned-CTA + scroll structure | `EmpatheticErrorScreen` `Expanded(scroll)` + pinned-sibling button | Adopt structure |
| Subscribe action | `PaywallSheet.show(context)` → `Future<bool>` | — |
| Restore / verify plumbing | `SubscriptionBloc` (`RestorePressed`, `SubscriptionPurchased`/`SubscriptionRestoreEmpty`/`SubscriptionFailed`), `SubscriptionRepository`, `InAppPurchaseService`, `kIapWeeklyProductId` | — |
| Manage handoff | `url_launcher` (dep) → App Store / Play URLs | A tiny `StoreLinks` helper (platform-branch the two URLs; Android pulls `package` from `PackageInfo`) |
| Loading | — | Skeleton of the status block (dim `avatarBg` bars) |
| Error/offline | `EmpatheticErrorScreen` (code-driven, retry) | Wire `onRetry` to the profile refetch |
| Success confirmation | `AppToast.show(..., AppToastType.success)` | — |
| Inline failure | inline `Text` in `AppColors.destructive` | — |
| Routing | `AppRoutes` + `GoRoute` + `_fadePage` | One new `account` route |
| Data model | mirror `CallUsage` / `SubscriptionStatus` (`isFree`/`isPaid` on `'free'`/`'paid'`) | A `UserProfile` model for `GET /user/profile` |
| New deps | — | `intl` (date format), `package_info_plus` (Android `package` id) |

**Build new (net):** `_AccountHubLine` (hub), `ManageSubscriptionScreen` + its route, a `UserProfile` model + read repository/loader for `GET /user/profile`, a `StoreLinks` platform-URL helper, the loading skeleton, and the two new deps (`intl`, `package_info_plus`). Everything else reuses existing tokens / widgets / blocs.

---

## 10. Open items the build agent must clear

- **R-copy — RESOLVED (Walid 2026-06-18).** Paid-plan display label = **`Premium`**; CTA strings = **`Subscribe`** (free) / **`Manage subscription`** (paid). All Handler's-Brief compliant (1–2 words, verb-first for the CTAs). No further copy sign-off owed. **`Premium` is the user-facing display label ONLY — the tier value stays `'paid'` (ADR 002). Do NOT introduce a `'premium'` tier string** (it would break the `users.tier` CHECK + `compute_call_usage`).

- **R2 (blocker) — `GET /user/profile` does not exist yet.** It is Story 8.3 Task 2 (in-scope, same story). `CallUsage` (from `/scenarios` meta) carries tier + calls but **no `subscription_expires_at`**, so the paid view's renewal/expiry date has no steady-state source until 8.3 ships it. Either (a) sequence this screen after 8.3 Task 2, (b) ship the **free-only** view first (tier + calls from existing `CallUsage`, Subscribe + Restore, no date), then add the paid date when the endpoint lands, or (c) build `GET /user/profile` as part of this work. Do not assume the field is available.

- **R1 (product decision — RESOLVED by Walid 2026-06-18: full-screen route, kept minimal on the hub).** This spec ships a tier-neutral `Account` line to **both** tiers (so a reinstalling/lapsed payer can reach Restore — UX-required) opening a full-screen route. This both honors Walid's D1 ruling ("a real Manage-Subscription screen is fine; keep the hub entry minimal so the user is not disturbed") and the safer invisible-tiers choice (a both-tiers neutral line leaks no tier to an observer). _(This supersedes Story 8.3's earlier paid-only-bottom-sheet default.)_

- **R3 — "Renews" vs "Access until" needs an auto-renew flag the profile may not expose.** Without it, default to `Renews {date}` and treat state C as a refinement gated on the store renewal-info flag. Do not fabricate a cancelled state.

- **R4 — store handoffs are unverified on-device.** The iOS manage URL form is UNVERIFIED until 10-4 (use the `https` → `itms-apps` fallback per §5). The true in-app iOS manage sheet is unavailable in `in_app_purchase` 3.3.0 (URL fallback is compliant today). All on-device iOS verification is blocked until CodeMagic / Story 10-4; Android live purchase/restore is blocked until the Google Play account exists + a signed AAB is on Internal testing. The URL handoff + screen layout are testable now (widget tests; Android once the account lands). Gate the Pixel 9 smoke on the same window as 8.1 / 8.2.

- **R5 — overflow on small phones / large type.** Plan line + date + price must survive a 320-wide surface at 200% text scale, as wrapping `Text` in the scrolling column (no fixed-height rows, no single-line ellipsis hiding the date). Add an overflow widget test at `Size(320, 480)` × `textScaler: 2.0` (client/CLAUDE.md gotcha #7). The trailing-stacked hub lines (§2) avoid the one-row horizontal overflow by construction.

- **R6 — dark-surface contrast.** Use `textPrimary` / `errorBody` for the data the user reads, `textSecondary` (4.82 : 1, AA with low headroom) only for chrome, `destructive` for inline failures. Never carry `overlaySubtitle` (light-paywall token) onto this dark surface — it fails AA on `background`.

- **R7 — token guards.** No new `AppColors` token (keeps `count == 16`); no inline `Color(0x…)` in the new files (the static hex-literal scan covers `lib/` outside `lib/core/theme/`). All colors via `AppColors.*`.
