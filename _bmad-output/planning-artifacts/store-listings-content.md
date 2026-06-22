# Store-Listings Content — "Survive the Talk"

> **Binding store-copy artifact for Story 10.3.** This is the single source of truth Walid follows click-by-click when filling in App Store Connect and the Google Play Console. Drafted by the dev agent; **the user-facing copy (name, subtitle/short description, full description, keywords) is DRAFT pending Walid's sign-off** (Task 5b — dev proposes, Walid approves, same pattern as the Story 7.1 debrief titles). Everything else (IDs, URLs, mappings, questionnaire answers) is factual and final.
>
> Captured 2026-06-22. Copy discipline follows the "Handler's Brief" rulebook — no exclamation marks / hype in the app's own voice.

---

## 0. Pinned identifiers — DO NOT change (copy verbatim)

| Field | Value | Why it's fixed |
|---|---|---|
| iOS bundle id | `com.surviveTheTalk.client` | Permanent once published; the IAP validators (Story 8.1) key on it. |
| Android applicationId | `com.surviveTheTalk.client` | Same string both platforms; permanent. |
| Subscription product id | `stt_weekly_199` | Must match client `kIapWeeklyProductId` **and** server `IAP_PRODUCT_ID` default (leave server var unset). Any mismatch breaks `POST /subscription/verify`. |
| Privacy Policy URL | `https://api.survivethetalk.com/legal/privacy` | Live HTTPS since Story 10.2 — **verified `200` on 2026-06-22**. |
| Terms of Service URL | `https://api.survivethetalk.com/legal/terms` | Live HTTPS since Story 10.2 — **verified `200` on 2026-06-22**. |
| Primary category | **Education** | PRD p.31/309 — entertainment-positioned, Education-classified for discoverability. |

---

## 1. App name / identity

- **App name (home-screen + store):** **Survive the Talk**
  - ⚠️ **Verify availability on both stores when registering.** If taken, fallback: **"Survive the Talk: English"**.
  - Already wired into the binary this story: iOS `CFBundleDisplayName` + `CFBundleName`, Android `android:label`.
- **Subtitle (Apple, ≤30 chars):** `Survive English phone calls`  — **27 chars** ✓
- **Short description (Google, ≤80 chars):** `High-stakes English calls with sarcastic AI. Talk your way out — or hang up.`  — **76 chars** ✓

---

## 2. Full description (both stores — identical body)

> Survive the Talk crash-tests your real English. Pick a scenario, take the call, and talk your way through a high-stakes conversation with a sarcastic, impatient AI character who will hang up on you if you freeze. Then read a brutally honest debrief: what you said well, the exact mistakes you made, the slang you missed, and your survival score.
>
> Built for intermediate learners stuck between understanding podcasts and holding a real conversation — expats, interview prep, anyone tired of apps that just praise you for trying. 3 free scenarios to start. Unlock everything for $1.99/week.

**Notes for the consoles:**
- Apple "Promotional Text" (optional, ≤170 chars, editable without review) — leave blank for MVP or reuse the short description.
- Google "Full description" max 4000 chars — the body above is well under.
- No exclamation marks / no "amazing"/"!" — matches the app's deadpan voice (Handler's Brief).

---

## 3. Keywords (Apple) — `≤100 chars`, comma-separated, **no spaces**

```
english,conversation,speaking,practice,learn,roleplay,fluency,esl,language,accent,interview
```
— **91 chars** ✓ (Google has no separate keyword field; it indexes the title + descriptions.)

---

## 4. Category & age rating

- **Primary category:** Education (both stores). Secondary (Apple, optional): Games / Word — leave unset for MVP unless Walid prefers a secondary.
- **Age rating:** **13+ (Apple) / PEGI 12 (Google)**. (Overrides the epics' stale "12+"; aligned to PRD p.305 and the Story 10.1 legal pages, which already state 13+.)

### 4a. Apple age-rating questionnaire (App Store Connect → App Information → Age Rating)

Answer to land **13+**. The app has simulated confrontation / mild mature themes (mugger, suspicious cop, angry partner) and infrequent mild language; **no** sexual content, **no** realistic violence, **no** gambling.

| Apple questionnaire item | Answer |
|---|---|
| Cartoon or Fantasy Violence | None |
| Realistic Violence | None |
| Prolonged Graphic/Sadistic Realistic Violence | None |
| Profanity or Crude Humor | **Infrequent/Mild** |
| Mature/Suggestive Themes | **Infrequent/Mild** |
| Horror/Fear Themes | None |
| Medical/Treatment Information | None |
| Alcohol, Tobacco, or Drug Use or References | None |
| Sexual Content or Nudity | None |
| Gambling (simulated) | None |
| Contests | None |
| Unrestricted Web Access | No |
| Made for Kids | **No** |

### 4b. Google content-rating questionnaire (Play Console → Content rating → IARC)

App category for the questionnaire: **Reference, News, or Educational**. Answer to land **PEGI 12 / ESRB Teen**:

| IARC question | Answer |
|---|---|
| Violence (realistic or cartoon) | **No** (confrontation is verbal only — no depicted violence) |
| Frightening / disturbing content | No |
| Sexuality / nudity | No |
| Profanity / crude humor | **Yes — mild, infrequent** |
| Controlled substances (drugs/alcohol/tobacco) | No |
| Gambling (real or simulated) | No |
| User interaction (chat between users / shared content) | **No** (the user only talks to AI characters, never other users) |
| Shares user location | No |
| Digital purchases | **Yes** (the weekly subscription) |

**Mature-themes note (both questionnaires):** the scenarios include adversarial/uncomfortable situations (a mugger, a suspicious cop, an angry partner). Persona bound (PRD p.316): *"Sarcastic and impatient YES, insulting or degrading NEVER."* In-app content warnings are shown before intense scenarios (PRD p.309/467).

---

## 5. Data Safety (Google) / Privacy Nutrition Labels (Apple)

Source: architecture §External Service Dependencies + the Story 10.1 privacy policy. **No advertising, no tracking/ATT prompt, no data sold, no data used to track across apps.**

| Data type | Collected? | Linked to identity? | Stored? | Purpose | Third party |
|---|---|---|---|---|---|
| Email address | Yes | Yes (account) | Yes (account) | Account / passwordless login | Resend (sends the login code) |
| Audio (voice) | Yes (processed live) | No | **No** — process-and-discard, no audio on disk, **no biometric/voiceprint** retained | App functionality (speech-to-text) | Soniox (STT); carried over LiveKit transport |
| Conversation text | Yes (transient) | No | Only a distilled **debrief JSON** is stored; the raw transcript is **not persisted** | App functionality (character replies, judging, debrief) | Groq (LLM); Cartesia / ElevenLabs (TTS) |
| Purchases | Yes | Yes | Yes (subscription state) | App functionality (entitlement) | Apple App Store / Google Play handle payment data |

**Apple privacy labels mapping** — Data Used to Track You: **None**. Data Linked to You: *Contact Info (email), Purchases.* Data Not Linked to You: *Audio Data (not stored), User Content (transient).*

**Google Data Safety mapping** — Data collected: *Email, Audio (not stored), App activity / in-app content (debrief only), Purchase history.* Security practices: *encrypted in transit* (HTTPS/WebRTC-DTLS); *user can request deletion* (account deletion path per privacy policy).

**AI disclosure (FR39 / EU AI Act Art. 50):** the in-app consent flow + privacy policy already state the user talks to **AI-generated characters and voices, not real humans**. Reference this wherever the store asks about AI-generated content / UGC.

**Region note:** EU-region VPS; process-and-discard audio (BIPA/GDPR posture asserted in the privacy policy).

---

## 6. Subscription product sheet (configured ONCE — completes Story 8.1's pending store setup)

Identical on both stores:

| Field | Value |
|---|---|
| Product ID | **`stt_weekly_199`** (verbatim — matches client + server) |
| Type | Auto-renewable subscription |
| Duration | 1 week |
| Price | **$1.99 USD** (use the store's nearest price point / tier) |
| Free trial / intro offer | **None** (MVP) |
| Display name (user-facing) | "Premium" |

- **Apple:** create one **subscription group** — suggested name "Survive the Talk Premium"; the single product `stt_weekly_199` sits inside it. Tier value stays `paid` per ADR-002 (the "Premium" label is display-only). ⚠️ The **"Paid Applications" agreement + tax/banking must be Active** in App Store Connect — the #1 cause of an un-buyable subscription (Story 8.1 gotcha).
- **Google:** create the subscription **and** its **base plan**, and set **both to `Active`**. Grant the service account the **"View financial data"** permission (Story 8.1). A **signed AAB** (this story's Task 4) on the **Internal testing** track is required before purchases are testable.

---

## 7. Screenshot spec (5 frames — same story on both stores)

| # | Frame | What it shows |
|---|---|---|
| 1 | Scenario hub | The scenario list with titles + completion % |
| 2 | Incoming call | The incoming-call screen (ringing) |
| 3 | In-call | Animated character + the checkpoint HUD mid-conversation (the "money" shot) |
| 4 | Debrief | The debrief with the survival score visible |
| 5 | Paywall | The paywall / unlock screen |

- **Android (this story):** phone screenshots captured on the **Pixel 9**, portrait, **9:16, ≥1080 px wide** (Task 10). Play minimum 2, up to 8 — upload all 5.
- **iOS (DEFERRED to Story 10.4):** iPhone 6.7" + 6.5" sets require an iOS build the project won't have until 10.4. **Do NOT fake them** — prep the iOS text + subscription now, defer screenshots + the submission-ready flip (DEC-2).

---

## 8. Graphic assets

| Asset | Spec | Status |
|---|---|---|
| App Store marketing icon | 1024×1024, no alpha | ✅ **Exported** → `_bmad-output/planning-artifacts/store-assets/app-store-icon-1024.png` (also in the iOS appiconset) |
| Play hi-res icon | 512×512, full-bleed (Play masks it) | ✅ **Exported** → `_bmad-output/planning-artifacts/store-assets/play-hi-res-icon-512.png` |
| Play feature graphic | **1024×500**, no alpha/transparency | ⚠️ **TODO (Walid / design)** — required by Play before publishing. Not auto-derivable from the icon; needs a banner composition (the app's dark `#120F0F` ground + the mouth mark + the wordmark "Survive the Talk"). |
| Android adaptive launcher icon | foreground + `#120F0F` background | ✅ Generated this story (`mipmap-anydpi-v26`); verify on the Pixel 9 (Task 10). |

---

## 9. Field-by-field console checklist

### App Store Connect (Apple — account active; iOS screenshots → 10.4)
- [ ] App name: **Survive the Talk** · Subtitle: `Survive English phone calls`
- [ ] Keywords: the §3 string · Category: **Education**
- [ ] Description: the §2 body · Age rating: questionnaire per §4a → **13+**
- [ ] Privacy Policy URL: `https://api.survivethetalk.com/legal/privacy`
- [ ] App Privacy (nutrition labels) per §5 · Bundle id: `com.surviveTheTalk.client`
- [ ] Subscription `stt_weekly_199` ($1.99/wk) in a group per §6 · Paid Apps agreement **Active**
- [ ] **Defer:** iOS screenshots + final submission state → Story 10.4 (recorded, not silent)

### Google Play Console (after the Developer account exists — DEC-1, the long pole)
- [ ] Title: **Survive the Talk** · Short description: §1 · Full description: §2
- [ ] Category: **Education** · Content rating: questionnaire per §4b → **PEGI 12**
- [ ] Data Safety form per §5 · Privacy Policy URL: `https://api.survivethetalk.com/legal/privacy`
- [ ] Upload: feature graphic 1024×500, 512 hi-res icon (§8), 5 phone screenshots (§7)
- [ ] Subscription `stt_weekly_199` + base plan **both Active** (§6) · service account "View financial data"
- [ ] Signed AAB (Task 4) on Internal testing before testing purchases

---

## 10. References

- Story 10.3 spec — `_bmad-output/implementation-artifacts/10-3-configure-app-store-and-play-store-listings.md`
- PRD — positioning/value prop, $1.99/week (p.174), category Education (p.31/309), age 13+/PEGI 12 (p.305), AI disclosure / EU AI Act Art. 50 (p.306/472), persona bounds (p.316)
- Architecture — §External Service Dependencies (data-safety mapping), §Voice Data Privacy (process-and-discard)
- Story 8.1 store-setup context — `memory/project_story_8_1_store_setup.md` (account status, env vars, Apple/Google gotchas, `stt_weekly_199`)
- Stories 10.1 (legal pages) + 10.2 (HTTPS domain — store URLs live)
