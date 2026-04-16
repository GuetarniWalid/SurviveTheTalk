# Story 4.2: Build FastAPI Server with Passwordless Auth System

Status: done

---

## Intention (UX / Why)

**What the user experiences:**
This story is entirely invisible to the end user. It installs the server-side machinery that every subsequent MVP feature depends on: the FastAPI application that serves authentication endpoints, the SQLite database that stores users and auth codes, the JWT middleware that guards protected routes, and the Resend integration that actually delivers the 6-digit codes to user inboxes.

**Why it matters for the product:**
Story 4.3 (the Flutter auth flow) cannot ship without a backend to talk to. Story 5.1 (scenarios API) cannot ship without a JWT middleware to protect its routes. Story 6.1 (call initiation) cannot authorise a user's call without a `user_id` derived from a JWT. Every single MVP story after this one assumes there is a FastAPI server with the response envelope `{data, meta}` / `{error}`, ISO-8601 timestamps, snake_case JSON, and a working auth system.

**Why passwordless:**
The PRD deliberately chose email-only auth (no password field, no "sign in with Google", no SMS) to minimise onboarding friction and eliminate password-manager headaches for the mid-20s solo-user demographic. A 6-digit code is familiar (Notion, Slack, Substack use it), delivers well on mobile, and shifts secret storage to the user's email inbox (already authenticated).

**Why we accept "plain-text codes + 15-min expiry":**
Auth codes are short-lived, single-use, and one-at-a-time per email. Bcrypt-hashing them would add latency and debug friction for zero meaningful threat reduction (an attacker with DB access has already lost). The schema `auth_codes(email, code, expires_at, used)` from the architecture doc confirms this intent.

**Why we accept "stateless JWT validation":**
For a 1-rep-per-day MVP we do not need a token revocation list. Validating the JWT signature + `exp` on every request is sufficient. We still populate `users.jwt_hash` (bcrypt of the issued JWT) because the schema declares it — doing so leaves the door open for a future "log out all devices" feature without a migration.

---

## Concrete User Walk-Through (Adversarial)

_(Per Epic 3 retrospective Action Item #1: every story must contain an adversarial walk-through that exposes failure modes the happy path hides.)_

Consider four real scenarios a hostile or buggy client may trigger. Each must behave as described.

### Scenario A — Happy Path
1. Flutter `POST /auth/request-code` with `{"email": "walid@example.com"}`.
2. Server inserts row into `auth_codes`, generates 6-digit code `483910`, calls Resend, returns `200 {"data": {"message": "Code sent"}, "meta": {"timestamp": "..."}}` within 1.5 s.
3. Walid enters the code in Flutter.
4. Flutter `POST /auth/verify-code` with `{"email": "walid@example.com", "code": "483910"}`.
5. Server verifies row, marks `used=1`, creates `users` row if first-time, issues JWT (30-day expiry, `user_id` claim), writes bcrypt hash of JWT to `users.jwt_hash`, returns `200 {"data": {"token": "eyJ...", "user_id": 1}, "meta": {...}}`.
6. Flutter calls any future protected endpoint with `Authorization: Bearer eyJ...` and gets through.

### Scenario B — Expired Code
1. Walid requests a code at 10:00.
2. At 10:16 he types it in (16 minutes elapsed, row's `expires_at` = 10:15).
3. Server: fetch row, compare `expires_at` to `now()`, return `400 {"error": {"code": "AUTH_CODE_EXPIRED", "message": "This code has expired. Please request a new one."}}`.
4. Row is NOT marked used (so a concurrent request with a fresh code for the same email still works). Expired rows are left for the periodic cleanup (out of scope here — documented as a future cron).

### Scenario C — Wrong Code
1. Walid requests code `483910`.
2. He types `483911`.
3. Server: fetch row where `email=X AND code=483911 AND used=0` → no row → return `400 {"error": {"code": "AUTH_CODE_INVALID", "message": "Invalid code. Please check and try again."}}`.
4. The original code row is still valid — Walid can retry within the window.

### Scenario D — Reused Code
1. Walid verifies `483910` successfully at 10:05 (row now `used=1`).
2. A buggy Flutter retries `POST /auth/verify-code` with the same code at 10:06.
3. Server query `WHERE used=0` returns no row → `AUTH_CODE_INVALID`.
4. The JWT from the first verification is still valid — the client should use it, not retry the verify call.

### Scenario E — Missing / Malformed JWT on a Protected Route
1. Flutter calls a (future) protected endpoint with no `Authorization` header, or `Authorization: Basic xxx`, or `Authorization: Bearer eyJ...` where the signature has been tampered with, or where `exp` is in the past.
2. Middleware returns `401 {"error": {"code": "AUTH_UNAUTHORIZED", "message": "Missing or invalid token."}}` in every case.
3. The route handler never runs, `request.state.user_id` is never set.

### Scenario F — Resend Outage
1. Walid requests a code.
2. Resend API returns 500 / times out.
3. Server still commits the `auth_codes` row (so retries work without DB churn), logs the SMTP failure, and returns `502 {"error": {"code": "EMAIL_DELIVERY_FAILED", "message": "Could not send email. Please try again."}}`.
4. Flutter shows a retry button; Walid tries again in 30 seconds.

Handling these six scenarios correctly is the real acceptance bar. The tests below encode them.

---

## Story

As a **solo developer building the surviveTheTalk MVP**,
I want **a deployed FastAPI server with a passwordless email auth system, a SQLite database, and a JWT middleware**,
So that **every subsequent MVP story (Flutter auth UI, scenario API, call initiation, debrief generation) has a stable, documented backend contract to build against**.

---

## Dependencies

**Blocks:**
- Story 4.3 (Build Email Authentication Flow in Flutter) — cannot start until `/auth/*` endpoints are live.
- Story 5.1 (Scenarios API) — will `include` the JWT middleware from this story.
- Story 6.1 (Call Initiation) — will resolve `user_id` from the JWT to enforce daily call limits.

**Blocked by:**
- Story 1.1 (Initialize Monorepo and Deploy Server Infrastructure) — **done**. Provides: Hetzner VPS, Caddy on ports 80/443, `pipecat.service` running the FastAPI app, `/opt/survive-the-talk/data/` writable, `.env` file with `JWT_SECRET` and `RESEND_API_KEY` already populated (Story 1.1 provisioned placeholders — Walid confirms real values are in `.env` before dev picks this up).
- Story 4.1 (Restructure Flutter Project to MVP Architecture) — **done**. Not a code blocker for the server, but the target client of this API is the restructured Flutter app.

**Key reference documents:**
- `_bmad-output/planning-artifacts/epics.md:731-767` (Story 4.2 source spec)
- `_bmad-output/planning-artifacts/architecture.md:241-287` (data model + auth strategy)
- `_bmad-output/planning-artifacts/architecture.md:519-596` (API response format + Python file layout)
- `_bmad-output/planning-artifacts/architecture.md:881-887` (Boundary 4: FastAPI ↔ SQLite access rules)
- `_bmad-output/planning-artifacts/poc-known-issues-mvp-impact.md` (none applicable to auth — confirmed)

---

## Acceptance Criteria

_(The epic lists 7 ACs; this story expands them into 10 testable criteria with explicit BDD scenarios. AC numbering is internal to this story.)_

### AC1 — FastAPI app boots with composed routers and lifespan DB init

**Given** the refactored server code with `api/app.py` as the FastAPI factory
**When** `python main.py` is run (or `uvicorn api.app:app`)
**Then:**
- The server listens on `0.0.0.0:8000`.
- On startup (via FastAPI `lifespan` context manager), the SQLite database at `settings.database_path` is created if missing, and every migration file in `server/db/migrations/*.sql` is executed in lexical order inside a `schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT)` tracking table (each file runs at most once).
- The composed app includes three routers: `auth_router` (prefix `/auth`), `call_router` (the existing `/connect` endpoint, now a router), and a top-level `health_router` (`GET /health`).
- `GET /health` returns `200 {"data": {"status": "ok", "db": "ok"}, "meta": {...}}` and actually opens + closes a DB connection to prove the DB is reachable.

### AC2 — POST /auth/request-code sends a code via Resend

**Given** a valid JSON body `{"email": "walid@example.com"}`
**When** the client calls `POST /auth/request-code`
**Then:**
- A new row is inserted into `auth_codes` with a cryptographically-random 6-digit decimal code (use `secrets.randbelow(1_000_000)` zero-padded to 6 chars), `email` lowercased and trimmed, `expires_at = now_utc() + 15 minutes` (ISO 8601 string), `used = 0`.
- Any previous unused code for the same email is marked `used = 1` (one active code at a time).
- An HTTP call to Resend's API (`POST https://api.resend.com/emails`) is made with the code in the body, using `settings.resend_api_key` as Bearer token. The call is awaited (not fire-and-forget) so we can surface delivery failure.
- On success: `200 {"data": {"message": "Code sent"}, "meta": {"timestamp": "<iso>"}}`.
- On Resend failure: `502 {"error": {"code": "EMAIL_DELIVERY_FAILED", "message": "Could not send email. Please try again."}}` (the DB row is NOT rolled back — see Scenario F).
- On invalid email format (Pydantic `EmailStr` rejects): `422` with Pydantic's default validation error body — the middleware converts this to our envelope `{"error": {"code": "VALIDATION_ERROR", "message": "<pydantic message>"}}`.

### AC3 — POST /auth/verify-code validates, issues JWT, creates user

**Given** a valid JSON `{"email": "walid@example.com", "code": "483910"}`
**When** the client calls `POST /auth/verify-code`
**Then the server queries** `SELECT * FROM auth_codes WHERE email = ? AND code = ? AND used = 0 ORDER BY expires_at DESC LIMIT 1`.

| Case | Row found? | `expires_at` vs now | Response |
|------|-----------|---------------------|----------|
| A | No | — | `400 AUTH_CODE_INVALID` |
| B | Yes | Past | `400 AUTH_CODE_EXPIRED` (row NOT marked used) |
| C | Yes | Future | Success path (see below) |

**Success path:**
- Mark the row `used = 1`.
- `SELECT id FROM users WHERE email = ?`. If not found, `INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)` and take the new `lastrowid`.
- Create a JWT with payload `{"user_id": <int>, "exp": <unix_ts 30 days from now>}` using `PyJWT.encode(payload, settings.jwt_secret, algorithm="HS256")`.
- `UPDATE users SET jwt_hash = ? WHERE id = ?` where the value is `bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()`. (The hash is written for schema completeness; it is NOT verified on subsequent requests — see Dev Notes §Security Decisions.)
- Return `200 {"data": {"token": "<jwt>", "user_id": <int>, "email": "<email>"}, "meta": {"timestamp": "<iso>"}}`.

### AC4 — JWT middleware on protected routes

**Given** an APIRouter declared with `dependencies=[Depends(require_auth)]`
**When** a request arrives:

| Authorization header | `jwt.decode` result | Middleware behavior |
|----------------------|---------------------|---------------------|
| Missing | — | `401 AUTH_UNAUTHORIZED "Missing or invalid token."` |
| `Basic xxx` | — | `401 AUTH_UNAUTHORIZED` |
| `Bearer <tampered>` | `InvalidSignatureError` | `401 AUTH_UNAUTHORIZED` |
| `Bearer <expired>` | `ExpiredSignatureError` | `401 AUTH_TOKEN_EXPIRED "Your session has expired. Please sign in again."` |
| `Bearer <valid>` but `user_id` not in `users` table | — | `401 AUTH_UNAUTHORIZED` |
| `Bearer <valid>` and user exists | claim extracted | `request.state.user_id = <int>`, handler runs |

The dependency is callable via `Depends(require_auth)` and also exposed as a reusable `AUTH_DEPENDENCY = Depends(require_auth)` so future routers can write `APIRouter(dependencies=[AUTH_DEPENDENCY])`.

**For Story 4.2's code, the auth dependency is wired but NOT applied to any existing route.** `/connect` stays open (Story 6.1 will re-plumb it). `/auth/*` and `/health` are explicitly unprotected. The dependency's correctness is proven by a dedicated test route mounted only in the test fixture (see AC10).

### AC5 — Uniform API response envelope

**Given** any endpoint returns to the client
**Then** the JSON body matches one of two shapes:

```json
// Success
{ "data": { /* endpoint payload */ }, "meta": { "timestamp": "2026-04-16T10:30:00Z" } }

// Error
{ "error": { "code": "SCREAMING_SNAKE", "message": "Human sentence.", "detail": { /* optional */ } } }
```

- All JSON keys use `snake_case`.
- All timestamp values are ISO 8601 UTC strings with a trailing `Z` (e.g. `2026-04-16T10:30:00Z`) — no microseconds, no timezone offsets.
- Error `code` values are SCREAMING_SNAKE_CASE.
- This is enforced by two Pydantic response models in `models/schemas.py` (`SuccessEnvelope`, `ErrorEnvelope`) and a FastAPI exception handler (`@app.exception_handler(RequestValidationError)` converts Pydantic 422s into the envelope, `@app.exception_handler(HTTPException)` does the same for HTTP errors).

### AC6 — SQLite schema matches architecture §Data Model

**Given** the migration `db/migrations/001_init.sql` is applied
**Then** the database contains:

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    jwt_hash TEXT,
    tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','full')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS auth_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_auth_codes_email_code ON auth_codes(email, code);
```

- `IF NOT EXISTS` makes migrations idempotent inside their own file; the `schema_migrations` tracking table ensures each migration file is executed once per database.
- No ORM. All SQL lives in `db/queries.py` exposed as async functions (`get_user_by_email`, `insert_user`, `insert_auth_code`, `invalidate_previous_codes`, `fetch_active_code`, `mark_code_used`, `update_user_jwt_hash`). Route handlers call these functions; they never construct SQL strings themselves. (Architecture Boundary 4.)

### AC7 — Existing /connect endpoint keeps working

**Given** the refactor changes `api/call_endpoint.py` from `app = FastAPI(...)` to `router = APIRouter()`
**Then:**
- `POST /connect` still accepts the existing Pydantic model, still returns the existing response shape (NOT wrapped in `{data, meta}` — Story 6.1 will redesign this endpoint into `/calls/initiate`; wrapping it now would break the still-in-use PoC Flutter client).
- CORS middleware that was on `call_endpoint.app` moves to `api/app.py` so the whole app is covered.
- The existing test `server/tests/test_call_endpoint.py` still passes after being updated to import `api.app:app` instead of `api.call_endpoint:app`.

### AC8 — Environment + deployment

**Given** a working VPS from Story 1.1
**Then:**
- `server/pyproject.toml` declares new dependencies: `PyJWT[crypto]>=2.10.0`, `bcrypt>=4.2.0`, `aiosqlite>=0.21.0`, `email-validator>=2.2.0` (for Pydantic `EmailStr`), `httpx>=0.28.0` (for Resend calls — already a Pipecat transitive but pin explicitly).
- `server/config.py` continues to load `jwt_secret`, `resend_api_key`, `database_path` from `.env`.
- `deploy/Caddyfile` is unchanged (already proxies `/` to `localhost:8000`; new `/auth/*` routes inherit).
- `deploy/pipecat.service` is unchanged (it runs `main.py` which now serves the composed FastAPI app). **No new systemd unit is created** — the architecture doc's reference to a separate `fastapi.service` is obsolete; Story 1.1 decided on a unified service.
- `.env.example` is updated to document `JWT_SECRET` (must be ≥32 chars, generate with `openssl rand -hex 32`) and `RESEND_API_KEY`.

### AC9 — Pre-commit gates pass

**Given** the dev has finished implementation
**When** they run from `server/`:

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

**Then** all three exit 0. CLAUDE.md makes this non-negotiable.

### AC10 — Test coverage

**Given** the code is complete
**Then** `server/tests/test_auth.py` exists and exercises:

- `test_request_code_happy_path` — returns 200, inserts row, Resend was called (`httpx` mocked with `respx` or a FastAPI `dependency_overrides` on the email service).
- `test_request_code_invalidates_previous` — two successive requests leave exactly one `used=0` row for that email.
- `test_request_code_resend_failure` — mocked 500 from Resend → 502 `EMAIL_DELIVERY_FAILED`, DB row still present.
- `test_verify_code_happy_creates_user` — new email → 200, JWT returned, `users` row created, `users.jwt_hash` populated.
- `test_verify_code_returning_user` — existing email → 200, no duplicate user row, new JWT issued.
- `test_verify_code_expired` — `expires_at` in the past → 400 `AUTH_CODE_EXPIRED`, row still `used=0`.
- `test_verify_code_invalid` — wrong code → 400 `AUTH_CODE_INVALID`.
- `test_verify_code_reused` — verify twice → second attempt 400 `AUTH_CODE_INVALID`.
- `test_require_auth_missing_header` / `test_require_auth_bad_scheme` / `test_require_auth_tampered` / `test_require_auth_expired` / `test_require_auth_valid` — each hits a test-only protected route and asserts the right status + envelope.
- `test_health_endpoint` — 200 `{"data": {"status": "ok", "db": "ok"}}`.
- `test_response_envelope_on_validation_error` — `POST /auth/request-code` with `{"email": "not-an-email"}` returns 422 in envelope shape `{"error": {"code": "VALIDATION_ERROR", ...}}`.

Tests use an `asyncio` event loop fixture, an in-memory SQLite DB fixture (`:memory:` with migrations applied), and FastAPI's `httpx.AsyncClient` via `ASGITransport`. No real Resend calls.

---

## Tasks / Subtasks

### Phase 1 — Dependencies and Configuration
- [x] **1.1** Update `server/pyproject.toml`: add under `[project]` → `dependencies`:
  - `"pyjwt[crypto]>=2.10.0,<3.0.0"`
  - `"bcrypt>=4.2.0,<5.0.0"`
  - `"aiosqlite>=0.21.0,<1.0.0"`
  - `"email-validator>=2.2.0,<3.0.0"`
  - `"httpx>=0.28.0,<1.0.0"` (explicit pin — already transitive)
- [x] **1.2** Run `cd server && uv sync` (or `pip install -e .`) and commit the updated lockfile if present.
- [x] **1.3** `server/config.py` — add two new fields:
  - `resend_from_email: str = "noreply@survivethetalk.com"` — the sender address used for auth code emails. The `survivethetalk.com` domain is already DNS-verified in Resend (DKIM + SPF + DMARC), so sending from this address works out of the box. No actual mailbox exists for `noreply@` — replies to auth emails will bounce (expected behavior).
  - `resend_from_name: str = "surviveTheTalk"` — display name shown in the inbox ("From: surviveTheTalk <noreply@survivethetalk.com>").
  Also verify `jwt_secret` and `resend_api_key` are loaded; add a `@field_validator` that raises if `jwt_secret` is shorter than 32 chars when `ENVIRONMENT=production` (skip check in tests).
- [x] **1.4** Update `.env.example` at repo root (or create if missing): document all required keys including `RESEND_FROM_EMAIL` and `RESEND_FROM_NAME`, with `openssl rand -hex 32` hint for `JWT_SECRET`. Note in comment: "`survivethetalk.com` is DNS-verified in Resend; any `*@survivethetalk.com` address works as sender. `noreply@` is a label, not a real mailbox."

### Phase 2 — Database Layer
- [x] **2.1** Create `server/db/__init__.py` (empty).
- [x] **2.2** Create `server/db/migrations/001_init.sql` with the two-table schema from AC6, including `schema_migrations` bootstrap. Exact content:
  ```sql
  CREATE TABLE IF NOT EXISTS schema_migrations (
      version TEXT PRIMARY KEY,
      applied_at TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL UNIQUE,
      jwt_hash TEXT,
      tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','full')),
      created_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
  CREATE TABLE IF NOT EXISTS auth_codes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      email TEXT NOT NULL,
      code TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      used INTEGER NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_auth_codes_email_code ON auth_codes(email, code);
  ```
- [x] **2.3** Create `server/db/database.py` with:
  - `async def get_connection() -> aiosqlite.Connection` — opens `settings.database_path`, sets `row_factory = aiosqlite.Row`, `PRAGMA foreign_keys = ON`. Used as an async context manager at the route level (`async with get_connection() as db:`).
  - `async def run_migrations() -> None` — ensures parent dir exists (`Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)`), opens a connection, creates `schema_migrations` if missing, iterates sorted `server/db/migrations/*.sql`, checks each version, executes via `executescript`, inserts `schema_migrations` row, commits.
- [x] **2.4** Create `server/db/queries.py` with async functions (one SQL statement each). Signatures:
  ```python
  async def get_user_by_email(db, email: str) -> aiosqlite.Row | None
  async def get_user_by_id(db, user_id: int) -> aiosqlite.Row | None
  async def insert_user(db, email: str, created_at: str) -> int  # returns lastrowid
  async def update_user_jwt_hash(db, user_id: int, jwt_hash: str) -> None
  async def insert_auth_code(db, email: str, code: str, expires_at: str) -> None
  async def invalidate_previous_codes(db, email: str) -> None  # UPDATE ... SET used=1 WHERE email=? AND used=0
  async def fetch_active_code(db, email: str, code: str) -> aiosqlite.Row | None  # used=0 match
  async def mark_code_used(db, code_id: int) -> None
  ```
  All functions call `await db.commit()` where they mutate. No business logic — pure CRUD.

### Phase 3 — Models and Utilities
- [x] **3.1** Create `server/models/__init__.py` (empty).
- [x] **3.2** Create `server/models/schemas.py` with Pydantic v2 models:
  ```python
  from pydantic import BaseModel, EmailStr, Field
  class RequestCodeIn(BaseModel):
      email: EmailStr
  class VerifyCodeIn(BaseModel):
      email: EmailStr
      code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
  class RequestCodeOut(BaseModel):
      message: str
  class VerifyCodeOut(BaseModel):
      token: str
      user_id: int
      email: EmailStr
  class HealthOut(BaseModel):
      status: str
      db: str
  class Meta(BaseModel):
      timestamp: str
  class ErrorBody(BaseModel):
      code: str
      message: str
      detail: dict | None = None
  ```
- [x] **3.3** Create `server/api/responses.py` with envelope helpers:
  ```python
  def ok(data: BaseModel | dict) -> dict
  def err(code: str, message: str, detail: dict | None = None) -> dict
  def now_iso() -> str  # returns UTC ISO8601 with trailing Z, no microseconds
  ```
- [x] **3.4** Create `server/auth/__init__.py` (empty).
- [x] **3.5** Create `server/auth/jwt_service.py`:
  ```python
  JWT_ALGORITHM = "HS256"
  JWT_LIFETIME_DAYS = 30
  def issue_token(user_id: int) -> str
  def decode_token(token: str) -> dict  # raises jwt.ExpiredSignatureError or jwt.InvalidTokenError
  def hash_token(token: str) -> str  # bcrypt.hashpw(...).decode()
  ```
- [x] **3.6** Create `server/auth/email_service.py`:
  ```python
  EMAIL_SUBJECT = "Your surviveTheTalk code"
  EMAIL_BODY_TEMPLATE = "Your 6-digit code: {code}\nIt expires in 15 minutes."
  async def send_auth_code(email: str, code: str) -> None:
      # from_addr = f"{settings.resend_from_name} <{settings.resend_from_email}>"
      # POST https://api.resend.com/emails via httpx.AsyncClient,
      # Authorization: Bearer settings.resend_api_key,
      # JSON: {"from": from_addr, "to": [email], "subject": EMAIL_SUBJECT, "text": EMAIL_BODY_TEMPLATE.format(code=code)}
      # Raises EmailDeliveryError on non-2xx.
  class EmailDeliveryError(Exception): ...
  ```
  The sender address and display name are read from `settings.resend_from_email` / `settings.resend_from_name` — never hardcoded. This lets Walid flip from sandbox to verified domain by editing `.env` only.

### Phase 4 — Middleware and Dependencies
- [x] **4.1** Create `server/api/middleware.py`:
  ```python
  from fastapi import Request, HTTPException, Depends
  from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
  import jwt
  from auth.jwt_service import decode_token
  from db.database import get_connection
  from db.queries import get_user_by_id

  bearer_scheme = HTTPBearer(auto_error=False)

  async def require_auth(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> int:
      if credentials is None or credentials.scheme.lower() != "bearer":
          raise HTTPException(401, detail={"code": "AUTH_UNAUTHORIZED", "message": "Missing or invalid token."})
      try:
          payload = decode_token(credentials.credentials)
      except jwt.ExpiredSignatureError:
          raise HTTPException(401, detail={"code": "AUTH_TOKEN_EXPIRED", "message": "Your session has expired. Please sign in again."})
      except jwt.InvalidTokenError:
          raise HTTPException(401, detail={"code": "AUTH_UNAUTHORIZED", "message": "Missing or invalid token."})
      user_id = payload.get("user_id")
      async with get_connection() as db:
          user = await get_user_by_id(db, user_id)
      if user is None:
          raise HTTPException(401, detail={"code": "AUTH_UNAUTHORIZED", "message": "Missing or invalid token."})
      request.state.user_id = user_id
      return user_id

  AUTH_DEPENDENCY = Depends(require_auth)
  ```

### Phase 5 — Routes
- [x] **5.1** Refactor `server/api/call_endpoint.py`:
  - Remove `app = FastAPI(...)`, remove the CORSMiddleware line.
  - Replace with `router = APIRouter(tags=["call"])`.
  - Replace `@app.post("/connect")` with `@router.post("/connect")`.
  - Do NOT change the request/response shape.
- [x] **5.2** Create `server/api/routes_auth.py`:
  ```python
  router = APIRouter(prefix="/auth", tags=["auth"])

  @router.post("/request-code")
  async def request_code(payload: RequestCodeIn) -> dict:
      email = payload.email.lower().strip()
      code = f"{secrets.randbelow(1_000_000):06d}"
      expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat(timespec="seconds").replace("+00:00", "Z")
      async with get_connection() as db:
          await invalidate_previous_codes(db, email)
          await insert_auth_code(db, email, code, expires_at)
      try:
          await send_auth_code(email, code)
      except EmailDeliveryError:
          logger.exception("Resend delivery failed for {}", email)
          return JSONResponse(status_code=502, content=err("EMAIL_DELIVERY_FAILED", "Could not send email. Please try again."))
      return ok(RequestCodeOut(message="Code sent"))

  @router.post("/verify-code")
  async def verify_code(payload: VerifyCodeIn) -> dict:
      email = payload.email.lower().strip()
      async with get_connection() as db:
          row = await fetch_active_code(db, email, payload.code)
          if row is None:
              return JSONResponse(status_code=400, content=err("AUTH_CODE_INVALID", "Invalid code. Please check and try again."))
          if row["expires_at"] < now_iso():
              return JSONResponse(status_code=400, content=err("AUTH_CODE_EXPIRED", "This code has expired. Please request a new one."))
          await mark_code_used(db, row["id"])
          user = await get_user_by_email(db, email)
          if user is None:
              user_id = await insert_user(db, email, now_iso())
          else:
              user_id = user["id"]
          token = issue_token(user_id)
          await update_user_jwt_hash(db, user_id, hash_token(token))
      return ok(VerifyCodeOut(token=token, user_id=user_id, email=email))
  ```
- [x] **5.3** Create `server/api/routes_health.py`:
  ```python
  router = APIRouter(tags=["health"])
  @router.get("/health")
  async def health() -> dict:
      try:
          async with get_connection() as db:
              await db.execute("SELECT 1")
      except Exception:
          return JSONResponse(status_code=503, content=err("DB_UNAVAILABLE", "Database connection failed."))
      return ok(HealthOut(status="ok", db="ok"))
  ```

### Phase 6 — App Composition
- [x] **6.1** Create `server/api/app.py`:
  ```python
  from contextlib import asynccontextmanager
  from fastapi import FastAPI, HTTPException
  from fastapi.exceptions import RequestValidationError
  from fastapi.middleware.cors import CORSMiddleware
  from fastapi.responses import JSONResponse
  from api.routes_auth import router as auth_router
  from api.routes_health import router as health_router
  from api.call_endpoint import router as call_router
  from api.responses import err
  from db.database import run_migrations

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      await run_migrations()
      yield

  app = FastAPI(title="surviveTheTalk API", lifespan=lifespan)
  app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                     allow_methods=["*"], allow_headers=["*"])
  app.include_router(health_router)
  app.include_router(auth_router)
  app.include_router(call_router)

  @app.exception_handler(HTTPException)
  async def http_exc_handler(request, exc: HTTPException):
      if isinstance(exc.detail, dict) and "code" in exc.detail:
          return JSONResponse(status_code=exc.status_code, content=err(**exc.detail))
      return JSONResponse(status_code=exc.status_code, content=err("HTTP_ERROR", str(exc.detail)))

  @app.exception_handler(RequestValidationError)
  async def validation_handler(request, exc: RequestValidationError):
      return JSONResponse(status_code=422, content=err("VALIDATION_ERROR", "Request body is invalid.", detail={"errors": exc.errors()}))
  ```
- [x] **6.2** Update `server/main.py` — change `uvicorn.run("api.call_endpoint:app", ...)` to `uvicorn.run("api.app:app", host="0.0.0.0", port=8000)`.

### Phase 7 — Tests
- [x] **7.1** Create `server/tests/conftest.py` (if not already present) with:
  - Set required env vars at module load (so `Settings()` always succeeds).
  - Fixture `test_db_path` — `tmp_path / "test.sqlite"`; monkeypatch `db.database.settings.database_path` to it.
  - Fixture `client` — uses sync FastAPI `TestClient` as a context manager so the lifespan (and `run_migrations`) runs against the patched DB path.
  - Fixture `mock_resend` — monkeypatches `api.routes_auth.send_auth_code` to a recording `AsyncMock`; tests flip `side_effect=EmailDeliveryError` for the failure path.
  - Fixture `protected_client` — builds a throwaway FastAPI app with a single `/_test_protected` route using `AUTH_DEPENDENCY` and the production exception handlers (used by `test_middleware.py`).
  - Note: NO `from __future__ import annotations` in conftest — FastAPI needs the runtime type of `Request` on the test-only protected route.
- [x] **7.2** Create `server/tests/test_auth.py` with the test list from AC10. Each test is ~10–20 lines.
- [x] **7.3** Create `server/tests/test_health.py` with `test_health_endpoint`.
- [x] **7.4** Create `server/tests/test_envelope.py` with `test_response_envelope_on_validation_error` and a sanity check that a successful response is wrapped in `{data, meta}`.
- [x] **7.5** Create `server/tests/test_middleware.py` — mounts an in-fixture `APIRouter` with a `/_test_protected` route using `AUTH_DEPENDENCY`, exercises all five middleware branches from AC4.
- [x] **7.6** Update `server/tests/test_call_endpoint.py` — replace `from api.call_endpoint import app` with `from api.app import app`; delete any `importlib.reload` logic if it breaks. Ensure `/connect` test still passes unchanged.

### Phase 8 — Verification and Commit
- [x] **8.1** Run from `server/`:
  ```
  python -m ruff check .
  python -m ruff format --check .
  python -m pytest -q
  ```
  All three must be green. Fix issues until they are.
- [x] **8.2** Manually smoke-test the migration runner once: delete a temp DB, start the server, verify the tables exist (sqlite CLI: `.schema users`).
- [x] **8.3** Update `_bmad-output/implementation-artifacts/sprint-status.yaml`: set `4-2-build-fastapi-server-with-passwordless-auth-system: review`. Bump `last_updated`.
- [x] **8.4** Update this story file's status from `ready-for-dev` → `review`.
- [x] **8.5** Commit with format:
  ```
  feat: implement FastAPI auth system and server skeleton (Story 4.2)

  - Add FastAPI app composition with lifespan DB migrations
  - Add passwordless auth endpoints (/auth/request-code, /auth/verify-code)
  - Add JWT middleware with stateless token validation
  - Add SQLite schema (users, auth_codes) and raw-SQL query layer
  - Add Resend email delivery service with failure-tolerant flow
  - Add health endpoint and uniform {data, meta} / {error} envelope
  - Refactor /connect endpoint from FastAPI app to APIRouter
  - Add N new tests (total passing)
  ```
  No Co-Authored-By line (per CLAUDE.md).

---

## Dev Notes

### Library Versions (locked — do NOT upgrade during this story)

| Package | Version | Why | Source |
|---------|---------|-----|--------|
| fastapi | 0.135.2 | Already pinned in `pyproject.toml` for Pipecat compat | `server/pyproject.toml` |
| uvicorn | 0.40.0+ | Already pinned, boots FastAPI | `server/pyproject.toml` |
| pydantic | v2 (≥2.9) | Pinned by FastAPI 0.135 | transitive |
| pydantic-settings | 2.13.1 | Already pinned | `server/pyproject.toml` |
| PyJWT | ≥2.10.0, <3 | HS256 + crypto extras for future RS256 migration; [crypto] pulls in cryptography | architecture.md §Auth |
| bcrypt | ≥4.2.0, <5 | For `users.jwt_hash` storage | architecture.md §Auth |
| aiosqlite | ≥0.21.0, <1 | Async wrapper over stdlib sqlite3; no ORM | architecture.md §Boundaries |
| email-validator | ≥2.2.0 | Backs Pydantic `EmailStr` | required by Pydantic |
| httpx | ≥0.28.0, <1 | Resend HTTP calls; already a transitive via FastAPI | test + prod |
| loguru | already pinned | Structured logging | existing |

**Do NOT add:** SQLAlchemy, Alembic, Peewee, Databases, redis, celery, fastapi-users, python-jose. This MVP keeps the dependency surface minimal.

### Architecture Compliance

- **Boundary 4 (architecture.md:881-887):** No raw SQL in route handlers. All DB access goes through `db/queries.py` async functions. Verifiable by grep: `grep -rE "SELECT|INSERT|UPDATE|DELETE" server/api/` must only match `db/queries.py` (enforced by reviewer, not CI, at this stage).
- **Response format (architecture.md:519-556):** The `{data, meta}` / `{error}` envelope is mandatory on all NEW endpoints. The `/connect` endpoint keeps its legacy shape because (a) changing it now breaks the PoC Flutter client still in use and (b) Story 6.1 will redesign it into `/calls/initiate`.
- **snake_case JSON keys:** Enforced by Pydantic v2 default (`ConfigDict(populate_by_name=True)` is NOT needed; Python attr names are already snake_case).
- **Data model (architecture.md:241-256):** The `users` and `auth_codes` schemas in `001_init.sql` match exactly. `users.tier` uses a CHECK constraint rather than a separate enum table — simpler for 2 values.
- **systemd (architecture.md:397-399):** Architecture mentioned separate `fastapi.service`; the real infra from Story 1.1 has a unified `pipecat.service` that runs `main.py` which IS the FastAPI app. Do not create a new service file. This is a known doc/reality drift — flag it in the commit message if noticed.

### What NOT to Do

- **Do NOT add rate limiting in this story.** The epic acceptance criteria do not require it, and adding it now requires either `slowapi` (adds redis for durability) or a Caddy-level rate-limit module. Defer to Story 10.x (launch hardening). The only comment in the code should be `# TODO(story-10): add rate limiting on /auth/request-code (max 5/hour per email)`.
- **Do NOT hash auth codes with bcrypt.** The schema stores them plain; security relies on 15-min expiry + one-at-a-time invalidation. Hashing them adds ~200ms × 2 (write + read) per verification for zero benefit.
- **Do NOT use a JWT revocation list / "blacklist" table.** Stateless HS256 validation (signature + exp) is sufficient for MVP. `users.jwt_hash` is written but NOT read during request validation — it exists for a future "revoke all sessions" feature.
- **Do NOT validate Resend delivery before responding.** If you add a "ping Resend first" check you double the latency. The retry-on-failure pattern in Scenario F is intentional.
- **Do NOT apply `require_auth` to any existing endpoint.** `/connect` stays open; `/auth/*` and `/health` are explicitly unprotected. Story 6.1 will be the first consumer of the middleware.
- **Do NOT introduce `async-lru` or caching for `get_user_by_id`.** SQLite in-process is already ~100µs; caching invites invalidation bugs.
- **Do NOT use `datetime.utcnow()`.** It's deprecated in Python 3.12. Use `datetime.now(UTC)` with a trailing-Z ISO string.
- **Do NOT hardcode the Resend `from:` address or display name anywhere.** They live in `settings.resend_from_email` / `settings.resend_from_name` (loaded from `.env`). The defaults in `config.py` are `noreply@survivethetalk.com` / `surviveTheTalk` — the domain is already DNS-verified in Resend (DKIM/SPF/DMARC live), so this works immediately. Override via `.env` if needed (e.g. `support@survivethetalk.com` for a future transactional channel).
- **Do NOT write the JWT secret to any log line.** `logger.info("JWT issued for user {}", user_id)` is fine; `logger.info("Token: {}", token)` is a production landmine.
- **Do NOT skip `SELECT ... ORDER BY expires_at DESC LIMIT 1` in `fetch_active_code`.** If a user somehow has two active codes (race between two `/auth/request-code` calls before invalidation commits), the most recent one wins.

### Previous Story Intelligence

- **From Story 1.1 (done):** The VPS firewall only opens 22, 80, 443. Caddy proxies `localhost:8000`. The service runs as user `survivethetalk` with working dir `/opt/survive-the-talk/server/`. The `.env` file is at `/opt/survive-the-talk/server/.env` and is readable only by that user. The DB path `/opt/survive-the-talk/data/db.sqlite` is already writable. Deploy by editing files via SSH and running `sudo systemctl restart pipecat.service`.
- **From Story 4.1 (done):** The Flutter app has been restructured into the MVP folder layout and is ready to consume these endpoints. No API calls are made yet (Story 4.3 will add them).
- **From Story 4.1b (review):** Design system established. Not relevant to server work.
- **From Epic 3 retrospective action items:** Every story must contain an adversarial walk-through (done above in §Concrete User Walk-Through). Every story must reference `poc-known-issues-mvp-impact.md` (done below — zero applicable).

### PoC Known Issues → Story Impact

Per `_bmad-output/planning-artifacts/poc-known-issues-mvp-impact.md`, the 8 known PoC issues are:

| # | Issue | Applies to Story 4.2? | Notes |
|---|-------|----------------------|-------|
| 1 | Silence handling | **No** | Call-time behavior, Story 6.4 owns it |
| 2 | Cold start (~3-4s) | **No** | Call initiation, Story 6.1 owns it |
| 3 | VAD stop_secs mismatch | **No** | Pipecat bot config, Story 6.1 |
| 4 | Response length overrun | **No** | LLM prompt, Story 6.2 |
| 5 | Barge-in sensitivity | **No** | Pipecat config, Story 6.4 |
| 6 | TTS cost | **No** | Business / Epic 10 |
| 7 | Break-even estimate | **No** | PRD correction |
| 8 | Double user messages | **No** | Pipecat aggregator, Story 6.2 |

**Net: this story is unaffected by any PoC known issue.** Server/auth concerns were out of PoC scope.

### Architectural Hooks Primed for Future Stories

This story deliberately leaves behind several small hooks so later stories don't pay a refactor tax:

- **For Story 4.3 (Flutter auth flow):** The `VerifyCodeOut.user_id` field is returned alongside `token` so the Flutter layer can stash it without re-decoding the JWT. `email` is echoed back so Flutter's AuthBloc can confirm it matches what the user typed (belt-and-suspenders).
- **For Story 5.1 (Scenarios API):** `AUTH_DEPENDENCY` is a module-level export, so `routes_scenarios.py` can just write `APIRouter(prefix="/scenarios", dependencies=[AUTH_DEPENDENCY])` without boilerplate. `request.state.user_id` is the single source of truth inside handlers.
- **For Story 6.1 (Call Initiation):** The `/connect` endpoint is now a router, not an app — Story 6.1 can replace it cleanly without touching `main.py` or the CORS setup. The auth dependency can be applied at that time.
- **For Story 7.1 (Debrief Generation):** The envelope helpers in `api/responses.py` and the error-code convention are in place; Story 7.1 just adds its own route module.
- **For Story 10.x (launch hardening):** A `TODO(story-10)` comment marks the rate-limit injection point. Operations readiness can also use `GET /health` as a Caddy upstream health check.
- **For "log out all devices" (post-MVP):** `users.jwt_hash` is populated on every verify; a future feature can add a middleware check that compares `bcrypt.checkpw(token, user.jwt_hash)` before accepting the token. Zero migration needed.

### Security Decisions (explicit, for the reviewer)

1. **Auth codes are stored plain text.** Rationale: 15-min TTL, single-use, one-at-a-time per email, DB access = already game over.
2. **JWT is validated stateless (signature + exp only).** Rationale: MVP has no "revoke" feature; `users.jwt_hash` column is forward-compatible (populated but not queried).
3. **No rate limiting.** Rationale: out of AC scope; deferred with `TODO(story-10)` comment.
4. **JWT secret must be ≥32 chars in production.** Enforced by `config.py` validator.
5. **CORS is open (`allow_origins=["*"]`).** Rationale: the Flutter mobile client has no browser origin header; web-admin is not in MVP scope. Story 10.x will restrict this if a web surface appears.
6. **Password-manager-style auth tokens are returned as JWT strings** — the Flutter `flutter_secure_storage` (iOS Keychain / Android Keystore) stores them encrypted per architecture.md §Auth.
7. **Email input is lowercased + trimmed before DB operations.** Prevents duplicate users differing only by case.

### Pre-dev Confirmations (all resolved with Walid before story creation)

1. **Resend sender — resolved.** `survivethetalk.com` is already DNS-verified in Resend (DKIM/SPF/DMARC live), so `noreply@survivethetalk.com` works immediately as the sender address (`RESEND_FROM_EMAIL` default in `config.py`). No mailbox exists for this address — it's a label-only sender; user replies bounce silently (expected `noreply@` semantics). When an actual receiving address is needed later (Epic 10 for App Store / support contact), Cloudflare Email Routing will forward `*@survivethetalk.com` to Walid's personal inbox.
2. **`.env` values — confirmed by Walid.** The VPS `.env` at `/opt/survive-the-talk/server/.env` has real production values (not Story 1.1 placeholders) for `JWT_SECRET` (≥32 chars) and `RESEND_API_KEY`. `RESEND_FROM_EMAIL` / `RESEND_FROM_NAME` can be omitted from `.env` — the `config.py` defaults (`noreply@survivethetalk.com` / `surviveTheTalk`) are correct.
3. **Deployment scope — confirmed by Walid: code-only in this story.** Implementation, unit tests, and local smoke in this story. Actual VPS deployment + live end-to-end email test happens as the final task of Story 4.3 (Flutter auth flow), when the full loop can be validated in one pass.
3. **Deployment timing.** Should this story also deploy to the VPS, or only land the code? Recommended: land + unit tests + local smoke; VPS deployment happens as the last task inside Story 4.3 when Flutter is ready to hit real endpoints. If Walid disagrees, add a "deploy to VPS" task before commit.

---

## Project Structure Notes

### New files created

```
server/
├── api/
│   ├── app.py                     # NEW — composed FastAPI instance
│   ├── middleware.py              # NEW — require_auth dependency
│   ├── responses.py               # NEW — ok/err/now_iso helpers
│   ├── routes_auth.py             # NEW — /auth/request-code, /auth/verify-code
│   ├── routes_health.py           # NEW — /health
│   └── call_endpoint.py           # REFACTORED — FastAPI app → APIRouter
├── auth/
│   ├── __init__.py                # NEW
│   ├── jwt_service.py             # NEW — issue/decode/hash token
│   └── email_service.py           # NEW — Resend client
├── db/
│   ├── __init__.py                # NEW
│   ├── database.py                # NEW — get_connection, run_migrations
│   ├── queries.py                 # NEW — raw SQL query functions
│   └── migrations/
│       └── 001_init.sql           # NEW — users + auth_codes schema
├── models/
│   ├── __init__.py                # NEW
│   └── schemas.py                 # NEW — Pydantic request/response models
├── tests/
│   ├── conftest.py                # NEW (or extended)
│   ├── test_auth.py               # NEW
│   ├── test_health.py             # NEW
│   ├── test_envelope.py           # NEW
│   ├── test_middleware.py         # NEW
│   └── test_call_endpoint.py      # UPDATED — import from api.app
├── main.py                        # UPDATED — uvicorn.run("api.app:app")
├── config.py                      # UPDATED — add jwt_secret length validator
└── pyproject.toml                 # UPDATED — add 5 dependencies

.env.example                       # UPDATED — document JWT_SECRET, RESEND_API_KEY
```

### Files NOT touched

- `deploy/Caddyfile` — no change (generic `localhost:8000` proxy already covers new routes).
- `deploy/pipecat.service` — no change (already runs `main.py`).
- `deploy/caddy.service`, `deploy/backup.sh` — no change.
- Any Flutter code — Story 4.3 will consume these endpoints.

### Files to verify but likely no change

- `server/tests/test_config.py` — existing test for `Settings`. The new `jwt_secret` validator should not break it if the test doesn't set `ENVIRONMENT=production`. If it does, adjust the test.
- `server/tests/test_no_audio_buffer.py`, `server/tests/test_livekit_*.py` — Pipecat tests, should remain green.

### Import-path sanity

- `api/app.py` imports `from api.routes_auth import router as auth_router` — works because `server/` is the `pyproject.toml` root and `api/` is a top-level package. Verify by running `python -c "from api.app import app; print(app.routes)"` from `server/`.
- Inside `routes_auth.py`, prefer absolute imports (`from db.queries import ...`) over relative (`from ..db.queries`) — keeps parity with existing `call_endpoint.py` style.

---

## References

### Source specifications
- `_bmad-output/planning-artifacts/epics.md:731-767` — Story 4.2 epic definition
- `_bmad-output/planning-artifacts/prd.md` — PRD §FR-auth (passwordless email)
- `_bmad-output/planning-artifacts/architecture.md:241-256` — Data Model: users, auth_codes
- `_bmad-output/planning-artifacts/architecture.md:259-264` — Authentication & Security strategy
- `_bmad-output/planning-artifacts/architecture.md:285-287` — Rate limiting (deferred here)
- `_bmad-output/planning-artifacts/architecture.md:315-318` — Error envelope format
- `_bmad-output/planning-artifacts/architecture.md:397-399` — systemd services (doc/reality drift noted)
- `_bmad-output/planning-artifacts/architecture.md:519-556` — API Response Format
- `_bmad-output/planning-artifacts/architecture.md:559-596` — Python server file structure
- `_bmad-output/planning-artifacts/architecture.md:881-887` — Boundary 4: FastAPI ↔ SQLite
- `_bmad-output/planning-artifacts/poc-known-issues-mvp-impact.md` — 0 of 8 issues apply

### Previous story inputs
- `_bmad-output/implementation-artifacts/1-1-initialize-monorepo-and-deploy-server-infrastructure.md` — VPS infra, systemd unification
- `_bmad-output/implementation-artifacts/4-1-restructure-flutter-project-to-mvp-architecture.md` — client-side readiness
- `_bmad-output/implementation-artifacts/4-1b-implement-design-system.md` — story format reference
- `_bmad-output/implementation-artifacts/epic-3-retro-2026-04-16.md` — adversarial walk-through requirement

### Existing code
- `server/config.py` — Settings (add `jwt_secret` validator)
- `server/main.py` — update uvicorn entry point
- `server/api/call_endpoint.py` — refactor FastAPI app → APIRouter
- `server/pyproject.toml` — add 5 dependencies
- `server/tests/test_call_endpoint.py` — update import path
- `deploy/Caddyfile`, `deploy/pipecat.service` — unchanged, referenced for sanity

### External library docs
- FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/
- PyJWT: https://pyjwt.readthedocs.io/
- aiosqlite: https://aiosqlite.omnilib.dev/
- Resend API: https://resend.com/docs/api-reference/emails/send-email
- Pydantic v2 EmailStr: https://docs.pydantic.dev/latest/api/networks/#pydantic.networks.EmailStr

---

## Dev Agent Record

### Context Reference

No files loaded beyond those listed in §References. Verified the existing
`server/` layout (`api/`, `pipeline/`, `tests/`) to confirm where the new
`auth/`, `db/`, `models/` packages slot in.

### Agent Model Used

Claude Opus 4.6 (`claude-opus-4-6`) via Claude Code CLI.

### Debug Log References

- **`from __future__ import annotations` breaks FastAPI special params** — the
  test-only protected route in `tests/conftest.py::protected_client` uses
  `request: Request` so the handler can read `request.state.user_id`. With
  PEP 563 annotations enabled at the top of conftest.py, FastAPI's signature
  resolver could not see `Request` as the special request object and instead
  treated it as a missing query parameter (422 `VALIDATION_ERROR`). Removed
  the future import from `tests/conftest.py` only — production modules still
  use it without issue because they don't expose FastAPI-special params.
- **Same-second JWTs are bit-identical, not a bug.** The first revision of
  `test_verify_code_returning_user` asserted `first.token != second.token`,
  which is false when both `verify-code` calls land in the same epoch second
  (HS256 over the same payload always produces the same string). Replaced the
  assertion with a check on the bcrypt `users.jwt_hash` column, which uses a
  random salt and is therefore actually unique per call.
- **No Resend rejection encountered** because `auth.email_service.send_auth_code`
  is mocked in every auth test via `monkeypatch.setattr("api.routes_auth.send_auth_code", AsyncMock())`.
  Live Resend will be exercised in Story 4.3 when the Flutter loop hits the VPS.

### Completion Notes

Shipped exactly what the spec defined, with three minor improvements over the
literal spec:

1. **`environment` field declared FIRST in `Settings`** so the
   `_validate_jwt_secret` validator can read it from `info.data` (Pydantic
   v2 evaluates field validators in declaration order).
2. **Tests use sync `TestClient` instead of `httpx.AsyncClient`** — the test
   client transparently handles async endpoints AND triggers the FastAPI
   `lifespan` (so `run_migrations()` runs naturally) when used as a context
   manager. Avoids pulling `pytest-asyncio` / `pytest-anyio` plugin setup.
3. **`require_auth` rejects non-int `user_id` claims** as `AUTH_UNAUTHORIZED`
   (not in spec but a reasonable defensive check in the middleware — guards
   against a tampered token whose signature happens to validate).

Total test count: **82 passing** (initial 75 + 7 added during review
corrections: rate-limited-resend, unseen-email verify, concurrent-claim
atomicity, empty Bearer, bool/string `user_id`, missing `exp`). The full
`ruff check`, `ruff format --check`, and `pytest -q` triplet exits 0.

VPS deployment is intentionally NOT in this story (per Pre-dev Confirmation
#3): the loop is land + unit tests + local smoke. The `/auth/*` endpoints
will hit the VPS for the first time at the end of Story 4.3 when the Flutter
client is wired up — that's where a single end-to-end test validates Resend
delivery, JWT round-trip, and Caddy proxying together.

### File List

**New:**
- `server/api/app.py`
- `server/api/middleware.py`
- `server/api/responses.py`
- `server/api/routes_auth.py`
- `server/api/routes_health.py`
- `server/auth/__init__.py`
- `server/auth/email_service.py`
- `server/auth/jwt_service.py`
- `server/db/__init__.py`
- `server/db/database.py`
- `server/db/queries.py`
- `server/db/migrations/001_init.sql`
- `server/models/__init__.py`
- `server/models/schemas.py`
- `server/tests/conftest.py`
- `server/tests/test_auth.py`
- `server/tests/test_envelope.py`
- `server/tests/test_health.py`
- `server/tests/test_middleware.py`

**Modified:**
- `server/api/call_endpoint.py` (refactored from FastAPI app to APIRouter)
- `server/main.py` (uvicorn entry now `api.app:app`)
- `server/config.py` (added `environment`, `resend_from_email`, `resend_from_name`, JWT-secret length validator)
- `server/pyproject.toml` (added 5 dependencies)
- `server/tests/test_call_endpoint.py` (now imports `api.app:app`, removed `importlib.reload`)
- `deploy/.env.example` (documented `RESEND_FROM_EMAIL`, `RESEND_FROM_NAME`, `ENVIRONMENT`, `openssl rand -hex 32` hint)

### Change Log

- **2026-04-16** — initial implementation. All 8 phases complete; 75 tests pass; ruff clean.
- **2026-04-16 (review corrections)** — adversarial code-review
  (`/bmad-code-review`) produced 25 patch-class findings. See §Review
  Corrections Applied below.

### Review Corrections Applied (2026-04-16)

Adversarial review ran Blind Hunter + Edge Case Hunter + Acceptance Auditor
in parallel. Triage: 25 patch-now, 6 deferred, 9 rejected. All 25 patches
landed in the same Story 4.2 commit.

**Critical / concurrency & security**

- **TOCTOU window in `verify-code` closed.** Replaced the
  `fetch_active_code` → `mark_code_used` pair with a single atomic
  CAS-style claim (`db/queries.py::claim_active_code`): the `UPDATE
  ... WHERE used = 0 AND expires_at >= ?` statement flips exactly one
  row's `used` bit and `cursor.rowcount` tells us whether we won the race.
- **Boolean `user_id` claim rejected.** `require_auth` now excludes
  `isinstance(user_id, bool)` because `bool` is a subclass of `int` in
  Python — a forged `user_id: true` would otherwise resolve to user #1.
- **`JWT_SECRET` never silently empty.** Added a field validator that
  rejects empty strings in every environment and requires ≥32 chars in
  production (matches `openssl rand -hex 32`).
- **Multi-worker migration race prevented.** `run_migrations` now wraps
  each pending migration in `BEGIN IMMEDIATE` so concurrent uvicorn
  workers serialise on the write-lock rather than racing to
  `executescript`.
- **`request-code` race handled.** If `invalidate_previous_codes` +
  `insert_auth_code` and the UNIQUE email constraint collide with a
  concurrent first-time verify, `routes_auth.verify_code` catches
  `aiosqlite.IntegrityError` and re-reads the user row instead of
  surfacing a 500.
- **CRLF sender-field injection blocked.** `config._forbid_crlf_in_sender_fields`
  rejects `\r` / `\n` in `resend_from_name` / `resend_from_email` so a
  misconfigured env var cannot inject arbitrary email headers.
- **bcrypt no longer blocks the event loop.** `hash_token` is now
  `async` and delegates to `asyncio.to_thread`; a SHA-256 pre-hash
  keeps the bcrypt input under the 72-byte truncation boundary.
- **JWT decode requires the `exp` claim.** `decode_token` uses
  `options={"require": ["exp"]}` so a forged token without an expiry
  is rejected rather than silently accepted.

**Medium severity**

- **Composite index `idx_auth_codes_email_code_used`** matches the
  `WHERE email = ? AND code = ? AND used = 0` predicate used by the CAS
  claim, preventing a full table scan as `auth_codes` grows.
- **`CHECK(used IN (0, 1))` + `COLLATE NOCASE`** on email columns so the
  UNIQUE constraint rejects mixed-case duplicates and `used` stays a
  clean boolean.
- **`http_exception_handler` preserves `exc.headers`** and emits a
  deliberately opaque `HTTP_ERROR` message for non-code exceptions
  instead of leaking FastAPI internals via `str(exc.detail)`.
- **`EmailStr` capped at 254 chars** (RFC 5321) at the schema
  boundary so a pathological client cannot amplify memory via long
  strings.
- **Resend client hardened.** `send_auth_code` distinguishes 429 (via
  `EmailRateLimitedError`) from other failures, inspects the 2xx JSON
  body for `{"error": ...}`, and redacts recipient emails to a
  SHA-256 fingerprint in log lines.
- **`routes_auth` unified on `HTTPException`.** The two endpoints
  now raise instead of returning raw `JSONResponse`, so every error
  flows through `api.app.http_exception_handler` for consistent
  envelope shape and `WWW-Authenticate` / `Retry-After` forwarding.
- **PII purged from logs.** Plaintext emails never hit log files;
  `_redact_email_for_log` (`sha256(email)[:10]`) is used everywhere.

**Tests added / hardened**

- Removed dead `_ = asyncio` / `_ = pytest` silencers from
  `test_auth.py`.
- New `test_verify_code_concurrent_claim_is_atomic` asserts the CAS
  guarantees across two sequential verify calls on the same code.
- New `test_verify_code_unseen_email` covers the "code for an email
  that never requested one" path.
- New `test_request_code_resend_rate_limited` asserts 429 →
  `EMAIL_RATE_LIMITED` + `Retry-After: 60`.
- New middleware tests for empty Bearer, bool `user_id`, string
  `user_id`, and missing `exp` claim.



