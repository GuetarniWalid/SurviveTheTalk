# UX Decision — Content Warning Dialog

**Status:** Accepted
**Date:** 2026-04-24
**Deciders:** Walid (Project Lead)
**Blocks resolved:** Story 5.4 (Content warning display for intense scenarios) — AI-E from Epic 4 retrospective

---

## Context

Story 5.4 adds a Material Dialog shown when the user taps a scenario whose `content_warning` column (added in ADR 001) is non-null. The dialog gates call initiation for intense scenarios (e.g. The Mugger). The retro flagged that copy, tone, and button labels were unspecified. Decision needed before Story 5.4 kickoff.

The per-scenario warning text itself is **authored in the YAML** and stored in the `scenarios.content_warning` column. This doc specifies the **frame** around that dynamic body: title, buttons, and behavioral rules.

---

## Decision

### Copy spec

| Element | Value |
|---|---|
| Title | *(none — dialog has no title, body carries the message)* |
| Body | `scenario.content_warning` (rendered verbatim from DB) |
| Primary button (confirm) | **Continuer** |
| Secondary button (cancel) | **Revenir** |

### Cross-cutting rules

- **`barrierDismissible: false`** — tap outside the dialog does NOT close it. Forces explicit user choice; prevents accidental entry into an intense scenario.
- **Button order:** secondary (Revenir) on the left, primary (Continuer) on the right, per Material convention.
- **No "don't show again"** option. The warning re-appears every time the user taps the card, even after successful calls. Protection is delibate and non-dismissable at the preference layer.
- **On confirm:** close dialog, proceed with call initiation (hands off to Epic 6.1 call-initiation path).
- **On cancel:** close dialog, return to scenario list. No state change, no call initiated.

---

## Rationale

**Tone = direct and respectful.**

- Treats the user as capable of handling the scenario they chose — no dramatic framing, no patronizing reassurance.
- Aligned with the AI-disclosure screen (Story 4.4) which established a neutral, respectful voice for app chrome. In-persona sarcasm belongs **inside** calls, not in warning surfaces.
- «Revenir» (instead of «Annuler» or «Retour») echoes the bounce-to-safe-fallback pattern documented in `feedback_error_ux.md` — it's the consistent verb for "go back to the safe screen" across the app.
- No title keeps the dialog focused on the scenario-specific message, not on a generic "Avertissement" heading that adds noise without information.

**Why not "App Store-ready" formal language (Variant C rejected):** the app's positioning is personal coaching, not a regulatory disclaimer. A "Content notice" header feels bureaucratic and contradicts the empowerment tone the rest of the product projects.

**Why not empathetic/warm language (Variant B rejected):** extra reassurance («Vous pourrez y revenir quand vous voudrez») adds copy without functional value — the Revenir button already communicates reversibility. Kept the body lean.

---

## Accessibility

- **Screen reader:** button labels are distinct verbs («Continuer», «Revenir») — no "OK/Cancel" ambiguity. Material Dialog automatically announces the body text on focus.
- **Dynamic type:** body must render without overflow at `textScaler: 1.5` on a 320-wide viewport. Use the `setSurfaceSize(320, 480)` + `addTearDown` pattern in widget tests (see `client/CLAUDE.md` gotcha #7).
- **Tap targets:** Material Dialog defaults satisfy the 48×48 minimum; no custom sizing needed.

---

## Design system

- No new color tokens. Material Dialog inherits from `ThemeData.dialogTheme` which is already wired through `AppTheme.dark` + `AppColors`.
- Primary button uses the default ElevatedButton / TextButton styles from theme. Do NOT hardcode colors — the `theme_tokens_test.dart` enforcement test will fail the build.
- Body text uses `AppTypography.body` (default). Button labels use their theme-default style.

---

## Consequences

**Positive**
- Story 5.4 has zero open UX questions at kickoff. Dev can reference this doc directly.
- Consistent with established app tone (neutral chrome + sarcastic in-call personas).
- Reusable pattern if future features need similar gating dialogs (e.g. Epic 7 debrief replay warnings).

**Negative / trade-offs**
- «Continuer» is slightly generic — a future UX pass (post-MVP) may want a more scenario-specific verb per warning category (e.g. «Prendre l'appel»). Deferred to validate-fast-iterate-on-render strategy.
- No localization. Strings are French-only, matching current app scope (communication_language = French).

---

## Implementation notes for Story 5.4

```dart
// Pseudocode — exact widget tree left to Story 5.4 dev
showDialog<bool>(
  context: context,
  barrierDismissible: false,
  builder: (ctx) => AlertDialog(
    content: Text(scenario.contentWarning),  // from DB, nullable-checked upstream
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(ctx, false),
        child: const Text('Revenir'),
      ),
      ElevatedButton(
        onPressed: () => Navigator.pop(ctx, true),
        child: const Text('Continuer'),
      ),
    ],
  ),
);
// Returned bool → true proceeds to call initiation, false/null stays on list.
```

- The dialog is triggered **only when `scenario.content_warning != null`**. Scenarios without a warning go straight to call initiation (no dialog).
- Widget tests must cover: (a) dialog shows for warning-present scenario, (b) dialog does not show for warning-absent scenario, (c) `barrierDismissible: false` behavior (tap outside = no-op), (d) confirm → proceeds, (e) cancel → returns with no call initiated.
