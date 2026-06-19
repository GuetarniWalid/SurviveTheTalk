# Story 10.1: Create Privacy Policy, Terms of Service, and Legal Compliance Pages

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want to read clear privacy and terms pages that explain how my data is handled,
so that I can trust the app and the stores accept the submission.

## Context & Why This Story Is Different

This is **not** a feature story — it is a **compliance + accuracy** story. The deliverable is *legal text published at a public URL* plus the in-app links that point to it. The single biggest risk is **a legal page that lies about the system** (claims encryption we don't have, lists sub-processors we stopped using, promises a self-serve delete button that doesn't exist). The planning docs (PRD, epics, architecture) are **stale on exactly these points** — see "🚨 Stale-Doc Overrides" below. **The Content Source of Truth in Dev Notes is authoritative; the epics/PRD/architecture wording is NOT.**

Two hosting/scope facts shape everything:
- There is **no domain yet** — the app talks to the raw IP `http://167.235.63.129`. The HTTPS public domain (`survivethetalk.com` family) is provisioned in **Story 10.2**, and the store listing that consumes the URL is **Story 10.3**. So 10.1's job is **content + a stable serving path + configurable in-app links**, not the final public HTTPS URL.
- The app already opens the privacy URL in an external browser (it does **not** render legal text in-app). So we host **HTML pages**; no new in-app legal screen is needed.

## Acceptance Criteria

1. **Privacy Policy is published at a stable public path served by our own backend, reachable WITHOUT authentication.** A `GET` to the privacy path returns `200` and HTML (not the JSON envelope, not a 401). [Epics AC1]

2. **The Privacy Policy content is factually accurate to the running system** and covers, at minimum:
   - **Data collected:** email address; call metadata (scenario, timestamps, duration, checkpoints passed, survival %, tier-at-call); the LLM-generated **debrief summary** (not the raw transcript); per-scenario best score & attempt count; subscription verification artifacts + expiry.
   - **Voice handling:** audio is streamed in real time to the speech-to-text provider for transcription and **never stored** as audio; **no voiceprint / biometric identifier is derived or retained** (BIPA). Process-and-discard.
   - **Transcript handling:** the full conversation transcript is **never persisted**; only a distilled, LLM-generated debrief summary is stored. (⚠️ Do NOT claim "transcripts stored, AES-256 at rest" — that is the stale PRD wording and is **false** against the code.)
   - **Third-party sub-processors (the REAL current list):** Soniox (STT), Groq (character LLM + checkpoint judging + debrief generation), Cartesia (TTS; ElevenLabs is a configurable fallback), LiveKit (real-time WebRTC transport), Resend (transactional email for login codes), Apple App Store / Google Play (subscription purchase & validation). State what each receives (voice audio vs. text vs. email vs. purchase token).
   - **User rights:** how to request **deletion and export** of personal data (GDPR Art 17/20) — see D4 for the MVP mechanism.
   - **Data location & security:** stored in a database on an EU-region VPS (Hetzner, Falkenstein/Nuremberg — GDPR-friendly), access-controlled, encrypted **in transit** (TLS). Describe what is true; do not overstate at-rest encryption.

3. **The Privacy Policy explicitly contains the AI disclosure (FR39 / EU AI Act Art. 50):** it states the user is interacting with **AI-generated characters and AI-generated voices, not real humans**, and that voice is processed in real time but never stored. [Epics AC2]

4. **Terms of Service is published at a stable public path (same hosting as the Privacy Policy)** and covers:
   - **Subscription terms — accurate to the build:** `$1.99 USD / week`, **auto-renewable**, single weekly plan (product id `stt_weekly_199`); free users get **3 free calls** (lifetime, free-era counted), subscribers get **3 calls per day**.
   - **Cancellation:** managed via the platform store (Apple Settings → Subscriptions / Google Play → Subscriptions); there is **no in-app cancel button**; auto-renew continues until cancelled.
   - **Payment data:** card/payment data is handled entirely by Apple/Google; **no card data is stored on our servers**.
   - **Content disclaimer:** scenarios are **simulated confrontation/roleplay** for language practice; content warnings precede intense scenarios.
   - **Age restriction:** 13+ (Apple) / PEGI 12 (Google). [Epics AC3]

5. **Both pages comply with the process-and-discard architecture (NFR10):** the content asserts no raw-audio storage and no biometric-data retention, consistent with the code. [Epics AC4]

6. **In-app links point to the published pages (no dead/placeholder URLs):**
   - The onboarding **Consent screen** privacy link resolves to the real published privacy URL (currently it hardcodes `https://survivethe.talk/privacy`, which does not exist).
   - The **Paywall** exposes functional **Privacy Policy** and **Terms of Use** links (Apple Guideline 3.1.2 requires both in the binary for auto-renewable subscriptions; today the paywall has neither).
   - All in-app legal URLs are built from a **single configurable base constant** so Story 10.2 can flip IP→domain in one place.

7. **Gates green:** `flutter analyze` clean, `flutter test` green, `ruff check`/`ruff format`/`pytest` green (incl. `test_migrations` — N/A here, no migration), plus the Smoke Test Gate below.

## Tasks / Subtasks

- [ ] **Task 1 — Author the Privacy Policy HTML** (AC: 2, 3, 5)
  - [ ] Write `server/static/legal/privacy.html` (or the route-served equivalent per D1) as a self-contained, styled-but-minimal HTML page (one `<style>` block, no external assets — must render standalone in a browser).
  - [ ] Source EVERY factual claim from the **Content Source of Truth** table in Dev Notes. Do not copy stale PRD/epics wording.
  - [ ] Include: effective date, data-controller identity + contact (D5), the AI disclosure paragraph (AC3), the sub-processor list (AC2), the rights/deletion section (D4).
  - [ ] Add a short "not legal advice / review recommended before public launch" internal note in the story record (NOT on the public page).

- [ ] **Task 2 — Author the Terms of Service HTML** (AC: 4)
  - [ ] Write `server/static/legal/terms.html` mirroring the privacy page's structure/styling.
  - [ ] Subscription terms verbatim-accurate: `$1.99/week`, auto-renewable, `stt_weekly_199`, 3 free (lifetime) / 3 per day (paid), store-managed cancellation, no card data stored, content disclaimer, 13+/PEGI 12.

- [ ] **Task 3 — Serve the pages publicly from the backend** (AC: 1) — see D1 for the mechanism choice
  - [ ] Add a new **unauthenticated** router `server/api/routes_legal.py` exposing `GET /legal/privacy` and `GET /legal/terms` returning `HTMLResponse` (these are the ONLY HTML/browser-facing routes — they intentionally bypass the `{data, meta}` JSON envelope; document that in a module docstring).
  - [ ] Register it in `server/api/app.py` alongside the other routers — **without** `AUTH_DEPENDENCY` (mirror `routes_health`/`routes_auth` which are public; do NOT mirror the auth-gated routers).
  - [ ] Confirm the HTML still also resolves via Caddy's existing `/static/*` mount (belt-and-suspenders) since the files live under `server/static/`.

- [ ] **Task 4 — Configurable base + wire the in-app links** (AC: 6)
  - [ ] Add a single legal-URL source (e.g. `kPrivacyPolicyUrl` / `kTermsOfServiceUrl` derived from one base constant) in the client, co-located with / derived from `ApiClient.baseUrl` so 10.2 flips it in one place. Remove the dead `https://survivethe.talk/privacy` literal.
  - [ ] Point the Consent screen privacy link at `kPrivacyPolicyUrl` (`consent_screen.dart:24`, `_launchPrivacyPolicy`).
  - [ ] Add **Privacy Policy** + **Terms of Use** tappable links to the paywall (`paywall_sheet.dart`), near the existing `_kLegal` caption — reuse the `TapGestureRecognizer` + `launchUrl(externalApplication)` pattern from the consent screen. Keep the two-ink, low-furniture paywall styling (see "The Handler's Brief" rulebook).
  - [ ] (Optional, low cost) Add the same two links to the manage drawer (`features/subscription/views/manage_sheet.dart`) for parity.

- [ ] **Task 5 — Tests** (AC: 1, 6, 7)
  - [ ] Server: pytest that `GET /legal/privacy` and `GET /legal/terms` return `200`, `content-type: text/html`, are reachable **without** an `Authorization` header, and that the body contains the load-bearing strings (e.g. "AI-generated", a sub-processor name, "$1.99", "auto-renew", "13+"). One negative test: an unknown `/legal/<x>` returns `404`.
  - [ ] Client: widget/unit tests that the consent link and the two new paywall links invoke `launchUrl` with the expected `kPrivacyPolicyUrl` / `kTermsOfServiceUrl` (inject the launcher — follow the `StoreLinks` injectable `_launch` pattern so tests don't touch the real plugin).

- [ ] **Task 6 — Deploy + Smoke Test Gate** (AC: 1, 7) — see the gate section below.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story adds a public backend route and deploys HTML to the VPS → the gate applies. There is **no DB migration and no DB write**, so the DB boxes are N/A with rationale.
>
> **Transition rule:** Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->

- [ ] **Privacy page round-trip (public, no JWT).** `curl` against the IP returns `200` + HTML containing the AI disclosure and at least one real sub-processor name.
  - _Command:_ `curl -sS -i http://167.235.63.129/legal/privacy | head -n 20`
  - _Expected:_ `200`, `content-type: text/html`, body contains "AI-generated" and e.g. "Soniox"/"Groq"
  - _Actual:_ <!-- paste output -->

- [ ] **Terms page round-trip (public, no JWT).** `curl` returns `200` + HTML containing the subscription terms.
  - _Command:_ `curl -sS -i http://167.235.63.129/legal/terms | head -n 20`
  - _Expected:_ `200`, body contains "$1.99" and "auto-renew"
  - _Actual:_ <!-- paste output -->

- [ ] **Negative path.** An unknown legal path returns `404` (not a 500, not a blank 200).
  - _Command:_ `curl -sS -o /dev/null -w "%{http_code}\n" http://167.235.63.129/legal/does-not-exist`
  - _Expected:_ `404`
  - _Actual:_ <!-- paste output -->

- [ ] **DB side-effect.** N/A — this story performs zero DB reads/writes and adds no migration.

- [ ] **DB backup pre-deploy.** N/A — no schema change. (The deploy workflow still auto-backups; no manual snapshot required.)

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 50 --since "5 min ago"` shows no ERROR/Traceback for the three requests above.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

## Dev Notes

### 🚨 Stale-Doc Overrides — the planning docs are WRONG on these; the code wins

| Topic | Stale doc says | **Reality (use this)** | Evidence |
|---|---|---|---|
| TTS provider | epics: "Cartesia"; PRD: "Cartesia Sonic 3" only | **Cartesia is the default; ElevenLabs is a configurable fallback** | `server/config.py:62` (`tts_provider="cartesia"`), `server/CLAUDE.md` §5 |
| LLM provider | epics: "OpenRouter"; PRD: "Qwen3.5 Flash" | **Groq** (Llama 3.3 70B character + Llama 4 Scout judge/debrief). NOT OpenRouter/Qwen anymore | `server/config.py` (groq_*), `server/CLAUDE.md` §4 |
| Transcript storage | PRD §Data: "Call transcripts stored server-side, encrypted at rest (AES-256)" | **Transcript is NEVER persisted; only the LLM-distilled debrief JSON is stored** | `server/db/migrations/011_debriefs.sql:9-10`, `pipeline/debrief_teardown.py` |
| At-rest encryption | PRD/architecture: "AES-256 encryption at rest" | **No at-rest encryption exists in code.** Do NOT claim it in the policy | no AES/Fernet/crypto in `server/` |
| Privacy URL / domain | consent_screen hardcodes `https://survivethe.talk/privacy`; Caddyfile uses `api.survivethetalk.com` | **No domain yet; app uses raw IP `http://167.235.63.129`.** Domain finalized in Story 10.2 | `client/lib/core/api/api_client.dart:8`, `deploy/Caddyfile:1` |

### Content Source of Truth (authoritative facts for the legal pages)

**What is stored in the database** (SQLite at `/opt/survive-the-talk/data/db.sqlite`; all `server/db/migrations/`):
- `users`: `email` (plaintext, unique), `jwt_hash` (hash of session token, not the token), `tier` (`free`/`paid`), `tier_changed_at`, `created_at`.
- `auth_codes`: `email`, 6-digit `code`, `expires_at`, `used` (transient login codes).
- `call_sessions`: `user_id`, `scenario_id`, `started_at`, `duration_sec`, `cost_cents`, `status`, `checkpoints_passed`, `total_checkpoints`, `gifted`, `tier_at_call`.
- `debriefs`: `survival_pct`, checkpoint counts, **`debrief_json`** = the LLM-distilled summary (the ONLY persisted reflection of a conversation), `prompt_version`, `created_at`.
- `user_progress`: per (user, scenario) `best_score`, `attempts`.
- `purchases`: `platform`, `product_id`, `verification_token` (store JWS / purchaseToken — NOT payment data), `transaction_id`, `original_transaction_id`, `validation_status`, `expires_at`.
- `subscription_events`: webhook idempotency ledger (`provider`, `notification_id`, `notification_type`, timestamps).
- `scenarios`: read-only content templates — **no user data**.

**Voice & transcript:** raw audio is streamed device→LiveKit→Soniox (STT); no `.wav`/`.pcm` is ever written to disk or DB. A temporary text transcript exists only in-process / `/tmp/transcript_{session}.json` during a call and is **not** persisted to the DB. The conversation transcript text is sent to Groq to generate the debrief, then discarded; only `debrief_json` survives.

**Sub-processors and what each receives:**
- **Soniox** (STT) — receives live voice audio.
- **Groq** (LLM) — receives conversation **text** (user turns + context) for character replies, checkpoint judging, and debrief generation. No audio.
- **Cartesia** (TTS, default) / **ElevenLabs** (fallback) — receives character reply **text** to synthesize speech.
- **LiveKit** (WebRTC transport) — carries the real-time audio stream between device and server bot.
- **Resend** (email) — receives the user's **email address** + the 6-digit login code.
- **Apple App Store / Google Play** (IAP) — receive/validate the **purchase token**; they (not us) handle card/payment data.
- No server-side analytics/crash SDK exists today (analytics is Story 10.4).

**Auth:** passwordless — request a 6-digit code by email, verify it, receive a JWT. No passwords stored.

**Subscription (Epic 8, live as of 2026-06-18):** `$1.99 USD/week`, auto-renewable, single plan, product id `stt_weekly_199` (placeholder until Walid creates it in the stores). Free tier = **3 lifetime free-era calls** (`server/usage.py` `CALLS_PER_PERIOD=3`; free-era counted via `call_sessions.tier_at_call`); paid tier = **3 calls/UTC-day**. Cancellation is store-side only (no in-app cancel button); manage handoff via `StoreLinks` (`client/lib/features/subscription/services/store_links.dart`). No card data stored server-side (NFR11 — zero PCI scope).

**Data deletion/export (GDPR Art 17/20):** **No self-serve endpoint exists** (searched — none). See D4 for the MVP mechanism the policy should describe.

### Reuse-don't-reinvent (server)
- **Router registration:** `server/api/app.py:241-249` (`app.include_router(...)`). Public routers carry **no** `AUTH_DEPENDENCY` — copy `routes_health.py` / `routes_auth.py`, NOT the auth-gated `routes_scenarios.py`.
- **Auth dependency:** `server/api/middleware.py` (`require_auth`, `AUTH_DEPENDENCY`). Legal routes must omit it.
- **Static serving already works:** `deploy/Caddyfile:2-6` serves `server/static/*` directly at `/static/*`. Put the HTML under `server/static/legal/` so it is reachable both via Caddy (`/static/legal/privacy.html`) and via the clean FastAPI route (`/legal/privacy`).
- **Deploy:** `.github/workflows/deploy-server.yml` rsyncs `server/` to the VPS and atomically swaps the `current` symlink, then restarts `pipecat.service` and health-checks. New files under `server/static/` and `server/api/` ship automatically on push to `main`. systemd unit: `deploy/pipecat.service` (`ExecStart=.venv/bin/python main.py`).
- **Response convention:** the JSON `{data, meta}` / `{error}` envelope lives in `server/api/responses.py`. **Legal routes are the deliberate exception** — they return `HTMLResponse`. Note this in the module docstring so a future reviewer doesn't "fix" it into the envelope.

### Reuse-don't-reinvent (client)
- **External-link launch pattern:** `consent_screen.dart` already uses `TapGestureRecognizer` + `launchUrl(uri, mode: LaunchMode.externalApplication)`. Reuse it verbatim for the paywall links; `url_launcher` is already a dependency.
- **Injectable launcher for tests:** `StoreLinks` injects `_launch` so tests assert the URL without the real plugin — follow that seam for the new paywall links.
- **Single base URL:** `client/lib/core/api/api_client.dart:8` (`baseUrl = 'http://167.235.63.129'`). Derive the legal URLs from one constant so 10.2 flips IP→domain once.
- **Paywall styling:** keep the paywall's two-ink, zero-furniture discipline ("The Handler's Brief" rulebook, `_bmad-output/planning-artifacts/...` design rules) — links as quiet underlined text near `_kLegal` (`paywall_sheet.dart:362-368`), not buttons/boxes.
- **Flutter test traps** (`client/CLAUDE.md`): `FlutterSecureStorage.setMockInitialValues({})` in `setUp` for any storage-touching test; force phone viewport for layout; no hardcoded hex (token-enforcement test scans `lib/`).

### Anti-patterns to avoid
- ❌ Claiming AES-256 at-rest encryption, transcript storage, or Cartesia/OpenRouter as sub-processors. All false/stale — the policy becomes inaccurate.
- ❌ Putting the legal routes behind `AUTH_DEPENDENCY` (store crawlers & the consent screen hit them with no token).
- ❌ Wrapping the HTML in the `{data, meta}` envelope.
- ❌ Hardcoding a domain that doesn't exist yet (`survivethe.talk`). Use the configurable base on the current IP; 10.2 owns the domain.
- ❌ Building a self-serve delete-account endpoint here (scope creep → its own story; see D4).
- ❌ Adding a new in-app legal *screen* — the app opens the hosted page in a browser; no in-app renderer is wanted.

### Open Decisions (defaults chosen — confirm with Walid; see end-of-story recap)
- **D1 — Hosting mechanism:** *Default:* clean public FastAPI `GET /legal/{privacy,terms}` HTML routes (store-friendly URL, easy pytest round-trip), with the files also under `server/static/legal/` so Caddy serves them too. *Alt:* static-only at `/static/legal/*.html` (zero code, uglier URL).
- **D2 — Domain split:** *Default:* 10.1 hosts on the current IP over HTTP and wires a configurable base; **Story 10.2 finalizes the HTTPS public domain URL**, and **Story 10.3** puts it in the store listings. (Stores require an HTTPS public URL — that arrives with 10.2, not here.)
- **D3 — Who authors the legal text:** *Default:* the dev agent drafts complete, plain-English, accurate pages from the Content Source of Truth; Walid reviews; the story record notes "functional draft, professional legal review recommended before public launch."
- **D4 — Deletion/export mechanism:** *Default:* the policy documents a **manual, email-request** process (user emails the contact address; operator deletes/export manually) for MVP, and a self-serve account-deletion endpoint is flagged as a **follow-up** (Google Play increasingly expects an in-app or URL account-deletion path — relevant to Story 10.3/10.5).
- **D5 — Data-controller identity, contact email, effective date:** *Default:* contact = Walid's email (`guetarni.walid@gmail.com`) and a placeholder controller name + today's effective date, **pending Walid's confirmation** of the real legal/business identity before the page goes public. The page cannot be truly public-ready until D5 is confirmed.

### Project Structure Notes
- New files: `server/api/routes_legal.py`, `server/static/legal/privacy.html`, `server/static/legal/terms.html`, and the matching test(s) under `server/tests/`.
- Touched: `server/api/app.py` (register router); `client/lib/.../consent_screen.dart`, `client/lib/features/paywall/views/paywall_sheet.dart`, `client/lib/core/api/api_client.dart` (or a new `core/legal_urls.dart`), optional `manage_sheet.dart`; plus client tests.
- No DB migration, no schema change, no new server dependency (FastAPI's `HTMLResponse` is built-in).
- This is the **first story of Epic 10** — epic flipped `backlog → in-progress`.

### References
- Story spec: [epics.md §Story 10.1](_bmad-output/planning-artifacts/epics.md) (lines 1566-1588)
- Requirements: [prd.md](_bmad-output/planning-artifacts/prd.md) FR24, FR28, FR30, FR35-FR39, NFR10/NFR11; "Legal & Compliance" (lines ~305-308, 500-501); age rating 13+/PEGI 12 (line 305)
- Compliance/hosting: [architecture.md](_bmad-output/planning-artifacts/architecture.md) §Security (lines 277-283), §Static Assets / Caddy (308-313), EU data center (388)
- Server patterns: [server/CLAUDE.md](server/CLAUDE.md) §4 (Groq), §5 (Cartesia default); `server/api/app.py`, `server/api/responses.py`, `server/api/middleware.py`
- Hosting/deploy: [deploy/Caddyfile](deploy/Caddyfile), [.github/workflows/deploy-server.yml](.github/workflows/deploy-server.yml), [deploy/pipecat.service](deploy/pipecat.service)
- Client patterns: [consent_screen.dart](client/lib/features/onboarding/presentation/consent_screen.dart), [paywall_sheet.dart](client/lib/features/paywall/views/paywall_sheet.dart), [store_links.dart](client/lib/features/subscription/services/store_links.dart), [client/CLAUDE.md](client/CLAUDE.md)
- Subscription truth: Stories `8-1`/`8-2`/`8-3` files; `server/config.py`, `server/usage.py`, `client/lib/features/subscription/services/in_app_purchase_service.dart`
- Apple Guideline 3.1.2 (auto-renewable subs require Privacy Policy + Terms/EULA links in the binary); EU AI Act Article 50 (AI disclosure); GDPR Art 17/20; BIPA (no biometric retention)

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
