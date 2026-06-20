# Story 10.1: Create Privacy Policy, Terms of Service, and Legal Compliance Pages

Status: review

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
   - **User rights:** the page describes a **working self-serve account-deletion** path (and a data export), GDPR Art 17/20 — see AC8. It also states that deleting the account does **not** auto-cancel an active store subscription (the user cancels that in the store).
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

7. **Gates green:** `flutter analyze` clean, `flutter test` green, `ruff check`/`ruff format`/`pytest` green (no migration in this story), plus the Smoke Test Gate below.

8. **A working self-serve account-deletion endpoint exists and is wired into the app (D4 — Walid chose to build it now, not the manual-email default).**
   - Authenticated `DELETE /user/me` (or equivalent) deletes the caller's account and **all** their personal rows — `users`, `auth_codes` (by email), `call_sessions`, `debriefs`, `user_progress`, `purchases`, `subscription_events` tied to them — in **one transaction**, respecting FK order (delete children before parents, or rely on `ON DELETE CASCADE` only if the schema actually declares it — verify, don't assume).
   - A companion **export** (`GET /user/data-export`) returns the caller's stored data as JSON (shared "gather my rows" logic; Art 20).
   - The app exposes a **"Delete my account"** action (in the account/manage surface). On success it **logs out and wipes the local cache** (the Story 9.1 de-auth side-effects key on the `AuthBloc → AuthInitial` transition — reuse that, do not invent a new wipe path).
   - The endpoint and the policy both state that deletion **does not cancel an active App Store / Google Play subscription** — the user must cancel that in the store.

## Tasks / Subtasks

- [x] **Task 1 — Author the Privacy Policy HTML** (AC: 2, 3, 5)
  - [x] Write `server/static/legal/privacy.html` (or the route-served equivalent per D1) as a self-contained, styled-but-minimal HTML page (one `<style>` block, no external assets — must render standalone in a browser).
  - [x] Source EVERY factual claim from the **Content Source of Truth** table in Dev Notes. Do not copy stale PRD/epics wording.
  - [x] Include: effective date, data-controller identity + contact (D5), the AI disclosure paragraph (AC3), the sub-processor list (AC2), the rights/deletion section (D4).
  - [x] Add a short "not legal advice / review recommended before public launch" internal note in the story record (NOT on the public page). — see Completion Notes.

- [x] **Task 2 — Author the Terms of Service HTML** (AC: 4)
  - [x] Write `server/static/legal/terms.html` mirroring the privacy page's structure/styling.
  - [x] Subscription terms verbatim-accurate: `$1.99/week`, auto-renewable, `stt_weekly_199`, 3 free (lifetime) / 3 per day (paid), store-managed cancellation, no card data stored, content disclaimer, 13+/PEGI 12.

- [x] **Task 3 — Serve the pages publicly from the backend** (AC: 1) — see D1 for the mechanism choice
  - [x] Add a new **unauthenticated** router `server/api/routes_legal.py` exposing `GET /legal/privacy` and `GET /legal/terms` returning `HTMLResponse` (these are the ONLY HTML/browser-facing routes — they intentionally bypass the `{data, meta}` JSON envelope; document that in a module docstring).
  - [x] Register it in `server/api/app.py` alongside the other routers — **without** `AUTH_DEPENDENCY` (mirror `routes_health`/`routes_auth` which are public; do NOT mirror the auth-gated routers).
  - [x] Confirm the HTML still also resolves via Caddy's existing `/static/*` mount (belt-and-suspenders) since the files live under `server/static/`. — files live under `server/static/legal/`; Caddy `/static/*` mount (`deploy/Caddyfile:2-6`) serves them at `/static/legal/*.html` on the eventual domain (Story 10.2). The clean `/legal/*` route is the primary contract on the current IP.

- [x] **Task 4 — Configurable base + wire the in-app links** (AC: 6)
  - [x] Add a single legal-URL source (`LegalUrls.privacyPolicy` / `LegalUrls.termsOfService`) derived from `ApiClient.baseUrl` (`client/lib/core/legal_urls.dart`) so 10.2 flips it in one place. Removed the dead `https://survivethe.talk/privacy` literal.
  - [x] Point the Consent screen privacy link at `LegalUrls.privacyPolicy` (`consent_screen.dart`, `_launchPrivacyPolicy`).
  - [x] Add **Privacy Policy** + **Terms of Use** tappable links to the paywall (`paywall_sheet.dart`), near the existing `_kLegal` caption — extracted a shared `LegalLinksRow` (`core/widgets/legal_links_row.dart`) reusing the `TapGestureRecognizer` + `launchUrl(externalApplication)` pattern. Kept the two-ink, low-furniture paywall styling.
  - [x] (Optional, low cost) Add the same two links to the manage drawer (`features/subscription/views/manage_sheet.dart`) for parity. — done (also on the new free Account sheet).

- [x] **Task 5 — Build self-serve account deletion + export** (AC: 8) — D4, Walid chose to build it now
  - [x] Add auth-gated `DELETE /user/me` to `server/api/routes_user.py` (reuse `AUTH_DEPENDENCY`; caller id from `request.state.user_id`). Deletes all of the user's rows in **one transaction** (`BEGIN IMMEDIATE`), FK-safe order. **Verified the actual FK `ON DELETE` behavior** in the migrations: `call_sessions→users` and `debriefs→call_sessions` have NO cascade (deleted explicitly, debriefs before call_sessions); `user_progress`/`purchases` DO declare cascade but are deleted explicitly anyway; `auth_codes` keyed by email; `subscription_events` has no `user_id` (idempotency ledger, nothing to delete). No schema change — `test_migrations` stays green.
  - [x] Add `GET /user/data-export` returning the caller's stored data as JSON (Art 20) — shared `gather_user_data` query (excludes `jwt_hash` / `verification_token` credentials).
  - [x] Return the canonical `{data, meta}` / `{error}` envelope (these are API routes, unlike the HTML legal routes).
  - [x] Client: add a **"Delete my account"** action in the account/manage surface. Per the 2026-06-19 decision (Walid: "Account visible pour tous"), the `Account` hub line is now shown to ALL users — paid → Manage drawer (+ Delete), free → new minimal `AccountSheet` (legal links + Delete). Confirm-then-delete via shared `DeleteAccountTile`; on success it **dispatches the new `SignOutEvent` → `AuthInitial`** (reuses the Story 9.1 cache-wipe + GoRouter redirect; no new wipe path). Failure shows inline (Epic 4 convention).

- [x] **Task 6 — Tests** (AC: 1, 6, 8)
  - [x] Server: pytest that `GET /legal/privacy` and `GET /legal/terms` return `200`, `content-type: text/html`, are reachable **without** an `Authorization` header, and the body contains load-bearing strings ("AI-generated", "Soniox"/"Groq", "$1.99", "auto-renew", "stt_weekly_199", "13"). Negative test: unknown `/legal/<x>` → `404` (`tests/test_routes_legal.py`).
  - [x] Server: pytest for `DELETE /user/me` against a seeded user with rows in every owned table — all rows gone, no FK/integrity error, second-delete → 401, unauth-delete → 401, does-not-touch-other-users; `GET /user/data-export` shape (`tests/test_account_deletion.py`).
  - [x] Client: widget/unit tests that the consent link + the two paywall links + the shared `LegalLinksRow` invoke the launcher with the expected URLs (injected launcher seams); `DeleteAccountTile` confirm → `onDelete` → `onDeleted` (success) / inline error (failure); `AuthBloc` `SignOutEvent` → deletes token + emits `AuthInitial`; `UserRepository.deleteAccount` → `DELETE /user/me`; scenario-list free-user Account-line opens the Account sheet.

- [x] **Task 7 — Deploy + Smoke Test Gate** (AC: 1, 7, 8) — see the gate section below.
  - [x] Automated gates green: `flutter analyze` clean, `flutter test` (686 passed), `ruff check`/`ruff format` clean, `pytest` (1018 passed).
  - [x] Deploy + the server-side Smoke Test Gate boxes below — deployed (CI `deploy-server.yml` run 27840892018 = success; running `git_sha` c73ca71); 7/7 smoke boxes PASS.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story adds public backend routes + deploys HTML AND adds a destructive account-deletion endpoint (D4) → the gate applies, including the DB boxes (deletion writes/removes rows). No migration / no schema change.
>
> **Transition rule:** Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output as proof.

- [x] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ `Active: active (running) since Fri 2026-06-19 17:57:18 UTC` / `Main PID: 1302059 (python)`. `GET /health` → `git_sha: c73ca71fdf2ba8498b0ca564add463db9b4565e2` == deployed HEAD (CI `deploy-server.yml` run 27840892018 = success).

- [x] **Privacy page round-trip (public, no JWT).** `curl` against the IP returns `200` + HTML containing the AI disclosure and at least one real sub-processor name.
  - _Command:_ `curl -sS -i http://167.235.63.129/legal/privacy | head -n 20`
  - _Expected:_ `200`, `content-type: text/html`, body contains "AI-generated" and e.g. "Soniox"/"Groq"
  - _Actual:_ `HTTP/1.1 200 OK` · `Content-Type: text/html; charset=utf-8` · `Via: 1.1 Caddy` · body grep matched: `AI-generated`, `Groq`, `Soniox`, `biometric`, `never stored`.

- [x] **Terms page round-trip (public, no JWT).** `curl` returns `200` + HTML containing the subscription terms.
  - _Command:_ `curl -sS -i http://167.235.63.129/legal/terms | head -n 20`
  - _Expected:_ `200`, body contains "$1.99" and "auto-renew"
  - _Actual:_ `HTTP/1.1 200 OK` · `Content-Type: text/html; charset=utf-8` · body grep matched: `$1.99`, `auto-renew`, `stt_weekly_199`.

- [x] **Negative path.** An unknown legal path returns `404` (not a 500, not a blank 200).
  - _Command:_ `curl -sS -o /dev/null -w "%{http_code}\n" http://167.235.63.129/legal/does-not-exist`
  - _Expected:_ `404`
  - _Actual:_ `HTTP 404`.

- [x] **DB side-effect — account deletion actually removes the rows.** Created a throwaway user `smoke-10-1-delete@example.invalid` (uid=3) on prod with a row in EVERY owned table (`ROWS_BEFORE = {call_sessions:1, user_progress:1, purchases:1, debriefs:1}`), minted its JWT, called `DELETE /user/me` from the IP, then read prod back via the venv `sqlite3`.
  - _Actual:_ first `DELETE /user/me` → `200 {"data":{"deleted":true}}`; second (orphan token) → `401 AUTH_UNAUTHORIZED` (idempotent). DB after: `ROWS_AFTER = {call_sessions:0, user_progress:0, purchases:0, users_by_uid:0, users_by_email:0, auth_codes_by_email:0, orphan_debriefs:0}` → `ALL_ZERO = True`. No FK/integrity error. Log: `account_deleted user_id=3` (INFO).

- [x] **DB backup taken BEFORE the deletion test.** Deletion is destructive — snapshot prod first.
  - _Proof:_ `deploy-server.yml` auto-snapshotted prod immediately before this release → `/opt/survive-the-talk/backups/db.pre-c73ca71.sqlite` (Jun 19 17:57), present and predating the 18:00 deletion test (fully restorable).

- [x] **Server logs clean on the happy path.** `journalctl -u pipecat.service --since "5 min ago"` shows no ERROR/Traceback for the requests above.
  - _Proof:_ grep for `ERROR|Traceback|Exception` over the window → empty; only `account_deleted user_id=3` INFO line for the deletion. Clean at 2026-06-19 18:00 UTC.

**Smoke gate: 7/7 PASS (server-side, agent-run). The on-device IAP/UI gate stays deferred (iOS blocked until Story 10-4), consistent with 8.1/8.2/8.3.**

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

**Data deletion/export (GDPR Art 17/20):** No self-serve endpoint exists today (searched — none). **D4 resolved: build one in this story** (`DELETE /user/me` + `GET /user/data-export`). The existing `routes_user.py` is the home (auth-gated). After deletion the client must run the existing log-out / `AuthBloc → AuthInitial` flow so the Story 9.1 local-cache wipe fires ([[feedback_cache_wipe_keys_on_auth_transition]]). Caveat to state in the policy: account deletion does not cancel an active store subscription.

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
- ❌ Adding a new in-app legal *screen* — the app opens the hosted page in a browser; no in-app renderer is wanted.
- ❌ (Deletion) Assuming FK cascades — verify the migrations' actual `ON DELETE` behavior before relying on it; delete children explicitly if not declared. Don't leave orphan rows (the whole point of a deletion endpoint is that *nothing* survives).
- ❌ (Deletion) Rolling a bespoke local-cache wipe — reuse the Story 9.1 `AuthInitial`-keyed de-auth path.

### Decisions (RESOLVED with Walid 2026-06-19)
- **D1 — Hosting mechanism — RESOLVED:** clean public FastAPI `GET /legal/{privacy,terms}` HTML routes (store-friendly URL, easy pytest round-trip), with the files also under `server/static/legal/` so Caddy serves them too.
- **D2 — Domain split — RESOLVED:** 10.1 hosts on the current IP over HTTP and wires a configurable base; **Story 10.2 finalizes the HTTPS public domain URL**, **Story 10.3** puts it in the store listings. (Stores require an HTTPS public URL — that arrives with 10.2.)
- **D3 — Who authors the legal text — RESOLVED: the dev agent drafts everything** — complete, plain-English, accurate pages from the Content Source of Truth. Record a note that this is a functional draft and professional legal review is recommended before public launch (not a dev blocker).
- **D4 — Deletion/export — RESOLVED: build the real self-serve endpoint NOW** (Walid chose this over the manual-email default). See AC8 + Task 5 — `DELETE /user/me` + `GET /user/data-export`, wired to a "Delete my account" in-app action that reuses the Story 9.1 de-auth/cache-wipe path.
- **D5 — Contact — RESOLVED: contact = `guetarni.walid@gmail.com`.** Use it + today's effective date. Controller name: use Walid's name as the individual operator unless he supplies a business entity later (he can swap it pre-launch).

### Project Structure Notes
- New files: `server/api/routes_legal.py`, `server/static/legal/privacy.html`, `server/static/legal/terms.html`, and matching test(s) under `server/tests/`.
- Touched (server): `server/api/app.py` (register the legal router); `server/api/routes_user.py` (+ `DELETE /user/me`, `GET /user/data-export`); the user/query layer for the cascade-delete + export gather.
- Touched (client): `consent_screen.dart`, `features/paywall/views/paywall_sheet.dart`, `core/api/api_client.dart` (or a new `core/legal_urls.dart`), `features/subscription/views/manage_sheet.dart` (Delete-my-account action), plus client tests.
- No DB migration, no schema change, no new server dependency (`HTMLResponse` is built-in). The deletion endpoint is DELETE statements only — but **verify FK `ON DELETE` behavior** in the existing migrations before relying on cascade.
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

claude-opus-4-8 (dev-story, 2026-06-19)

### Debug Log References

- Automated gates: `flutter analyze` → No issues found; `flutter test` → 686 passed; `ruff check .` / `ruff format --check .` → clean; `pytest` → 1018 passed.

### Completion Notes List

- **Legal text is a functional DRAFT (D3).** The dev agent authored both pages in plain English, every claim sourced from the Content Source of Truth (NOT the stale PRD/epics). **Professional legal review is recommended before public launch** — this is a recommendation, not a dev blocker. Controller name = Walid Guetarni (individual operator, swappable for a business entity pre-launch); contact = guetarni.walid@gmail.com; effective date = 19 June 2026.
- **Accuracy guardrails honored (anti-pattern list):** no AES-256-at-rest claim, no transcript-storage claim, Cartesia named as default TTS with ElevenLabs as a configurable fallback, Groq named as the LLM, real sub-processor list (Soniox/Groq/Cartesia/LiveKit/Resend/Apple/Google), no hardcoded domain (configurable base on the current IP).
- **FK behavior verified, not assumed (Story 10.1 anti-pattern).** `delete_user_account` deletes debriefs→call_sessions explicitly (no cascade on either FK), then user_progress/purchases (cascade-backed but deleted explicitly for determinism), auth_codes by email, then users. `subscription_events` has no `user_id` column → nothing user-scoped to delete. No migration / no schema change → `test_migrations` unaffected.
- **DECISION surfaced + resolved with Walid (per `feedback_surface_behavioral_tradeoffs_as_decisions`):** account deletion is a universal GDPR right but the only `Account` entry point was paid-only. Walid chose "Account visible to all" — paid opens the existing Manage drawer (+ a Delete line), free opens a new minimal `AccountSheet` (legal links + Delete). The export endpoint exists server-side (Art 20) but is not surfaced in the UI (AC8 only requires the Delete action client-side).
- **De-auth reuse:** added an explicit `SignOutEvent` to `AuthBloc` (deletes the token, emits `AuthInitial`) so deletion routes through the SAME `AuthInitial` transition the 401/expiry paths use — the Story 9.1 cache wipe + the GoRouter redirect fire unchanged (no new wipe path). [[feedback_cache_wipe_keys_on_auth_transition]]
- **Smoke gate scope:** this story's gate is server-side (public routes + a destructive deletion endpoint) and agent-runnable (curl + SSH/sqlite); recorded in the boxes below against the deployed build. The on-device IAP/UI gate stays DEFERRED (iOS blocked until Story 10-4), consistent with 8.1/8.2/8.3.

### File List

**Server (new):**
- `server/static/legal/privacy.html`
- `server/static/legal/terms.html`
- `server/api/routes_legal.py`
- `server/tests/test_routes_legal.py`
- `server/tests/test_account_deletion.py`

**Server (modified):**
- `server/api/app.py` (register the public legal router)
- `server/api/routes_user.py` (+ `DELETE /user/me`, `GET /user/data-export`)
- `server/db/queries.py` (+ `delete_user_account`, `gather_user_data`)
- `server/models/schemas.py` (+ `AccountDeletionOut`)

**Client (new):**
- `client/lib/core/legal_urls.dart`
- `client/lib/core/widgets/legal_links_row.dart`
- `client/lib/features/account/views/account_sheet.dart`
- `client/lib/features/account/widgets/delete_account_tile.dart`
- `client/test/core/widgets/legal_links_row_test.dart`
- `client/test/features/account/widgets/delete_account_tile_test.dart`
- `client/test/features/subscription/repositories/user_repository_test.dart`

**Client (modified):**
- `client/lib/core/api/api_client.dart` (+ `delete<T>`)
- `client/lib/features/subscription/repositories/user_repository.dart` (+ `deleteAccount`)
- `client/lib/features/auth/bloc/auth_event.dart` (+ `SignOutEvent`)
- `client/lib/features/auth/bloc/auth_bloc.dart` (+ `_onSignOut`)
- `client/lib/features/onboarding/presentation/consent_screen.dart` (configurable URL + launcher seam)
- `client/lib/features/paywall/views/paywall_sheet.dart` (+ legal links)
- `client/lib/features/subscription/views/manage_sheet.dart` (+ legal links + Delete; `onSignOut` param)
- `client/lib/features/scenarios/views/scenario_list_screen.dart` (Account line shown to all; routes free→AccountSheet, paid→ManageSheet; de-auth wiring)
- `client/test/features/auth/bloc/auth_bloc_test.dart` (+ SignOutEvent group)
- `client/test/features/onboarding/presentation/consent_screen_test.dart` (+ privacy-link launch test)
- `client/test/features/paywall/views/paywall_sheet_test.dart` (+ legal-links test)
- `client/test/features/subscription/views/manage_sheet_test.dart` (`onSignOut` arg)
- `client/test/features/scenarios/views/scenario_list_screen_test.dart` (AuthBloc harness; free-user Account test)

### Change Log

- 2026-06-19 — dev-story: legal pages (privacy + ToS HTML) served at public `GET /legal/{privacy,terms}`; configurable in-app legal URLs wired into consent + paywall + manage/account sheets; self-serve GDPR `DELETE /user/me` + `GET /user/data-export` with a universal in-app "Delete my account" surface. Status → review.

### Review Findings

_Formal adversarial `/bmad-code-review` (Opus 4.8, 3 parallel layers: Blind Hunter / Edge Case Hunter / Acceptance Auditor). 20+ raw findings → 1 decision-needed + 4 patch + 5 defer + 9 dismissed-as-noise. The #1 risk for this compliance story — a legal page that lies about the system — came back CLEAN: every load-bearing claim in `privacy.html` / `terms.html` was verified against the running code (Cartesia-default TTS confirmed at `server/config.py:62`, no AES-256/transcript-storage/OpenRouter claims, full real sub-processor list, AI disclosure present). The deletion endpoint is atomic, FK-verified, and reuses the Story 9.1 de-auth path._

**Review resolution (2026-06-20):** decision resolved (clean erasure), all 4 patches FIXED, 5 deferred, 9 dismissed. Gates re-run green: `flutter analyze` clean, `flutter test` 687 (+1 mic-permission privacy-link regression test), `ruff check`/`ruff format` clean, `pytest` 1018. The story's server-side smoke gate (7/7) stands — none of the patches touch a smoke-boxed path (legal pages + `delete_user_account` are byte-unchanged; P3/P4 touch only `GET /user/data-export`, unit-tested; P1/P2 are client, test-locked).

**Decision-needed (RESOLVED 2026-06-20 — Walid chose clean erasure):**

- [x] [Review][Decision][RESOLVED → dismissed] Account deletion leaves an active store subscription billing with NO server-side tombstone — `delete_user_account` hard-deletes the `purchases` row, so a later Apple/Google webhook (`DID_RENEW`/`EXPIRED`) for that still-active subscription can no longer be correlated to anyone (`get_purchase_by_original_transaction_id` → `None`). **Walid's call (2026-06-20): ACCEPT the clean erasure** — it is the GDPR Art-17-correct default (delete everything), the webhook handler no-ops harmlessly (idempotency ledger, returns 200), and the policy already states deletion does not cancel the store sub. No code change. [`server/db/queries.py:947-950`]

**Patch (all FIXED 2026-06-20):**

- [x] [Review][Patch] [HIGH] Second dead `https://survivethe.talk/privacy` link still ships — the mic-permission onboarding screen hardcoded the dead domain on a live, tappable button, untouched by the dev-story; violated AC6 ("no dead/placeholder URLs"). FIXED: removed the literal, added the `@visibleForTesting debugLaunch` seam, and pointed `_launchPrivacyPolicy` at `LegalUrls.privacyPolicy` (mirrors `consent_screen.dart`); added a regression widget test that taps the "What we do with your voice" link and asserts the configured URL. [`client/lib/features/onboarding/presentation/mic_permission_screen.dart:27,514`, `+mic_permission_screen_test.dart`]
- [x] [Review][Patch] [Low] `DeleteAccountTile._onTap` set the `_deleting` latch only AFTER `await showDialog`, so two rapid taps could stack two confirm dialogs → two `DELETE /user/me` calls. FIXED: added a synchronous `if (_deleting) return;` re-entry guard at the top of `_onTap`. [`client/lib/features/account/widgets/delete_account_tile.dart:36`]
- [x] [Review][Patch] [Low] Data export used `SELECT *` on `call_sessions`/`debriefs` while `users`/`purchases` were column-listed to scrub credentials. FIXED: made both column lists explicit (every current user-data column preserved — no Art-20 content dropped — so a future internal/credential column can't auto-leak). [`server/db/queries.py`]
- [x] [Review][Patch] [Low] `GET /user/data-export` returned the user's full PII with default (cacheable) headers. FIXED: set `Cache-Control: no-store` on the export response via an injected `Response`. [`server/api/routes_user.py` `export_data`]

**Deferred (see `deferred-work.md`):**

- [x] [Review][Defer] [Low] `launchUrl` result/exception ignored in `LegalLinksRow._open` (and consent/mic screens) — a failed browser launch is a silent no-op with no user feedback; matches the pre-existing consent-screen convention. [`client/lib/core/widgets/legal_links_row.dart:50`] — deferred, matches existing pattern
- [x] [Review][Defer] [Low] `LegalUrls` naive string concat would yield `//legal/...` if a future `ApiClient.baseUrl` gains a trailing slash (the Story 10.2 domain flip the doc-comment anticipates). [`client/lib/core/legal_urls.dart:52-53`] — deferred to Story 10.2 (owns the domain flip)
- [x] [Review][Defer] [Low] Post-deletion 401 burst — a concurrent in-flight authed request returning 401 after a successful delete can fire the global "Session expired" toast on top of the intentional sign-out (wrong copy for a self-initiated deletion). [`client/lib/core/api/auth_interceptor.dart`] — deferred, narrow timing window, non-trivial fix
- [x] [Review][Defer] [Low] Deletion mid-call wastes the ~8s debrief-LLM spend — the teardown's `generate_debrief` runs between an unlocked pre-check read and the locked write, so a concurrent delete can't stop it (no data corruption — the rowcount guard holds, rows are cleaned). [`server/pipeline/debrief_teardown.py`] — deferred, no correctness impact, narrow race
- [x] [Review][Defer] [Low] `gather_user_data` is unbounded (no streaming/pagination) — a heavy account materializes its entire history into one in-memory dict; the sibling `get_pending_purchases` uses `LIMIT` for exactly this reason (a GDPR export legitimately wants all rows, so the real fix is streaming, not a cap). [`server/db/queries.py:957`] — deferred, MVP-scale, post-MVP streaming

**Dismissed as noise (9):** inverted-TTS-provider claim (FALSE POSITIVE — Cartesia IS the default, `config.py:62`); JWT-valid-after-deletion (handled — `require_auth` DB-lookup + deleted `jwt_hash`, test-confirmed); `except BaseException` rollback (intentional/correct); import-time HTML read crashes boot (intentional, documented fail-loud, deploy health-gated); `-> dict` annotation (cosmetic); dead `else None` branch (harmless); export torn-snapshot (negligible best-effort artifact); `subscription_events` not deleted (no `user_id` — justified); `auth_codes` not in export (transient login codes — justified; deletion DOES remove them).
