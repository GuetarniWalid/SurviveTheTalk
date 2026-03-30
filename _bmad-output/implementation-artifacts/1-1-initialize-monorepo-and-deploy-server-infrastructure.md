# Story 1.1: Initialize Monorepo and Deploy Server Infrastructure

Status: ready-for-dev

## Story

As a developer,
I want the project monorepo initialized and the Hetzner VPS configured with Caddy reverse proxy,
So that I have the foundation to deploy and iterate on the voice pipeline.

## Acceptance Criteria

1. **AC1 — Monorepo Structure:**
   Given a fresh development environment,
   When I clone the repository,
   Then I find `client/` (Flutter project), `server/` (Python project), and `deploy/` directories matching the architecture spec,
   And `.gitignore`, `.env.example`, and `pyproject.toml` are properly configured.

2. **AC2 — VPS with HTTPS:**
   Given a Hetzner CX22 VPS is provisioned,
   When the deploy configuration is applied,
   Then Caddy serves HTTPS on the configured domain with valid Let's Encrypt certificate,
   And systemd service files for Pipecat and Caddy are installed and enabled.

3. **AC3 — Environment Variables:**
   Given environment variables are set in `.env`,
   When the server starts,
   Then all API keys (Soniox, OpenRouter, Cartesia, LiveKit) are loaded from environment variables and never hardcoded.

## Tasks / Subtasks

- [ ] **Task 1: Initialize Git repository and monorepo root** (AC: #1)
  - [ ] 1.1 Run `git init` at project root
  - [ ] 1.2 Create `.gitignore` covering Python, Flutter/Dart, OS files, `.env`, `*.sqlite`, IDE configs
  - [ ] 1.3 Create root `README.md` with project name only (minimal)

- [ ] **Task 2: Initialize Flutter client project** (AC: #1)
  - [ ] 2.1 Run `flutter create --org com.surviveTheTalk --platforms ios,android survive_the_talk` inside `client/` (then move contents up or create directly as `client/`)
  - [ ] 2.2 Add dependencies: `livekit_client: ^2.6.4`, `rive: ^0.14.2`
  - [ ] 2.3 Configure `analysis_options.yaml` with strict linting (include `package:flutter_lints`)
  - [ ] 2.4 Verify `flutter analyze` passes with zero issues
  - [ ] 2.5 Verify `flutter test` passes (default widget test)
  - [ ] 2.6 Create empty `client/assets/rive/` directory with `.gitkeep` for future fallback character

- [ ] **Task 3: Initialize Python server project** (AC: #1, #3)
  - [ ] 3.1 Run `uv init` inside `server/`
  - [ ] 3.2 Set `.python-version` to `3.12`
  - [ ] 3.3 Run `uv add "pipecat-ai[soniox,openai,cartesia,livekit]"`
  - [ ] 3.4 Create `server/config.py` — load env vars via `pydantic-settings` (`uv add pydantic-settings`)
  - [ ] 3.5 Create directory skeleton: `server/pipeline/`, `server/api/`, `server/db/`, `server/db/migrations/`, `server/models/`, `server/static/rive/`, `server/tests/`
  - [ ] 3.6 Create `server/main.py` — minimal placeholder (print config loaded, exit)
  - [ ] 3.7 Verify `ruff check .` and `ruff format --check .` pass (`uv add --dev ruff pytest`)

- [ ] **Task 4: Create deploy configuration files** (AC: #2, #3)
  - [ ] 4.1 Create `deploy/Caddyfile` with reverse proxy config for FastAPI + static file serving
  - [ ] 4.2 Create `deploy/pipecat.service` systemd unit file
  - [ ] 4.3 Create `deploy/caddy.service` systemd unit file (or use Caddy's built-in systemd unit)
  - [ ] 4.4 Create `deploy/backup.sh` — SQLite daily backup script (placeholder, no DB yet)
  - [ ] 4.5 Create `deploy/.env.example` — template with all required env var names, no secrets

- [ ] **Task 5: Provision Hetzner CX22 VPS** (AC: #2)
  - [ ] 5.1 Provision CX22 (2 vCPU, 4GB RAM, 40GB NVMe) in EU datacenter via Hetzner Cloud console or `hcloud` CLI
  - [ ] 5.2 Configure SSH key access, disable password auth
  - [ ] 5.3 Set up firewall: allow 22 (SSH), 80 (HTTP→HTTPS redirect), 443 (HTTPS)
  - [ ] 5.4 Point domain DNS A record to VPS IP
  - [ ] 5.5 Install Caddy via official APT repo
  - [ ] 5.6 Install Python 3.12 + uv
  - [ ] 5.7 Deploy Caddyfile, verify HTTPS with valid Let's Encrypt cert
  - [ ] 5.8 Install systemd service files, enable services
  - [ ] 5.9 Create `/opt/survive-the-talk/` directory structure on VPS
  - [ ] 5.10 Create `.env` on VPS with all API keys populated

- [ ] **Task 6: Verify end-to-end** (AC: #1, #2, #3)
  - [ ] 6.1 Clone repo on a fresh machine, verify monorepo structure is correct
  - [ ] 6.2 Verify `flutter analyze` + `flutter test` pass in `client/`
  - [ ] 6.3 Verify `ruff check .` + `ruff format --check .` + `pytest` pass in `server/`
  - [ ] 6.4 Verify HTTPS endpoint responds on VPS (Caddy health check)
  - [ ] 6.5 Verify `.env` is NOT committed to git

## Dev Notes

### Architecture Compliance

This story implements the **monorepo structure** defined in [Source: architecture.md#Project Structure & Boundaries].

**EXACT directory structure required:**

```
surviveTheTalk2/
├── .gitignore
├── client/                             # Flutter app
│   ├── pubspec.yaml
│   ├── analysis_options.yaml
│   ├── lib/
│   │   └── main.dart                   # PoC: single file
│   ├── test/
│   │   └── widget_test.dart
│   ├── android/
│   ├── ios/
│   └── assets/
│       └── rive/                       # Empty for now
│
├── server/                             # Python backend
│   ├── pyproject.toml
│   ├── .python-version                 # 3.12
│   ├── main.py
│   ├── config.py
│   ├── pipeline/                       # Empty dirs for now
│   ├── api/
│   ├── db/
│   │   └── migrations/
│   ├── models/
│   ├── static/
│   │   └── rive/
│   └── tests/
│
└── deploy/
    ├── Caddyfile
    ├── pipecat.service
    ├── backup.sh
    └── .env.example
```

### Critical Technical Specifications

**Caddy v2.11.1 — Caddyfile configuration:**
```
api.survivethetalk.com {
    handle /static/* {
        root * /opt/survive-the-talk/server
        file_server
    }
    handle {
        reverse_proxy localhost:8000
    }
}
```
- Caddy automatically provisions Let's Encrypt TLS certificates
- HTTP→HTTPS redirect is automatic
- No manual cert management needed

**systemd service file pattern (`deploy/pipecat.service`):**
```ini
[Unit]
Description=SurviveTheTalk Pipecat Voice Pipeline
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/survive-the-talk/server
EnvironmentFile=/opt/survive-the-talk/.env
ExecStart=/opt/survive-the-talk/server/.venv/bin/python main.py
Restart=on-failure
RestartSec=5s
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Python config.py pattern (pydantic-settings):**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    soniox_api_key: str
    openrouter_api_key: str
    cartesia_api_key: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    jwt_secret: str = ""
    resend_api_key: str = ""
    database_path: str = "/opt/survive-the-talk/data/db.sqlite"

    model_config = {"env_file": ".env"}
```

**`.env.example` template:**
```
# AI Services
SONIOX_API_KEY=
OPENROUTER_API_KEY=
CARTESIA_API_KEY=

# LiveKit
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# Auth (not needed for PoC, but defined for structure)
RESEND_API_KEY=
JWT_SECRET=

# Database
DATABASE_PATH=/opt/survive-the-talk/data/db.sqlite
```

### Library Versions (Verified March 2026)

| Library | Version | Manager |
|---------|---------|---------|
| Flutter | 3.41.x stable | flutter SDK |
| livekit_client | ^2.6.4 | pub.dev |
| rive | ^0.14.2 | pub.dev |
| Python | 3.12 | .python-version |
| pipecat-ai | 0.0.108 (latest) | PyPI via uv |
| pydantic-settings | latest | PyPI via uv |
| ruff | latest (dev dep) | PyPI via uv |
| pytest | latest (dev dep) | PyPI via uv |
| Caddy | 2.11.1 | APT repo |
| uv | 0.11.2 | astral.sh |

### Pipecat 0.0.108 Notes

- **Extras required:** `soniox`, `openai` (for OpenRouter compatibility), `cartesia`, `livekit`
- **VADParams default changed:** `stop_secs` is now 0.2s (was 0.8s) — better for conversational flow
- **stop_frame_timeout_s** default is now 3.0s (was 2.0s)
- Python >=3.10 required, 3.12 recommended

### Flutter Client — PoC Scope

The Flutter client for PoC is intentionally **zero architecture**:
- Single `lib/main.dart` with a "Call" button
- No state management, no routing, no BLoC
- Dependencies added now (`livekit_client`, `rive`) but not used until stories 1.3 and later
- `analysis_options.yaml` must enforce strict analysis from day 1

**`flutter create` command:**
```bash
flutter create --org com.surviveTheTalk --platforms ios,android client
```
This creates the Flutter project directly in the `client/` directory.

### Hetzner VPS Setup

- **Plan:** CX22 — 2 shared vCPU, 4GB RAM, 40GB NVMe, 20TB traffic
- **Cost:** €3.79/month
- **Datacenter:** EU (Falkenstein or Nuremberg) for GDPR compliance
- **OS:** Ubuntu 22.04 LTS (or 24.04 LTS)
- **Security hardening:**
  - SSH key-only auth (disable `PasswordAuthentication` in `/etc/ssh/sshd_config`)
  - UFW firewall: allow 22, 80, 443 only
  - Non-root user for services (`www-data`)

### .gitignore Must Include

```
# Environment
.env
*.env

# Python
__pycache__/
*.pyc
.venv/
*.sqlite

# Flutter/Dart
client/.dart_tool/
client/.packages
client/build/
client/.flutter-plugins
client/.flutter-plugins-dependencies
*.iml

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
Thumbs.db

# Hetzner
*.pem
```

### What NOT to Do

- **DO NOT** create `fastapi.service` yet — FastAPI is not needed for PoC (story 1.2 uses a minimal HTTP endpoint inside the Pipecat process)
- **DO NOT** create database files or migration SQL yet — no DB until MVP
- **DO NOT** add `flutter_bloc`, `go_router`, `dio`, `sqflite`, or any MVP-only dependencies
- **DO NOT** hardcode any API keys anywhere — `.env` only
- **DO NOT** create multiple Dart files — PoC is single `main.dart`
- **DO NOT** modify the default Flutter `main.dart` beyond what's needed to verify the project compiles
- **DO NOT** set up CI/CD (GitHub Actions) — that's MVP scope

### Pre-Commit Checks (Non-Negotiable)

**Flutter (in `client/`):**
```bash
flutter analyze   # Must show: No issues found!
flutter test      # Must show: All tests passed!
```

**Python (in `server/`):**
```bash
ruff check .         # Must pass with zero issues
ruff format --check . # Must pass (properly formatted)
pytest               # Must pass (even if no tests yet — returns 0)
```

### Project Structure Notes

- The monorepo has two independent technology domains: Flutter (Dart) in `client/` and Python in `server/`
- Each has its own package management (`pubspec.yaml` / `pyproject.toml`), test framework, and linting
- `deploy/` contains infrastructure-as-code for the VPS — separate from both client and server
- The VPS path `/opt/survive-the-talk/` is the production deployment root on the server
- All static assets served by Caddy from `/opt/survive-the-talk/server/static/`

### References

- [Source: architecture.md#Project Structure & Boundaries] — Complete monorepo directory tree
- [Source: architecture.md#Infrastructure & Deployment] — Hetzner CX22, Caddy, systemd, backup strategy
- [Source: architecture.md#Core Architectural Decisions] — VPS consolidation, Caddy choice
- [Source: architecture.md#Implementation Patterns & Consistency Rules] — Naming conventions, enforcement guidelines
- [Source: architecture.md#Starter Template Evaluation] — Flutter create + uv init commands
- [Source: prd.md#Phase 0 — Proof of Concept] — PoC scope definition
- [Source: epics.md#Epic 1] — Epic context and cross-story dependencies

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
