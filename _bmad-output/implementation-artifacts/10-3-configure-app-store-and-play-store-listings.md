# Story 10.3: Configure App Store and Play Store Listings

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want both store listings fully configured with all required metadata, assets, and the weekly subscription product — and the few remaining app-identity gaps fixed in code,
so that "Survive the Talk" can be submitted for review with no avoidable rejections or delays.

## Context & Why This Story Is Different

This is a **launch-ops + asset-prep story, not a feature build.** The bulk of the acceptance criteria is **manual work in the Apple/Google consoles** that only Walid can do (the agent has no store credentials), gated on accounts and assets that don't all exist yet. So the story splits cleanly into two halves:

1. **The codeable gaps the agent fixes now** — the app is still shipping under Flutter's scaffold identity (`"client"` / `"Client"`), Android `release` builds still **debug-sign**, Android has **no adaptive launcher icon**, and there's no drafted store copy. All of that is the agent's job and is done in this story.
2. **The manual console configuration + asset capture** — creating the listings, uploading screenshots/graphics, completing the rating/data-safety questionnaires, and configuring the subscription product. The agent produces a **complete, copy-paste-ready content artifact** so Walid's console work is mechanical, but the clicks are his.

**Three hard external realities shape the scope (all surfaced as decisions below):**

- **The Google Play Developer account does not exist yet** (25 USD + ~48h identity verification — the launch **long pole**, already flagged in Story 8.1). **Nothing in the Play half can start until it's created**, so it must be started **first**.
- **iOS has no build/test pipeline until Story 10.4.** App Store Connect **text metadata + the subscription product** can be prepped now (the Apple account is active), but **iOS screenshots require an iOS build** → the iOS screenshot upload + final submission-ready state **defer to 10.4**.
- **The weekly subscription product (AC3) is the same manual store setup Story 8.1 has been waiting on.** It is configured **once, here** (`stt_weekly_199`, $1.99/week auto-renewable) — completing 8.1's deferred store-config dependency at the same time. See [project_story_8_1_store_setup.md].

The **"Current State of the World" table in Dev Notes was captured live from the repo on 2026-06-22** and is authoritative. The epics text is stale on two points (age rating "12+", and the privacy URL form) — see "🚨 Stale-Doc Overrides".

### Agent vs. Walid split

Per the standing autonomy rule, the agent does **everything it can**: the identity rename, the icon pipeline, the mic string, the release-signing scaffolding, and the full store-content artifact — plus run all Flutter gates. **What only Walid can do** (no agent credentials / on-device only):

- **Create the Google Play Developer account** (the long pole — start first).
- **Generate + safely store the release upload keystore** (a permanent secret; see DEC-5).
- **Enter the listings in App Store Connect + Google Play Console**, upload assets, create the subscription products, complete the content-rating + Data-Safety questionnaires.
- **Capture Android screenshots on the Pixel 9** (iOS screenshots deferred to 10.4).

## Acceptance Criteria

1. **The app's user- and store-facing name is "Survive the Talk" everywhere.** iOS `CFBundleDisplayName` and Android `android:label` read **"Survive the Talk"** (both currently `"Client"`/`"client"`). The bundle identifier / applicationId stay **`com.surviveTheTalk.client`** unchanged (it is permanent and already wired into the IAP product config — see Anti-patterns). `flutter analyze` clean and `flutter test` green after the change. [Epics AC1 — app name]

2. **Launcher icons are generated from the single 1024 source for every required target, including Android adaptive icons.** `flutter_launcher_icons` is configured against the existing `assets/images/icon/app_icon.png` (1024×1024) + `app_icon_foreground.png`, and running it produces: the iOS `AppIcon.appiconset` (incl. the 1024 marketing icon), and **Android adaptive icons** (`mipmap-anydpi-v26/ic_launcher.xml` + foreground/background) at all densities (today only legacy square `ic_launcher.png` exists). A **512×512** Play "hi-res icon" and a **1024×1024** App Store icon are available for upload, derived from the same source. The on-device icon is visually verified unchanged-or-better on the Pixel 9. [Epics AC5]

3. **The microphone usage description matches the store-spec wording.** iOS `NSMicrophoneUsageDescription` reads **"Used for real-time English conversation practice with AI characters"** (Epics AC4 verbatim; currently a close-but-different string). [Epics AC4]

4. **Android `release` builds are signed with a real upload key, not the debug key.** `android/app/build.gradle.kts` has a `signingConfigs { release { … } }` that reads credentials from a **git-ignored** `android/key.properties`; `buildTypes.release` uses it; the keystore file + `key.properties` are in `.gitignore` and are **never committed**; `flutter build appbundle --release` produces a **signed AAB** (verified locally by the agent against a throwaway/Walid-provided keystore, then the real keystore owned by Walid per DEC-5). [Play prerequisite — "submittable"]

5. **A complete, Walid-approved store-listing content artifact exists at `_bmad-output/planning-artifacts/store-listings-content.md`,** containing fully-drafted metadata for **both** stores: app name, subtitle (Apple ≤30 chars) / short description (Google ≤80 chars), full description, keyword list (Apple ≤100 chars), **primary category = Education**, **age rating 13+ (Apple) / PEGI 12 (Google)**, the **content-rating questionnaire answers**, the **Data Safety / Apple privacy-nutrition-label mapping** for every third-party service (Soniox, Groq, Cartesia/ElevenLabs, LiveKit, Resend, Apple/Google IAP), the **subscription product sheet**, and the **per-frame screenshot spec**. [Epics AC1/AC2 — content side]

6. **App Store Connect is configured to the extent possible without an iOS build (Apple account active).** Name, subtitle, keywords, description, category, age rating, and the **privacy-policy URL** are entered; the **`stt_weekly_199` weekly auto-renewable subscription ($1.99/week)** is created in App Store Connect with the product id matching the client (`kIapWeeklyProductId`) and server (`IAP_PRODUCT_ID` default). **iOS screenshots + the final submission-ready listing DEFER to Story 10.4** (no iOS build pipeline) — recorded explicitly, not silently. [Epics AC1/AC3 — reconciled; Walid manual]

7. **Google Play Console is fully configured** — title, short + full description, category, **content-rating questionnaire completed**, **feature graphic (1024×500)** + **512×512 hi-res icon** + **phone screenshots** uploaded, privacy-policy URL set, **Data Safety form** completed, and the **`stt_weekly_199` weekly subscription ($1.99/week) with its base plan both `Active`** and the product id matching client + server. **Gated on the Google Play Developer account existing (DEC-1).** [Epics AC2/AC3 — Walid manual]

8. **Both stores' privacy / terms URLs point at the live HTTPS pages.** The store "Privacy Policy URL" fields use **`https://api.survivethetalk.com/legal/privacy`**, and the Terms URL (where the store has a field) uses **`https://api.survivethetalk.com/legal/terms`** — both live over HTTPS since Story 10.2. [Epics AC1/AC2 — privacy URL]

> **No Smoke Test Gate.** This story touches **no** server endpoint, **no** DB migration, and **no** VPS deploy — the code changes are client-side identity strings, a Gradle signing config, a `pubspec` dev-dependency, and regenerated icon assets; the rest is manual console work + a planning artifact. Per the template's scope rule, the Smoke Test Gate section is **omitted**. The automated gates are `flutter analyze` + `flutter test`; the human gates are the signed-AAB build + Walid's console completion + the Pixel 9 icon/identity check.

## Tasks / Subtasks

### Part A — Agent (codeable now)

- [x] **Task 1 — Rename the app identity to "Survive the Talk"** (AC: 1) — agent ✓ DONE
  - [x] `client/ios/Runner/Info.plist:9-10` — `CFBundleDisplayName` → `Survive the Talk`; also set `CFBundleName` (line 17-18) to `Survive the Talk`. `CFBundleIdentifier` untouched.
  - [x] `client/android/app/src/main/AndroidManifest.xml:17` — `android:label="Survive the Talk"`.
  - [x] **Did NOT change** `applicationId` / `PRODUCT_BUNDLE_IDENTIFIER` (`com.surviveTheTalk.client`) — left permanent/IAP-tied id intact.
  - [x] `flutter analyze` clean + `flutter test` 689 pass — no test asserted the old label.

- [x] **Task 2 — Set up the launcher-icon pipeline + export store icons** (AC: 2) — agent ✓ DONE
  - [x] Added `flutter_launcher_icons: ^0.14.0` (resolved 0.14.4) to `dev_dependencies` + a config block: `image_path: app_icon.png` (drives iOS + Android legacy), `adaptive_icon_foreground: app_icon_foreground.png`, `adaptive_icon_background: "#120F0F"` (sampled from the source art's own corner so the masked look matches), `remove_alpha_ios: true`, `min_sdk_android: 24`.
  - [x] Ran `dart run flutter_launcher_icons` → `mipmap-anydpi-v26/ic_launcher.xml` + `drawable-*/ic_launcher_foreground.png` (5 densities) + `values/colors.xml` now exist; iOS appiconset still has all 21 PNGs incl. `Icon-App-1024x1024@1x.png`.
  - [x] Exported `play-hi-res-icon-512.png` (512, full-bleed) + `app-store-icon-1024.png` (1024, no alpha) → `_bmad-output/planning-artifacts/store-assets/`; referenced in the content artifact §8.
  - [x] **Preserved the visual** — iOS regenerates from the same `app_icon.png` source (identical); Android adaptive (the only missing piece) = mouth foreground over the `#120F0F` ground. On-device visual check is Walid's Task 10.
  - [x] `flutter analyze` clean + `flutter test` 689 pass — icon assets did not affect tests.

- [x] **Task 3 — Align the microphone usage description** (AC: 3) — agent ✓ DONE
  - [x] `client/ios/Runner/Info.plist:62-63` — `NSMicrophoneUsageDescription` → `Used for real-time English conversation practice with AI characters` (Epics AC4 verbatim). Android needs no manifest rationale string.

- [x] **Task 4 — Wire Android release signing (Walid owns the keystore)** (AC: 4) — agent ✓ DONE / Walid owns the real keystore (DEC-5)
  - [x] `client/android/app/build.gradle.kts`: loads `rootProject.file("key.properties")` if present, adds `signingConfigs.create("release")` reading `storeFile/storePassword/keyAlias/keyPassword`, and `buildTypes.release.signingConfig` switches to the release config when `key.properties` exists, **falling back to debug** when absent (so `flutter run --release` still works for devs without the keystore).
  - [x] `**/key.properties`, `**/*.jks`, `**/*.keystore` were **already** in `client/android/.gitignore` — confirmed git-ignored (`git check-ignore` ✓). Nothing secret is committed.
  - [x] **Verified the wiring with a throwaway keystore** (generated in the OS temp dir, never in-repo): `flutter build appbundle --release` produced a signed `app-release.aab` (78.6MB); `jarsigner -verify` → `jar verified`, signer `CN=Throwaway` (the upload key), **not** the Android Debug key. Throwaway keystore + `key.properties` + AAB deleted after. The exact `keytool` command + `key.properties` template handed to Walid (see Completion Notes) — Walid generates + backs up the REAL upload keystore.
  - [x] `flutter analyze` clean + `flutter test` 689 pass.

- [x] **Task 5 — Draft the store-listing content artifact** (AC: 5) — agent drafts ✓ DONE / Walid approves the copy (pending)
  - [x] Created `_bmad-output/planning-artifacts/store-listings-content.md` — pinned IDs/URLs, app name + Apple subtitle (27 chars) + Google short description (76 chars), full description, Apple keyword string (91 chars), category Education, age rating 13+/PEGI 12 with **both** age-questionnaire answer tables (Apple + Google IARC), the Data-Safety / privacy-label mapping (Soniox / Groq / Cartesia+ElevenLabs / LiveKit / Resend / IAP), the `stt_weekly_199` subscription sheet, the 5-frame screenshot spec, the asset inventory, and a field-by-field console checklist. Handler's-Brief copy discipline (no hype/exclamations).
  - [ ] ⏳ **Present the drafted name/subtitle/keywords/description to Walid for sign-off** before he pastes them into the consoles (dev proposes, Walid approves — Story 7.1 pattern). **Surfaced in the dev-story hand-off; awaiting Walid's OK.**

### Part B — Walid (manual console work; agent guides + verifies)

> **Part B status (human gates — NOT agent dev work).** Task 9 (URL check) is agent-done below. Tasks 6, 7, 8, 10 are Walid-only (no agent credentials / on-device only) and remain **open** — they are the story's human gates, the same way a smoke gate is. They do **not** block the dev→review flip (the agent's Part A is complete + gated green), but they DO gate `review → done`. Task 6 (Google Play account) is the launch long pole — start it first.

- [ ] **Task 6 — Create the Google Play Developer account** (AC: 7 prerequisite; DEC-1) — **Walid, start FIRST** ⏳ PENDING
  - [ ] Register at `play.google.com/console` (25 USD one-time + identity verification, ~48h). This is the **launch long pole** — nothing in Task 8 can start until it clears. Same account flagged in Story 8.1.

- [ ] **Task 7 — Configure the App Store Connect listing** (AC: 6, 8) — Walid (Apple account active), agent-guided ⏳ PENDING
  - [ ] Create/register the app under bundle id `com.surviveTheTalk.client`; enter name/subtitle/keywords/description/category(Education)/age-rating(13+) from the artifact; set Privacy Policy URL `https://api.survivethetalk.com/legal/privacy`.
  - [ ] Create the **`stt_weekly_199`** weekly auto-renewable subscription ($1.99/week, no free trial) in a subscription group; confirm the product id matches the client/server. (Apple "Paid Applications" agreement + tax/banking must be **Active** — #1 cause of un-buyable subs; see 8.1 gotchas.)
  - [ ] **Defer to Story 10.4:** iOS screenshots (need an iOS build) + the final submission-ready listing state. Record the deferral in the story.

- [ ] **Task 8 — Configure the Google Play Console listing** (AC: 7, 8) — Walid (after Task 6), agent-guided ⏳ PENDING (blocked on Task 6)
  - [ ] Main store listing: title, short + full description, category, upload **feature graphic 1024×500**, **512×512 hi-res icon**, and **phone screenshots** (captured on the Pixel 9 — Task 10); set Privacy Policy URL.
  - [ ] Complete the **content-rating questionnaire** and the **Data Safety form** from the artifact's mapping.
  - [ ] Create the **`stt_weekly_199`** weekly subscription ($1.99/week) — subscription **and** its base plan both `Active`; grant the service account the "View financial data" permission (per 8.1). A **signed AAB** (Task 4) on the Internal testing track is required before purchases are testable.

- [x] **Task 9 — Confirm the store privacy/terms URLs resolve** (AC: 8) — agent ✓ DONE
  - [x] Verified `https://api.survivethetalk.com/legal/privacy` → **200** and `/legal/terms` → **200** over HTTPS (2026-06-22) — the store-entered URLs are valid at submission time.

- [ ] **Task 10 — Pixel 9 identity + icon check** (AC: 1, 2) — Walid, on-device ⏳ PENDING (the Pixel 9 human gate)
  - [ ] Install a fresh Android build; confirm the home-screen label reads **"Survive the Talk"** and the launcher icon (incl. the new adaptive form) renders correctly. Capture the listing screenshots while here (Task 8).

## Dev Notes

### 🚨 Stale-Doc Overrides — the epics are out of date on these; use the right-hand column

| Topic | Epics text says | **Reality (use this)** | Evidence |
|---|---|---|---|
| Age rating | AC1: "age rating (12+ or equivalent)" | **13+ (Apple) / PEGI 12 (Google)** | prd.md p.305; Story 10.1 AC3 (legal pages already state 13+) |
| Privacy URL form | AC1/AC2: "privacy policy URL" (abstract) | **`https://api.survivethetalk.com/legal/privacy`** (live HTTPS since 10.2; terms at `/legal/terms`) | Story 10.2 smoke gate; Story 10.1 |
| Subscription "set up in both stores" | AC3 (new work) | **Same manual config Story 8.1 has been waiting on** — product `stt_weekly_199`, do it once here | [project_story_8_1_store_setup.md] |
| App name in code | implies it's "Survive the Talk" | **Still Flutter scaffold `"client"`/`"Client"`** — must be renamed (Task 1) | Info.plist:10/18, AndroidManifest:17 |
| Release build | implies submittable | **Android `release` still debug-signs** (`build.gradle.kts:39-42` TODO) — must wire a real keystore (Task 4) | build.gradle.kts |
| Adaptive icon | AC5 "adaptive icon formats" (implies present) | **Missing** — only legacy square `ic_launcher.png` at 5 densities; no `mipmap-anydpi-v26` | res/mipmap-* listing |

### Current State of the World (captured from the repo, 2026-06-22 — ground truth)

| Item | Current value | File |
|---|---|---|
| iOS display name | `Client` / bundle name `client` | `client/ios/Runner/Info.plist:9-10, 17-18` |
| Android label | `client` | `client/android/app/src/main/AndroidManifest.xml:17` |
| iOS bundle id | `com.surviveTheTalk.client` (keep) | `client/ios/Runner.xcodeproj/project.pbxproj` |
| Android applicationId | `com.surviveTheTalk.client` (keep) | `client/android/app/build.gradle.kts:24` |
| iOS mic string | `SurviveTheTalk needs your microphone for voice calls with AI characters` | `Info.plist:62-63` |
| Android release signing | **debug keys** (`signingConfigs.getByName("debug")`, TODO) | `build.gradle.kts:37-43` |
| Icon source | `app_icon.png` (1024×1024) + `app_icon_foreground.png` | `client/assets/images/icon/` |
| Android icons | legacy square `ic_launcher.png` only, 5 densities; **no adaptive** | `client/android/app/src/main/res/mipmap-*` |
| iOS icons | full 19-variant appiconset incl. 1024 | `client/ios/Runner/Assets.xcassets/AppIcon.appiconset/` |
| `flutter_launcher_icons` | **not configured** | `pubspec.yaml` |
| App version | `1.0.0+1` | `pubspec.yaml:19` |
| Store assets (screenshots, feature graphic, fastlane, metadata) | **none in repo** | — |
| IAP product id | `stt_weekly_199` (client `kIapWeeklyProductId` == server `IAP_PRODUCT_ID` default) | Story 8.1 |

### Store-Listing Content (raw material for the Task 5 artifact)

**Identity** — Name: **Survive the Talk** (verify it's available on both stores; have a fallback like "Survive the Talk: English" ready). Subtitle/short tagline (Apple ≤30 chars): **"Survive English phone calls"** (27). Google short description (≤80): **"High-stakes English calls with sarcastic AI. Talk your way out — or hang up."**

**Full description (draft)** — built from the PRD positioning ("adversarial entertainment — a game you survive, not a tool you study with"; the gap "between *I understand podcasts* and *I can't hold a real conversation*"):
> Survive the Talk crash-tests your real English. Pick a scenario, take the call, and talk your way through a high-stakes conversation with a sarcastic, impatient AI character who will hang up on you if you freeze. Then read a brutally honest debrief: what you said well, the exact mistakes you made, the slang you missed, and your survival score.
> Built for intermediate learners stuck between understanding podcasts and holding a real conversation — expats, interview prep, anyone tired of apps that just praise you for trying. 3 free scenarios to start. Unlock everything for $1.99/week.

**Apple keyword string (≤100 chars, comma-separated, no spaces):**
`english,conversation,speaking,practice,learn,roleplay,fluency,esl,language,accent,interview`

**Category:** Education (primary). [PRD p.31/309 — "Education as primary category", positioned as entertainment but classified Education.]

**Age rating:** 13+ (Apple) / PEGI 12 (Google). Questionnaire guidance — the app contains **simulated confrontation / mild mature themes** (mugger, suspicious cop, angry partner), **infrequent/mild language**, **no** sexual content, **no** real violence, **no** gambling, **no** user-to-user contact, **no** unrestricted web access. Content warnings are shown in-app before intense scenarios (PRD p.309/467). [Persona rule: "Sarcastic and impatient YES, insulting or degrading NEVER" — PRD p.316.]

**Data Safety (Google) / Privacy nutrition labels (Apple) — third-party mapping** (from architecture §External Services + the 10.1 privacy policy):

| Data type | Collected? | Stored? | Purpose | Third party |
|---|---|---|---|---|
| Email address | Yes | Yes (account) | Account / passwordless auth | Resend (sends the login code) |
| Audio (voice) | Yes (processed live) | **No** — process-and-discard, no audio on disk, **no biometric/voiceprint** retained | App functionality (speech-to-text) | Soniox (STT); carried by LiveKit transport |
| Conversation text | Yes (transient) | Only a distilled **debrief JSON** is stored; the raw transcript is **not persisted** | App functionality (character replies, judging, debrief) | Groq (LLM); Cartesia/ElevenLabs (TTS, text→speech) |
| Purchases | Yes | Yes (subscription state) | App functionality (entitlement) | Apple App Store / Google Play handle the payment data |

No advertising, no tracking/ATT, no data sold. (BIPA/GDPR: process-and-discard audio, EU-region VPS — already asserted in the privacy policy.)

**AI disclosure (FR39 / EU AI Act Art. 50):** the in-app consent flow + privacy policy already state the user talks to **AI-generated characters and voices, not real humans** — referenced from the listing where the store asks about AI/UGC.

**Subscription product sheet (both stores, identical):**
- Product ID: **`stt_weekly_199`** (permanent; must match client `kIapWeeklyProductId` + server `IAP_PRODUCT_ID` default — leave server unset).
- Type: auto-renewable subscription. Duration: **1 week**. Price: **$1.99 USD** (price point). Free trial / intro offer: **none** (MVP).
- Apple: one subscription group ("Survive the Talk Premium"); display label "Premium" (tier value stays `paid` per ADR-002 — label-only). Google: subscription + **base plan** both `Active`.

**Screenshot spec (5 frames, same story both stores):** (1) scenario hub (the list with titles + completion %), (2) incoming-call screen, (3) in-call — animated character + checkpoint HUD, (4) debrief with the survival score, (5) paywall. Android phone screenshots captured on the Pixel 9 (9:16, ≥1080px). iPhone 6.7"/6.5" sets **deferred to 10.4** (need an iOS build). Play also needs a **feature graphic 1024×500** + **512×512 hi-res icon** (Task 2 exports).

### Reuse-don't-reinvent

- **Bundle id is already correct and consistent** (`com.surviveTheTalk.client` on both platforms) and is wired into the IAP product config (8.1). **Only the human-facing name** is wrong — rename the *label/display name*, never the id.
- **One 1024 icon source already exists** (`app_icon.png` + `app_icon_foreground.png`) — `flutter_launcher_icons` regenerates every target from it; don't hand-cut icons per size. The 512 Play icon + 1024 App Store icon both derive from it.
- **The IAP product id is already chosen and pinned** — `stt_weekly_199`. The store products must use exactly that string (don't invent a new one).
- **Legal pages are done and live over HTTPS** (Stories 10.1 + 10.2) — the store URL fields just consume `https://api.survivethetalk.com/legal/{privacy,terms}`; no new hosting work.
- **The store-content artifact mirrors the 8.1 store-setup memory + the binding-doc pattern** ([project_story_8_1_store_setup.md], `manage-subscription-screen-design.md`) — one authoritative planning doc Walid follows click-by-click.

### Anti-patterns to avoid

- ❌ **Changing `applicationId` / `PRODUCT_BUNDLE_IDENTIFIER`.** It's permanent once published, and the IAP validators (8.1) key on `com.surviveTheTalk.client`. Rename only the display label.
- ❌ **Committing the release keystore or `key.properties`.** They are secrets; `.gitignore` them. A leaked upload key is a security incident; a *lost* one blocks Play updates (unless Play App Signing key-reset is used).
- ❌ **Inventing a new subscription product id.** Use `stt_weekly_199` verbatim — any mismatch with the client/server breaks server-side validation.
- ❌ **Treating iOS screenshots as in-scope now.** No iOS build pipeline until 10.4 — prepping iOS *text + subscription* is fine; screenshots defer (DEC-2). Don't fake them.
- ❌ **Blocking the whole story on Google Play.** The Apple-text half + all agent code tasks proceed in parallel; only Task 8 waits on the account (DEC-1).
- ❌ **Letting `flutter_launcher_icons` silently degrade the existing iOS icon.** Verify the visual on-device; if it regresses, match the current design or hand-add only the missing Android adaptive icon (DEC-6).
- ❌ **Hardcoding a color for the adaptive-icon background outside the theme** — `client/CLAUDE.md` gotcha #6 (the token-enforcement test scans `lib/` for hex literals). The icon background lives in Android resources, not `lib/`, so it's outside that lint — but if any Dart references a brand color, use `AppColors`.

### Decisions

- **DEC-1 — Google Play Developer account is the external long pole (Walid, start FIRST).** 25 USD + ~48h ID verification; the entire Play half (AC7) is blocked until it exists. Same account from Story 8.1. **RECOMMEND: Walid registers it the moment this story starts**, in parallel with all the agent code tasks. ⚠️ This is the one true schedule blocker.
- **DEC-2 — iOS screenshots + final iOS listing DEFER to Story 10.4; iOS text + subscription are done now.** App Store Connect text/metadata + the `stt_weekly_199` product need no build (Apple account active); **screenshots require an iOS build** the project won't have until 10.4. **RECOMMEND: prep everything text-side now, defer the iOS screenshot upload + submission-ready flip to 10.4** — recorded as an explicit partial-coverage decision (per [feedback_surface_behavioral_tradeoffs_as_decisions]), not a silent gap.
- **DEC-3 — AC3 subscription config is done once, here (completes 8.1's pending store setup).** `stt_weekly_199`, $1.99/week auto-renewable, matching ids both stores. Avoids two stories each claiming "configure the subscription."
- **DEC-4 — App name string = "Survive the Talk" (RECOMMEND, confirm exact form).** Used as the home-screen label + the store name. Confirm capitalization/spacing and that it's **available** on both stores (have a fallback ready). Bundle ids unchanged.
- **DEC-5 — Release keystore: Walid owns the secret; the agent wires Gradle (RECOMMEND).** The agent adds `signingConfigs.release` reading a git-ignored `key.properties` + gives the `keytool` command; **Walid generates + safely backs up** the upload keystore (a permanent secret — losing it blocks Play updates). Alternatively Walid hands the agent the values and the agent generates it locally, but Walid must still store it off-repo. Either way it's never committed. (Walid running keytool himself fits the "secret the agent doesn't hold" exception to the agent-runs-commands rule.)
- **DEC-6 — Icon generation via `flutter_launcher_icons` (RECOMMEND) vs. hand-add only the Android adaptive icon.** The missing piece is the Android adaptive icon; iOS already has a full appiconset. `flutter_launcher_icons` is the reproducible, reuse-don't-reinvent path and also emits the iOS set + densities from one source — **RECOMMEND it**, configured to preserve the current look and visually verified on-device. If Walid would rather not touch the working iOS icon, the lighter-touch fallback is to hand-author only `mipmap-anydpi-v26/ic_launcher.xml` + foreground/background and export the 512 separately.
- **DEC-7 — Category = Education (RECOMMEND).** PRD positions the app as adversarial *entertainment* but classifies it under **Education** for the stores (p.31/309). Confirm; "Education" maximizes the learn-English discoverability the ASO copy targets.

### Project Structure Notes

- **Client code (agent):** `client/ios/Runner/Info.plist` (display name + mic string), `client/android/app/src/main/AndroidManifest.xml` (label), `client/android/app/build.gradle.kts` (release signing), `client/pubspec.yaml` (`flutter_launcher_icons` dev-dep + config), regenerated icon assets under `client/ios/.../AppIcon.appiconset/` + `client/android/app/src/main/res/mipmap-*`, `client/android/.gitignore` (keystore/`key.properties`).
- **Planning artifact (agent):** `_bmad-output/planning-artifacts/store-listings-content.md` (new — the binding store-copy doc).
- **No server Python, no migration, no new runtime client dependency** (flutter_launcher_icons is a dev-dependency / build-time tool).
- **External/manual (Walid):** the Google Play account, both store consoles, the upload keystore, Android screenshots.
- This is the **third story of Epic 10** (10.1 + 10.2 done). Epic 10 is already `in-progress`.

### References

- Story spec: [epics.md §Story 10.3](_bmad-output/planning-artifacts/epics.md) (lines 1618-1644) — age "12+" overridden to 13+/PEGI 12 above.
- PRD: [prd.md](_bmad-output/planning-artifacts/prd.md) — positioning/value prop, pricing $1.99/week (p.174), category Education (p.31/309), age rating 13+/PEGI 12 (p.305), AI disclosure / EU AI Act Art. 50 (p.306/472), persona tone bounds (p.316).
- Product brief: [product-brief-surviveTheTalk2-2026-03-25.md](_bmad-output/planning-artifacts/product-brief-surviveTheTalk2-2026-03-25.md) — the intermediate-plateau gap + 5 launch scenarios.
- Architecture: [architecture.md](_bmad-output/planning-artifacts/architecture.md) §External Service Dependencies (data-safety mapping), §Voice Data Privacy (process-and-discard), §Transport Security.
- Prior stories: [10-1-...legal-compliance-pages.md](_bmad-output/implementation-artifacts/10-1-create-privacy-policy-terms-of-service-and-legal-compliance-pages.md) (legal URLs + contact + third-party list); [10-2-...domain-dns-ssl....md](_bmad-output/implementation-artifacts/10-2-provision-domain-dns-ssl-and-server-infrastructure.md) (HTTPS domain — store URLs live).
- IAP / store-setup context: [project_story_8_1_store_setup.md] (account status, env vars, verified Apple/Google gotchas, `stt_weekly_199`), [project_ios_test_pipeline_deferred.md] (iOS build/test deferred to 10.4), `deferred-work.md` F13 (Restore Purchases — a separate 8.2 client task, a **10.5/iOS-submission** blocker, NOT 10.3 scope).
- Client touch-points: [Info.plist](client/ios/Runner/Info.plist), [AndroidManifest.xml](client/android/app/src/main/AndroidManifest.xml), [build.gradle.kts](client/android/app/build.gradle.kts), [pubspec.yaml](client/pubspec.yaml).
- Copy discipline: [project_design_rulebook_handlers_brief.md] (no hype/exclamations in the app's own voice).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (dev-story, 2026-06-22)

### Debug Log References

- `flutter pub get` → resolved `flutter_launcher_icons` 0.14.4 (`Changed 6 dependencies!`).
- `dart run flutter_launcher_icons` → generated Android adaptive icons + `colors.xml` + `mipmap-anydpi-v26/ic_launcher.xml`; regenerated iOS appiconset.
- Throwaway-keystore release build: `flutter build appbundle --release` → `√ Built app-release.aab (78.6MB)` in 318s; `jarsigner -verify` → `jar verified`, signer `CN=Throwaway` (upload key, NOT Android Debug). Throwaway artifacts deleted after.
- `flutter analyze` → `No issues found!`; `flutter test` → `All tests passed!` (689 tests).
- Legal URL check: `/legal/privacy` → 200, `/legal/terms` → 200 (HTTPS, 2026-06-22).

### Completion Notes List

**Agent Part A — COMPLETE + gated green (flutter analyze clean, 689 tests pass):**
- ✅ **Task 1 — identity rename.** iOS `CFBundleDisplayName` + `CFBundleName` and Android `android:label` → **"Survive the Talk"**. Bundle id `com.surviveTheTalk.client` left untouched (permanent / IAP-tied).
- ✅ **Task 2 — icon pipeline.** `flutter_launcher_icons` 0.14.4 (dev-dep) generates Android **adaptive icons** (mouth foreground over `#120F0F`, sampled from the source art's own corner so the masked look matches) + regenerates the iOS appiconset from the same `app_icon.png`. Exported `play-hi-res-icon-512.png` + `app-store-icon-1024.png` to `planning-artifacts/store-assets/`.
- ✅ **Task 3 — mic string.** `NSMicrophoneUsageDescription` → "Used for real-time English conversation practice with AI characters" (Epics AC4 verbatim).
- ✅ **Task 4 — release signing.** `build.gradle.kts` reads a git-ignored `key.properties` → `signingConfigs.release`, with a debug fallback when absent. Verified with a throwaway keystore (signed AAB, `CN=Throwaway`). `.gitignore` already covered `key.properties`/`*.jks`/`*.keystore`.
- ✅ **Task 5 — content artifact** at `planning-artifacts/store-listings-content.md` (copy is DRAFT pending Walid's sign-off).
- ✅ **Task 9 — legal URLs** both return 200.

**⚠️ flutter_launcher_icons side-effect REVERTED:** the generator also flipped the Xcode build setting `ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS` from `YES` to `AppIcon` in `project.pbxproj` — a spurious mutation of a boolean Swift-symbol setting, unrelated to the icon assets (which live in the appiconset, independent of it). Reverted `project.pbxproj` to keep the Xcode project pristine; the icon regeneration (Contents.json + PNGs) is preserved and consistent. iOS isn't buildable until Story 10.4 anyway.

**Walid — Task 4 keystore command (run yourself; it's a permanent secret the agent must not hold — DEC-5):**
```
keytool -genkey -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```
Then create `client/android/key.properties` (git-ignored — never commit it):
```
storePassword=<the store password you chose>
keyPassword=<the key password you chose>
keyAlias=upload
storeFile=C:/absolute/path/to/upload-keystore.jks   # forward slashes; absolute path recommended
```
**Back the keystore up off-machine** — losing it blocks all future Play updates.

**Pending human gates (Part B — NOT agent dev work; gate `review → done`):**
- Task 5b — Walid signs off the listing copy (name / subtitle / keywords / description).
- Task 6 — Walid creates the Google Play Developer account (the launch long pole; start first).
- Task 7 — Walid configures App Store Connect (iOS text + subscription now; iOS screenshots + final submission DEFER to Story 10.4 — DEC-2).
- Task 8 — Walid configures Google Play Console (after Task 6).
- Task 10 — Walid's Pixel 9 identity + icon check (home-screen label "Survive the Talk" + adaptive icon renders).
- Plus the formal `/bmad-code-review` (use a different LLM).

### File List

**Client — modified (agent):**
- `client/ios/Runner/Info.plist` — `CFBundleDisplayName`, `CFBundleName`, `NSMicrophoneUsageDescription`
- `client/android/app/src/main/AndroidManifest.xml` — `android:label`
- `client/android/app/build.gradle.kts` — release `signingConfigs` + `buildTypes.release` (key.properties + debug fallback)
- `client/pubspec.yaml` — `flutter_launcher_icons` dev-dep + config block
- `client/pubspec.lock` — resolved deps
- `client/android/app/src/main/res/mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png` — regenerated legacy square icons (5)
- `client/ios/Runner/Assets.xcassets/AppIcon.appiconset/Contents.json` + the 19 existing `Icon-App-*.png` — regenerated from the same source

**Client — new (agent, generated):**
- `client/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml` — adaptive icon definition
- `client/android/app/src/main/res/values/colors.xml` — `ic_launcher_background = #120F0F`
- `client/android/app/src/main/res/drawable-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher_foreground.png` — adaptive foreground (5)
- `client/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-{50x50,57x57,72x72}@{1x,2x}.png` — added iOS sizes (6)

**Planning artifacts — new (agent):**
- `_bmad-output/planning-artifacts/store-listings-content.md` — the binding store-copy doc
- `_bmad-output/planning-artifacts/store-assets/play-hi-res-icon-512.png`
- `_bmad-output/planning-artifacts/store-assets/app-store-icon-1024.png`

**Story tracking:**
- `_bmad-output/implementation-artifacts/10-3-configure-app-store-and-play-store-listings.md` (this file)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status flips

### Change Log

- 2026-06-22 — dev-story (Part A): renamed the app identity to "Survive the Talk" (iOS + Android), set up the `flutter_launcher_icons` pipeline and generated the missing Android adaptive launcher icon (+ regenerated iOS appiconset, + exported 512/1024 store icons), aligned the iOS mic usage string to the Epics AC4 wording, and wired Android `release` signing to a git-ignored `key.properties` (verified a signed AAB with a throwaway keystore). Drafted the binding `store-listings-content.md`. Reverted a spurious `flutter_launcher_icons` Xcode-build-setting mutation. Gates green (analyze clean, 689 tests). Status → review. Part B (Walid console work + Pixel 9 check + iOS-screenshots-to-10.4) remains as the human gates; `/bmad-code-review` still owed.
- 2026-06-22 — create-story: store-listings story authored after a live repo audit. Found the app still under the Flutter scaffold identity (`client`/`Client`), Android `release` debug-signing, and no adaptive launcher icon → folded those agent-codeable gaps into the story alongside the manual console work. Reconciled the epics' stale age rating (→13+/PEGI 12) + privacy URL (→ live HTTPS), and merged AC3's subscription config with Story 8.1's pending store setup. Status → ready-for-dev.

## Questions for Walid (raised at create-story; none block writing the spec)

1. **Google Play account (the long pole — DEC-1):** confirm you'll start the Google Play Developer registration **now** (25 USD + ~48h ID verification). Everything Play-side waits on it; the Apple-text half + all the code tasks proceed in parallel.
2. **App name (DEC-4):** confirm the exact store/home-screen name is **"Survive the Talk"** (this capitalization/spacing). I'll check availability on both stores when configuring — want a fallback (e.g. "Survive the Talk: English") if it's taken?
3. **Release keystore (DEC-5):** OK for **you to run the `keytool` command and keep/back up the upload keystore** (I'll wire Gradle + give you the exact command + `key.properties` template), since it's a permanent secret? Or would you rather I generate it locally and hand you the file + passwords to store off-repo?
4. **iOS screenshots deferral (DEC-2):** OK to prep the App Store **text + subscription** now but **defer iOS screenshots + the final iOS submission flip to Story 10.4** (no iOS build pipeline yet)? Android goes fully live this story.
5. **Category (DEC-7):** confirm **Education** as the primary store category (you're positioned as entertainment, but Education maximizes the learn-English discoverability).
6. **Listing copy:** I'll draft the subtitle / keywords / full description (candidates are in Dev Notes) and bring them to you for sign-off before anything goes in the consoles — same as the debrief titles in 7.1. Good?
