# Story 10.2: Provision Domain, DNS, SSL, and Server Infrastructure

Status: in-progress

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want the production backend reachable over a stable HTTPS domain with a valid certificate (instead of a raw cleartext IP),
so that the app, the App Store, and the Play Store can talk to a secure, review-ready backend.

## Context & Why This Story Is Different

This is **not** a from-scratch provisioning story. **Almost all of the "provision the server" work already exists and is live** — the epic's wording was written before the PoC server was ever stood up. The Hetzner VPS, the systemd services, Caddy, the database, and **every external API key** are already running in production. What is genuinely missing is the **one thing the stores actually gate on: a public HTTPS domain with a real TLS certificate.** Today the app talks to `http://167.235.63.129` — a raw IP over **cleartext HTTP**. Apple ATS and Google Play both reject a cleartext-IP backend, so this is a hard launch blocker.

So the real deliverable is a **cutover + reconciliation**, in three moves:
1. **DNS** — point `api.survivethetalk.com` at the VPS (the apex `survivethetalk.com` is already registered, DNS hosted on **Cloudflare**, and Resend-verified).
2. **Caddy → HTTPS** — replace the live `:80`-only Caddyfile with a domain Caddyfile so Caddy auto-provisions a Let's Encrypt cert and serves TLS on `:443`, **without breaking the raw-IP endpoint the current app + CI still use** during the transition.
3. **Client flip** — change `ApiClient.baseUrl` from the IP to `https://api.survivethetalk.com` in the ONE place Story 10.1 set up for exactly this, and tighten the now-unneeded cleartext allowances.

**The "Current State of the World" table in Dev Notes is authoritative — it was captured live off the running VPS on 2026-06-22.** The epics/PRD/architecture wording is stale on multiple infrastructure points (see "🚨 Stale-Doc Overrides"); do not implement the phantom services or routing they describe.

**Agent vs. Walid split:** per the standing autonomy rule, the agent does everything it can — Caddy deploy, cert verification, the client flip, all smoke tests. The **single** step the agent cannot do is **add the Cloudflare DNS record** (no Cloudflare credentials/MCP are in scope). That is Walid's one manual action (exact click-path in Task 1), unless he hands over a scoped Cloudflare API token, in which case the agent does it too. Walid also runs the final Pixel 9 smoke gate on a new build.

## Acceptance Criteria

1. **`api.survivethetalk.com` resolves to the production VPS.** A public DNS lookup of `api.survivethetalk.com` returns `167.235.63.129` (A record). The record is **DNS-only / un-proxied** at Cloudflare (grey cloud) so Caddy — not Cloudflare — terminates TLS with its own Let's Encrypt certificate (per Architecture §Transport Security: "TLS 1.3 via Caddy, automatic Let's Encrypt"). An `AAAA` record is added too **iff** the VPS has a public IPv6 address (verify on the box); otherwise A-only is acceptable. [Epics AC2]

2. **Caddy serves the backend over HTTPS on the domain with a valid, browser-trusted certificate.** `curl https://api.survivethetalk.com/health` returns `200` with the standard `{data, meta}` envelope and `data.git_sha` matching the deployed commit; the TLS certificate is issued by Let's Encrypt (ISRG/R-series) and within its validity window. [Epics AC2]

3. **All plaintext HTTP to the domain is redirected to HTTPS.** `curl -I http://api.survivethetalk.com/health` returns a redirect (Caddy's automatic `308`/`301` to `https://`), not a `200` served over cleartext. [Epics AC3 — "all HTTP traffic redirected to HTTPS"]

4. **Caddy reverse-proxies the API and serves static assets — no phantom `/api/*` prefix, no phantom `fastapi.service`.** Caddy routes the catch-all to the single FastAPI/Pipecat process on `localhost:8000`, and serves `server/static/*` directly under `/static/*` (so the Story 10.1 legal HTML is reachable at `https://api.survivethetalk.com/static/legal/*.html` as well as the primary `/legal/*` FastAPI route). The `/static/*` root points at the live release path `/opt/survive-the-talk/current/server/static` (NOT the stale `/opt/survive-the-talk/server/static`). [Epics AC3, reconciled to reality]

5. **The raw-IP endpoint keeps working through the transition.** After the cutover, `curl http://167.235.63.129/health` still returns `200` so the **currently-installed** app build and the CI `/health` check are not bricked while the new HTTPS build rolls out. (Removing this transitional cleartext endpoint is explicitly deferred to the launch checklist, Story 10.5 — see DEC-2.) [non-regression]

6. **The Flutter client targets the HTTPS domain, in one place.** `ApiClient.baseUrl` is `https://api.survivethetalk.com` (no trailing slash); `LegalUrls` (derived from it) now yields `https://api.survivethetalk.com/legal/{privacy,terms}` and is hardened against a future trailing-slash on the base (the deferred Story 10.1 review item). Cleartext-traffic allowances that only existed to reach the IP are removed: Android `usesCleartextTraffic` is set to `false` (or dropped), and the iOS `NSAllowsArbitraryLoads` exception is removed/replaced with an HTTPS-only posture. [Epics AC2; unblocks 10.3/10.5 store builds; NFR13 HTTPS-everywhere]

7. **The already-provisioned infrastructure is verified accurate, not re-created.** The story records evidence that: the VPS runs **Ubuntu 24.04** with a **single** `pipecat.service` (FastAPI runs inside it via `main.py`) + `caddy.service` (there is NO separate `fastapi.service`); LiveKit Cloud is configured (`LIVEKIT_URL`/`API_KEY`/`API_SECRET` present); and the real external-service keys are all set in `/opt/survive-the-talk/.env`: **Soniox** (STT), **Groq** (LLM — replaces the stale OpenRouter/Qwen), **Cartesia** + **ElevenLabs** (TTS — replaces the stale Cartesia-only), **Resend** (email), **LiveKit**. No keys are printed in the story (names only). [Epics AC1, AC4, AC5 — reconciled]

8. **Gates green + the Smoke Test Gate below passes.** `flutter analyze` clean, `flutter test` green (incl. the updated `api_client_test.dart` baseURL assertion), `ruff check`/`ruff format`/`pytest` green (no server code or migration changes are expected in this story). The repo `deploy/Caddyfile` is updated to match exactly what is deployed (source-of-truth honesty), even though CI does not deploy it.

## Tasks / Subtasks

- [ ] **Task 1 — DNS: point `api.survivethetalk.com` at the VPS** (AC: 1) — **Walid's one manual step** (or hand the agent a Cloudflare API token)
  - [ ] In the **Cloudflare** dashboard for `survivethetalk.com` → **DNS → Records → Add record**:
    - Type `A`, Name `api`, IPv4 `167.235.63.129`, **Proxy status = DNS only (grey cloud)**, TTL Auto.
  - [ ] On the VPS, check for a public IPv6 (`ip -6 addr show scope global`). If one exists, add a matching `AAAA` record (Name `api`, that IPv6, DNS-only). If none, skip — A-only is fine.
  - [ ] Agent verifies propagation before touching Caddy: `dig +short api.survivethetalk.com @1.1.1.1` returns `167.235.63.129`. Do NOT proceed to Task 3 until this resolves publicly.
  - [ ] ⚠️ **Why DNS-only, not proxied:** the orange-cloud proxy would make Cloudflare terminate TLS at its edge and break Caddy's Let's Encrypt issuance / the architecture's "Caddy auto Let's Encrypt" contract. If Walid prefers Cloudflare-proxied later, that's a separate hardening decision (Full-Strict + a CF origin cert) — out of scope here.

- [x] **Task 2 — Pre-flight: confirm 443 is reachable and capture the baseline** (AC: 2) — agent, read-only
  - [x] Confirm inbound `:443` is open (Hetzner Cloud firewall + host `ufw`/`iptables`). Port `:80` is already open (Caddy listens there now) so the Let's Encrypt HTTP-01 challenge can complete; clients need `:443` open to connect over HTTPS. If `:443` is blocked, open it (this is the agent's job) and record the change.
  - [x] Snapshot the live Caddyfile and service state before editing, so the change is reversible: `cat /etc/caddy/Caddyfile`, `systemctl is-active caddy pipecat.service`.

- [ ] **Task 3 — Caddy: cut over to the domain (HTTPS) while keeping the IP alive** (AC: 2, 3, 4, 5) — agent, **manual deploy** (CI does NOT ship the Caddyfile)
  - [ ] Update `deploy/Caddyfile` to the domain config below (this is also the repo source-of-truth fix — corrects the stale static `root` and drops the vestigial `/auth/*` + `/api/*` handles, which all just proxied to `:8000` anyway):
    ```
    api.survivethetalk.com {
        handle /static/* {
            uri strip_prefix /static
            root * /opt/survive-the-talk/current/server/static
            file_server
        }
        handle {
            reverse_proxy localhost:8000
        }
    }

    # Transitional backward-compat (DEC-2): the currently-installed app and the
    # CI /health check still hit the raw IP over HTTP. Caddy cannot get a
    # Let's Encrypt cert for a bare IP, so this stays plain HTTP. REMOVE before
    # public launch (Story 10.5) once every install points at the domain.
    http://167.235.63.129 {
        reverse_proxy localhost:8000
    }
    ```
  - [ ] Deploy it to the VPS manually and reload (NOT via the GitHub Actions deploy — that workflow's `paths:` deliberately exclude the Caddyfile):
    `scp deploy/Caddyfile root@167.235.63.129:/etc/caddy/Caddyfile`, then `ssh root@167.235.63.129 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy'`.
  - [ ] Watch Caddy obtain the cert on first reload: `journalctl -u caddy -n 50 --no-pager` should show a successful Let's Encrypt issuance for `api.survivethetalk.com` (no rate-limit / challenge failures). Confirm Caddy now listens on `:443` (`ss -tlnp | grep ':443'`).

- [ ] **Task 4 — Client: flip the base URL to the domain + tighten cleartext** (AC: 6) — agent. **Only after Task 3 verifies HTTPS is live**, so the build is never pointed at a dead domain.
  - [ ] `client/lib/core/api/api_client.dart:8` — `baseUrl = 'https://api.survivethetalk.com'`.
  - [ ] `client/test/core/api/api_client_test.dart:99` — update the assertion to the new HTTPS base URL.
  - [ ] `client/lib/core/legal_urls.dart` — harden the concat so a future trailing slash on `baseUrl` can't yield `//legal/...` (the deferred Story 10.1 review item). Keep it a single derived source.
  - [ ] `client/android/app/src/main/AndroidManifest.xml:20` — set `android:usesCleartextTraffic="false"` (or remove the attribute). The new build talks HTTPS-only; the kept-alive IP block is for OLD installs / CI, which the new build never uses.
  - [ ] `client/ios/Runner/Info.plist:5-9` — remove `NSAllowsArbitraryLoads` (HTTPS-only ATS posture). iOS can't be device-verified until Story 10.4, but make the code change now so the store build is correct; note it in Completion Notes.
  - [ ] Run `flutter analyze` + `flutter test` and fix any fallout (the baseURL test, any test hardcoding the IP).

- [x] **Task 5 — Verify the already-provisioned infra (don't re-create it)** (AC: 7) — agent, read-only; record evidence in the story
  - [x] OS: `Ubuntu 24.04` (`/etc/os-release`).
  - [x] Services: `pipecat.service` + `caddy.service` both `active`; **no** `fastapi.service` exists (`systemctl list-unit-files | grep -E 'fastapi|pipecat|caddy'`).
  - [x] `.env` key NAMES present (do not print values): `SONIOX_API_KEY`, `GROQ_API_KEY`, `CARTESIA_API_KEY`, `ELEVENLABS_API_KEY`, `RESEND_API_KEY`, `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`, `JWT_SECRET`. Note `OPENROUTER_API_KEY` is present but legacy/optional (migrated to Groq).

- [ ] **Task 6 — Reconcile repo source-of-truth + commit** (AC: 8)
  - [ ] Ensure `deploy/Caddyfile` in the repo matches exactly what was deployed.
  - [ ] All gates green; complete the Smoke Test Gate boxes with pasted evidence.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story changes the live reverse-proxy / TLS posture and the deployed Caddy config → the gate applies. There is **no DB write and no migration** in this story → the DB-side-effect and DB-backup boxes are **N/A** (Caddy reload doesn't touch SQLite). Caddy already auto-backs the DB on every code deploy, and this is a config reload, not a code deploy.
>
> **Transition rule:** Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output as proof.

- [ ] **Deployed.** `systemctl is-active caddy.service pipecat.service` → both `active`; Caddy reloaded with the domain config and is listening on `:443`.
  - _Proof:_ <!-- paste systemctl + `ss -tlnp | grep ':443'` -->

- [ ] **HTTPS happy-path round-trip (valid cert).** `curl https://api.survivethetalk.com/health` → `200` + `{data, meta}` envelope; `data.git_sha` == deployed HEAD; cert issued by Let's Encrypt and valid.
  - _Command:_ `curl -sS https://api.survivethetalk.com/health` and `echo | openssl s_client -connect api.survivethetalk.com:443 -servername api.survivethetalk.com 2>/dev/null | openssl x509 -noout -issuer -dates`
  - _Expected:_ `200` + git_sha match; issuer `C=US, O=Let's Encrypt, ...`; `notAfter` in the future
  - _Actual:_ <!-- paste -->

- [ ] **HTTP→HTTPS redirect on the domain.** `curl -sS -I http://api.survivethetalk.com/health` → a `308`/`301` `Location: https://...` (not a cleartext `200`).
  - _Command:_ `curl -sS -I http://api.survivethetalk.com/health`
  - _Expected:_ `30x` + `Location: https://api.survivethetalk.com/...`
  - _Actual:_ <!-- paste -->

- [ ] **Legal pages reachable over HTTPS (Story 10.1 contract holds on the domain).** `GET https://api.survivethetalk.com/legal/privacy` → `200` HTML; and the Caddy static mount `GET https://api.survivethetalk.com/static/legal/privacy.html` → `200` HTML.
  - _Command:_ `curl -sS -o /dev/null -w "%{http_code}\n" https://api.survivethetalk.com/legal/privacy` and `.../static/legal/privacy.html`
  - _Expected:_ `200` and `200`
  - _Actual:_ <!-- paste -->

- [ ] **Raw-IP endpoint still alive (transition non-regression, AC5).** `curl http://167.235.63.129/health` → `200`.
  - _Command:_ `curl -sS -o /dev/null -w "%{http_code}\n" http://167.235.63.129/health`
  - _Expected:_ `200`
  - _Actual:_ <!-- paste -->

- [ ] **DB side-effect — N/A.** This story is a reverse-proxy/TLS config reload; it writes no rows and adds no migration.
- [ ] **DB backup before deploy — N/A.** No DB schema change; no destructive operation against SQLite.

- [ ] **Server logs clean on the happy path.** `journalctl -u caddy -u pipecat.service -n 80 --since "5 min ago"` shows the successful Let's Encrypt issuance and no ERROR/Traceback for the requests above.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

**On-device gate (Walid, Pixel 9 — Android only; iOS deferred to 10.4):** a new Android build with `baseUrl = https://api.survivethetalk.com` (a) launches and loads the scenario list, (b) completes one short call (proves the API initiate/end + token path works over HTTPS — note WebRTC itself is unaffected, it uses LiveKit Cloud directly), (c) the paywall/consent legal links open the HTTPS pages. A ready-to-play script will be handed over before the gate per the project's voice-smoke-test rule.

## Dev Notes

### 🚨 Stale-Doc Overrides — the epics/PRD/architecture are WRONG on these; the live server wins

| Topic | Stale doc says | **Reality (use this)** | Evidence |
|---|---|---|---|
| systemd services | epics AC1 + architecture: 3 services "pipecat.service, **fastapi.service**, caddy.service" | **No `fastapi.service`.** FastAPI runs INSIDE `pipecat.service` via `main.py`. Two units only: `pipecat.service` + `caddy.service` | live `systemctl list-unit-files` (2026-06-22); `deploy/pipecat.service` `ExecStart=.venv/bin/python main.py` |
| Caddy routing | epics AC3: "Caddy routes `/api/*` → FastAPI" | **No `/api` prefix.** Real paths are `/health`, `/auth/*`, `/scenarios`, `/calls/*`, `/user/*`, `/debriefs/*`, `/legal/*`. Caddy catch-all → `localhost:8000` | live Caddyfile; `client/lib/core/api/api_client.dart` call sites |
| LiveKit transport | epics AC3: "LiveKit traffic passes through [Caddy] on standard WebRTC ports" | **LiveKit Cloud handles WebRTC directly** — device ↔ LiveKit Cloud, NOT through Caddy/the VPS. Caddy proxies ONLY the REST API | architecture §844-863 ("Boundary 2"), §321-323 |
| LLM provider | epics AC5 + architecture: "OpenRouter (Qwen3.5 Flash)" | **Groq** (Llama 3.3 70B character + Llama 4 Scout judge/debrief). `OPENROUTER_API_KEY` is legacy/optional | `.env` has `GROQ_API_KEY`+`CHARACTER_MODEL`; `server/CLAUDE.md` §4 |
| TTS provider | epics AC5: "Cartesia"; architecture: "Cartesia Sonic 3" only | **Cartesia is default, ElevenLabs is a configurable fallback** (both keys set) | `.env` `TTS_PROVIDER=cartesia` + `ELEVENLABS_*`; `server/CLAUDE.md` §5 |
| Live serving | implied "HTTPS domain" | **Today it's `http://167.235.63.129` cleartext, Caddy `:80`-only, no `:443` listener.** This story creates the HTTPS domain | live Caddyfile + `ss -tlnp` (2026-06-22) |
| Hosting provider | architecture mentions a Hostinger alternative | Production is **Hetzner @ `167.235.63.129`**. A separate **stopped/unused Hostinger VPS** (`srv1341085`, `193.203.169.132`) exists — **do NOT use or provision it** | Hetzner IP range; Hostinger API shows that box `state: stopped` |

### Current State of the World (captured LIVE off the VPS, 2026-06-22 — this is ground truth)

- **VPS:** Hetzner, `167.235.63.129`, **Ubuntu 24.04.3 LTS**. EU region (Falkenstein/Nuremberg, GDPR-friendly — already asserted in the 10.1 privacy policy).
- **Live `/etc/caddy/Caddyfile`** (the thing this story replaces):
  ```
  :80 {
      handle /auth/* { reverse_proxy localhost:8000 }
      handle /api/*  { reverse_proxy localhost:8000 }   # vestigial — no /api prefix exists
      handle         { reverse_proxy localhost:8000 }
  }
  ```
  Note: it has **no `/static/*` mount** and binds `:80` only. Caddy is **not listening on `:443`**.
- **Services:** `caddy.service` active, `pipecat.service` active. A disabled `caddy-api.service` leftover exists (ignore it). FastAPI/Pipecat python listens on `0.0.0.0:8000`.
- **`.env` keys present** (names only): `SONIOX_API_KEY`, `GROQ_API_KEY`, `CHARACTER_MODEL`, `CARTESIA_API_KEY`, `ELEVENLABS_API_KEY`/`ELEVENLABS_MODEL`/`ELEVENLABS_VOICE_ID`, `TTS_PROVIDER`, `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`, `RESEND_API_KEY`, `JWT_SECRET`, `DATABASE_PATH`, `ENVIRONMENT`, `OPENROUTER_API_KEY` (legacy), plus several feature flags. → **AC5/AC4 are already satisfied; verify, don't re-create.**
- **Domain:** `survivethetalk.com` is **registered and its DNS is hosted on Cloudflare** (`conrad.ns.cloudflare.com`, `keira.ns.cloudflare.com`). It is **Resend-verified** (DKIM/SPF/DMARC live — that's how the login-code emails already send from `noreply@survivethetalk.com`). The subdomain **`api.survivethetalk.com` does NOT resolve yet** — that A record is the net-new DNS work.
- **Firewall:** ports 22 / 80 / 443 are the intended public surface (memory). `:80` is confirmed open (Caddy serves it). **Verify `:443` is open** before expecting external HTTPS to work.

### The cutover sequence MUST be ordered (this is the #1 way to brick something)

1. DNS A record live + propagated (`dig` confirms) →
2. `:443` confirmed open →
3. Caddy domain config deployed + Let's Encrypt cert issued + `https://.../health` verified →
4. ONLY THEN flip the client `baseUrl` + remove cleartext.

Flipping the client before HTTPS is live would ship a build that can't reach the backend. Keep the raw-IP `:80` block the whole time so the **currently-installed Pixel 9 build keeps working** until the new build is installed.

### Reuse-don't-reinvent

- **One base-URL constant, by design:** Story 10.1 deliberately routed every legal URL through `ApiClient.baseUrl` via `LegalUrls` "so Story 10.2 flips IP→domain in ONE place." Flip the one constant; `LegalUrls` follows automatically. Do not scatter the domain.
- **Caddy auto-HTTPS is the whole mechanism:** giving Caddy a site address that is a domain (not `:80`/an IP) makes it auto-provision Let's Encrypt and auto-redirect HTTP→HTTPS. No `tls`, `acme`, or redirect blocks needed. Don't hand-roll certbot.
- **Static mount already designed:** the `/static/*` handler (corrected `root`) makes `server/static/*` reachable — this is the belt-and-suspenders path Story 10.1 anticipated for the legal HTML on the domain (`/static/legal/*.html`), complementing the primary `/legal/*` FastAPI route.
- **Manual Caddy deploy is the established pattern:** `deploy/README.md` and the CI `paths:` filter both state the Caddyfile is a manual one-shot (scp + `caddy validate` + `systemctl reload caddy`). Editing the repo Caddyfile alone does nothing — push it to the box.
- **SSH access:** `ssh root@167.235.63.129` (id_ed25519). `caddy reload` (not restart) for zero-drop config changes.

### Anti-patterns to avoid

- ❌ Proxying the `api` record through Cloudflare (orange cloud) — breaks Caddy's Let's Encrypt issuance and the architecture's TLS contract. Use DNS-only (grey cloud).
- ❌ Creating a `fastapi.service`, an `hcloud`-provisioned new VPS, or touching the stopped **Hostinger** box. The Hetzner server is already running everything.
- ❌ Deploying the Caddyfile via `git push` and assuming CI ships it — CI's `paths:` exclude it on purpose. It must be scp'd + reloaded manually.
- ❌ Pointing the static `root` at `/opt/survive-the-talk/server/static` (doesn't exist) — use `/opt/survive-the-talk/current/server/static` (the symlinked release).
- ❌ Flipping the client `baseUrl` before HTTPS is verified live, or killing the raw-IP `:80` block in this story (it would brick the currently-installed app + the CI `/health` check). Removal is deferred to 10.5.
- ❌ Re-adding/keeping `NSAllowsArbitraryLoads` / `usesCleartextTraffic=true` in the store-bound build — the whole point is HTTPS-only for store acceptance (NFR13). The transitional cleartext lives only in the kept-alive *server* IP block, not in the new *client*.
- ❌ Printing any `.env` secret value into the story/logs — key NAMES only.

### Decisions

- **DEC-1 — Cloudflare proxy mode (NEEDS WALID, or a CF API token): RECOMMEND DNS-only (grey cloud).** Caddy terminates TLS with Let's Encrypt, matching the architecture. The agent has no Cloudflare credentials, so **Walid adds the A record** (Task 1 click-path) — unless he provides a scoped Cloudflare API token, in which case the agent adds it. ⚠️ This is the one true blocker / hand-off in the story.
- **DEC-2 — Keep the raw-IP `:80` block alive (RECOMMEND, agent default).** Prevents bricking the installed app + CI healthcheck during rollout. It's an unencrypted endpoint for the same JWT-gated backend; **flag for removal in the Story 10.5 launch checklist** once every install is on the domain. (Surfacing this transitional-cleartext trade-off explicitly per `feedback_surface_behavioral_tradeoffs_as_decisions`.)
- **DEC-3 — Domain = `api.survivethetalk.com` (RECOMMEND, confirm).** Already the value in `deploy/Caddyfile` + architecture §946, and the apex is Resend-verified. Legal/privacy URL becomes `https://api.survivethetalk.com/legal/privacy` (a public, stable HTTPS URL — sufficient for store submission; a prettier apex/`www` is not required for MVP).
- **DEC-4 — `AAAA` record: add iff the VPS has a public IPv6** (dev checks `ip -6 addr` on the box). Architecture says "A/AAAA"; A-only is acceptable if there's no IPv6.
- **DEC-5 — CI healthcheck stays on the IP (RECOMMEND, no workflow change).** Because the IP block stays alive (DEC-2), `curl http://167.235.63.129/health` keeps passing — avoids a chicken-and-egg where editing the workflow triggers a deploy whose new domain healthcheck could run before DNS/cert are live. Revisit when the IP block is removed in 10.5.

### Project Structure Notes

- **Server/deploy (manual deploy, not CI):** `deploy/Caddyfile` (domain + IP blocks, corrected static root). Live target: `/etc/caddy/Caddyfile` via scp + `caddy validate` + `systemctl reload caddy`.
- **Client (one-line flip + hardening):** `client/lib/core/api/api_client.dart` (`baseUrl`), `client/lib/core/legal_urls.dart` (trailing-slash hardening), `client/android/app/src/main/AndroidManifest.xml` (`usesCleartextTraffic`), `client/ios/Runner/Info.plist` (drop `NSAllowsArbitraryLoads`), `client/test/core/api/api_client_test.dart` (baseURL assertion).
- **No server Python change, no migration, no new dependency.** This is config + a client constant.
- **External/manual:** the Cloudflare A (+ optional AAAA) record — Walid (or agent w/ token).
- This is the **second story of Epic 10** (10.1 done). Epic 10 is already `in-progress`.

### References

- Story spec: [epics.md §Story 10.2](_bmad-output/planning-artifacts/epics.md) (lines 1590-1616) — note the stale provider/service wording overridden above.
- Architecture: [architecture.md](_bmad-output/planning-artifacts/architecture.md) §Transport Security (277-278), §Infrastructure (373-415), §Deploy Configuration / Caddyfile (944-957), §Boundaries 1 & 2 (844-863).
- Requirements: [prd.md](_bmad-output/planning-artifacts/prd.md) NFR13 (HTTPS everywhere), NFR10/NFR12 (server-side keys); validated in the 10.5 launch checklist.
- Live deploy mechanics: [deploy/Caddyfile](deploy/Caddyfile), [deploy/caddy.service](deploy/caddy.service), [deploy/pipecat.service](deploy/pipecat.service), [deploy/README.md](deploy/README.md), [deploy/setup-vps.sh](deploy/setup-vps.sh), [.github/workflows/deploy-server.yml](.github/workflows/deploy-server.yml) (note its `paths:` exclude the Caddyfile).
- Prior story (the IP→domain seam + deferred trailing-slash item): [10-1-...legal-compliance-pages.md](_bmad-output/implementation-artifacts/10-1-create-privacy-policy-terms-of-service-and-legal-compliance-pages.md) (AC6, review "Deferred" list).
- Client touch-points: [api_client.dart](client/lib/core/api/api_client.dart), [legal_urls.dart](client/lib/core/legal_urls.dart), [AndroidManifest.xml](client/android/app/src/main/AndroidManifest.xml), [Info.plist](client/ios/Runner/Info.plist).
- Memory: VPS access + Caddy-on-80 + firewall 22/80/443 (`MEMORY.md` §Infrastructure); standing autonomy (`feedback_vps_autonomy`); smoke-gate analysis mode (`feedback_smoke_gate_analysis_mode`).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (dev-story, 2026-06-22)

### Debug Log References

### Completion Notes List

**2026-06-22 — dev-story session 1 (read-only prep done; cutover BLOCKED on the Task 1 DNS hand-off).**

- ✅ **Task 2 (pre-flight) complete.** Live state captured off the VPS via SSH (read-only):
  - Firewall: `ufw` active with `443/tcp ALLOW` (v4+v6) and iptables `-A ufw-user-input -p tcp --dport 443 -j ACCEPT`. **`:443` is already open — no firewall change needed.** Ports 22/80/443 are the public surface as expected.
  - Caddy currently listens on `:80` only (`ss -tlnp` → `*:80 caddy pid=4150`); **no `:443` listener yet** (expected — Caddy binds `:443` once the domain Caddyfile is deployed in Task 3).
  - Baseline snapshot of the live `/etc/caddy/Caddyfile` taken for reversibility — it is the `:80`-only block with `/auth/*`, the vestigial `/api/*`, and the catch-all, **no `/static/*` mount** (matches the story's "Current State of the World" exactly).
  - `systemctl is-active caddy.service pipecat.service` → `active` / `active`.
- ✅ **Task 5 (infra verification) complete.** Evidence (no secret values printed):
  - OS: `Ubuntu 24.04.3 LTS (Noble Numbat)`.
  - Services: `caddy.service` (enabled/active) + `pipecat.service` (enabled/active); **no `fastapi.service`** — only a disabled `caddy-api.service` leftover (ignored per Dev Notes).
  - `.env` key NAMES present: `SONIOX_API_KEY`, `GROQ_API_KEY` + `CHARACTER_MODEL`, `CARTESIA_API_KEY`, `ELEVENLABS_API_KEY`/`ELEVENLABS_MODEL`/`ELEVENLABS_VOICE_ID`, `TTS_PROVIDER`, `RESEND_API_KEY`, `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`, `JWT_SECRET`, `DATABASE_PATH`, `ENVIRONMENT`, plus feature flags (`DTLN_ENABLED`, `HANGUP_LINE_GENERATION`, `HESITATION_DIAG`, `LATENCY_PROBE`, `CARTESIA_FRESH_CTX`, `CARTESIA_INSTRUMENT`, `TTS_AUDIO_DEBUG`). `OPENROUTER_API_KEY` present (legacy/optional). **AC5/AC4 satisfied — verified, not re-created.**
- ⚠️ **AAAA needed (AC1 / DEC-4).** The VPS HAS a public global IPv6 — `ip -6 addr show scope global` → `2a01:4f8:1c18:fbfd::1/64`. So an `AAAA api → 2a01:4f8:1c18:fbfd::1` (DNS-only) record must be added **in addition to** the `A` record. This was unknown at create-story (create-story said "check on the box"); now confirmed.
- 🚧 **BLOCKED — Task 1 (DNS) is the one true hand-off (DEC-1).** `api.survivethetalk.com` does not resolve yet. The agent has no Cloudflare credentials/MCP (DNS is hosted on Cloudflare, not Hostinger), so the A+AAAA records are Walid's manual step OR the agent does it if handed a scoped Cloudflare API token. Tasks 3 (Caddy cutover / Let's Encrypt — would fail/rate-limit without DNS), 4 (client flip — must not point at a dead domain), and 6 (commit) are gated until DNS resolves publicly (`dig +short api.survivethetalk.com @1.1.1.1` → `167.235.63.129`). Story stays `in-progress`.

**2026-06-22 — dev-story session 2 (the DNS hand-off escalated to an account-ACCESS problem).** Walid could not find the account managing the domain (tried `guetarni.walid@gmail.com` + `team@kindopia.com`). Investigation via public DNS + RDAP + his connected Gmail:

- **Registrar = GoDaddy.com, LLC** (IANA Registrar ID 146). Registered `2026-04-16`, expires `2027-04-16`; status `clientUpdateProhibited`/`clientTransferProhibited` etc. (`rdap.org/domain/survivethetalk.com`).
- **DNS zone = Cloudflare** (NS `conrad`/`keira.ns.cloudflare.com`, SOA primary `conrad`, admin `dns.cloudflare.com`). The zone also runs **Cloudflare Email Routing** (MX `route1/2/3.mx.cloudflare.net`, SPF `v=spf1 include:_spf.mx.cloudflare.net ~all`) and DMARC `p=quarantine; rua=mailto:dmarc_rua@onsecureserver.net` (GoDaddy infra).
- **Neither account is under the personal Gmail.** Gmail search `cloudflare newer_than:1y` → 0 threads; `godaddy OR survivethetalk` → 0 relevant. So both GoDaddy + Cloudflare were created under another email (likely `team@kindopia.com`, or a teammate's).
- **The blocker is now: regain access to the Cloudflare account** to add the `A`+`AAAA` records. Preferred over repointing nameservers at GoDaddy — that would drop the Cloudflare-managed records (Email Routing, plus any Resend records) and risk breaking the app's login-code emails. Recovery path handed to Walid: forgot-password probe on `dash.cloudflare.com` + `godaddy.com` with each candidate email; search the `team@kindopia.com` inbox for "cloudflare"/"godaddy" receipts (~2026-04-16). Fallback if Cloudflare is unrecoverable: get into GoDaddy → repoint NS to a DNS host Walid controls → recreate the full record set (the public records are enumerable via `dig` for a clean migration).

**2026-06-22 — dev-story session 3 (GoDaddy DNS cutover EXECUTED; awaiting propagation).** Cloudflare account never located (NS `conrad`/`keira` = a 3rd account; Resend is under `guetarni.walid@gmail.com` but the CF zone is not). Walid chose the GoDaddy fallback. Actions taken (Walid in GoDaddy UI, agent guiding + verifying):
- Switched nameservers **Cloudflare → GoDaddy default** (`ns19`/`ns20.domaincontrol.com`).
- Recreated the zone: `api` A=`167.235.63.129`, `api` AAAA=`2a01:4f8:1c18:fbfd::1`, plus the 5 Resend/DMARC records (DKIM `resend._domainkey`, `send` SPF, `dc-fd741b8612._spfm.send`, `send` MX=10, `_dmarc`). Full set + procedure: `ops-notes/godaddy-dns-cutover-2026-06-22.md`.
- **Verified authoritatively** against `ns19.domaincontrol.com` (`97.74.109.10`): all 7 records correct → **outbound login emails preserved**.
- **Dropped** Cloudflare Email-Routing (`contact@`/`hello@` forwarding) — accepted trade-off (published contact = `guetarni.walid@gmail.com`).
- **Now waiting on NS-delegation propagation** (public resolvers still cache `conrad`/`keira`). A background poll watches `1.1.1.1`+`8.8.8.8` for `api`→VPS; on success the agent runs Task 3 (deploy domain Caddyfile → Let's Encrypt) then Task 4 (client base-URL flip). ACME is deliberately NOT triggered until propagation completes (avoids LE failed-validation rate limits).

### File List

_Docs/ops only so far (DNS cutover done in the GoDaddy UI; Caddy + client changes pending propagation):_
- `_bmad-output/implementation-artifacts/10-2-provision-domain-dns-ssl-and-server-infrastructure.md` (status → in-progress, Tasks 1/2/5 done, Dev Agent Record)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (10-2 → in-progress)
- `_bmad-output/implementation-artifacts/ops-notes/godaddy-dns-cutover-2026-06-22.md` (NEW — full GoDaddy record set + cutover procedure)
- _Pending (after propagation):_ `deploy/Caddyfile`, `client/lib/core/api/api_client.dart`, `client/test/core/api/api_client_test.dart`, `client/lib/core/legal_urls.dart`, `client/android/app/src/main/AndroidManifest.xml`, `client/ios/Runner/Info.plist`

### Change Log

- 2026-06-22 — dev-story session 3: GoDaddy DNS cutover executed (Cloudflare account unrecoverable). NS switched to GoDaddy (ns19/ns20.domaincontrol.com); api A+AAAA + 5 Resend/DMARC records recreated and verified authoritatively; Cloudflare Email-Routing dropped (accepted). Awaiting NS propagation before Caddy/ACME. See ops-notes/godaddy-dns-cutover-2026-06-22.md.
- 2026-06-22 — dev-story session 2: DNS hand-off escalated to an account-access problem. Domain = GoDaddy registrar (reg. 2026-04-16) + Cloudflare DNS/Email-Routing; neither account under the personal Gmail. Walid to recover the Cloudflare account (or GoDaddy, with NS-repoint fallback) before Task 1 can complete. Story stays in-progress.
- 2026-06-22 — dev-story session 1: Tasks 2 (pre-flight) + 5 (infra verify) done read-only off the live VPS. `:443` already open at the firewall; confirmed single `pipecat.service`+`caddy.service` (no `fastapi.service`); all `.env` keys present (Groq/Cartesia+ElevenLabs/Soniox/Resend/LiveKit/JWT). Discovered the VPS has public IPv6 → AAAA record now required (AC1/DEC-4). Cutover (Tasks 3/4/6) blocked on the Cloudflare A+AAAA record (Task 1, Walid's hand-off). Status ready-for-dev → in-progress.
- 2026-06-22 — create-story: domain/DNS/SSL cutover story authored after live VPS inspection. Status → ready-for-dev.

## Questions for Walid (raised at create-story; none block writing the spec)

1. **DNS access (the one real hand-off):** Confirm you'll add the Cloudflare A record `api → 167.235.63.129` (DNS-only / grey cloud), OR give me a scoped Cloudflare API token and I'll add it. This is the single step I can't do myself — everything after it (Caddy, cert, client flip, smoke tests) I'll run.
2. **Domain confirmation (DEC-3):** OK to standardize the backend on `api.survivethetalk.com` (already in the repo Caddyfile + architecture)? Your privacy/terms URL then becomes `https://api.survivethetalk.com/legal/...`.
3. **Transitional cleartext (DEC-2):** I'll keep the old `http://167.235.63.129` endpoint alive so your currently-installed app doesn't break mid-cutover, and tag it for removal in the launch checklist (10.5). Good?
