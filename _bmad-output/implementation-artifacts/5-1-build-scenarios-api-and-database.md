# Story 5.1: Build Scenarios API and Database

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want the server to provide my scenario list with my progression data,
So that the app can display my available scenarios and track my progress.

## Acceptance Criteria (BDD)

**AC1 — Scenarios schema migration (ADR 001):**
Given the Architecture defines a `scenarios` table and ADR 001 freezes the canonical column list
When migration `004_scenarios_and_user_progress.sql` is applied at startup
Then the `scenarios` table exists with these columns and constraints (exact list — see ADR 001 §Canonical column list):
  - `id` TEXT PRIMARY KEY
  - `title` TEXT NOT NULL
  - `difficulty` TEXT NOT NULL CHECK(difficulty IN ('easy','medium','hard'))
  - `is_free` INTEGER NOT NULL CHECK(is_free IN (0,1))
  - `rive_character` TEXT NOT NULL
  - `base_prompt` TEXT NOT NULL
  - `checkpoints` TEXT NOT NULL (JSON array of objects)
  - `briefing` TEXT NOT NULL (JSON object `{vocabulary, context, expect}`)
  - `exit_lines` TEXT NOT NULL (JSON object `{hangup, completion}`)
  - `language_focus` TEXT NOT NULL (JSON array of strings)
  - `content_warning` TEXT NULL
  - `patience_start`, `fail_penalty`, `silence_penalty`, `recovery_bonus`, `silence_prompt_seconds`, `silence_hangup_seconds` INTEGER NULL
  - `escalation_thresholds` TEXT NULL (JSON array)
  - `tts_voice_id` TEXT NULL
  - `tts_speed` REAL NULL
  - `scoring_model` TEXT NULL
And the `user_progress` table exists with:
  - `user_id` INTEGER NOT NULL REFERENCES users(id)
  - `scenario_id` TEXT NOT NULL REFERENCES scenarios(id)
  - `best_score` INTEGER NULL (CHECK 0..100)
  - `attempts` INTEGER NOT NULL DEFAULT 0
  - `updated_at` TEXT NOT NULL
  - PRIMARY KEY (`user_id`, `scenario_id`)
And the migration is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

**AC2 — Tier rename migration (ADR 002):**
Given `001_init.sql` still has `CHECK(tier IN ('free','full'))` and ADR 002 freezes `'paid'` as canonical
When migration `003_tier_rename_full_to_paid.sql` is applied at startup
Then the `users` table's CHECK constraint becomes `CHECK(tier IN ('free','paid'))` via the SQLite table-rebuild idiom (BEGIN → CREATE TABLE users_new → INSERT … SELECT … FROM users → DROP TABLE users → ALTER TABLE users_new RENAME TO users → recreate `idx_users_email` → COMMIT)
And `001_init.sql` is NOT modified in place (migrations are immutable once applied)
And the rename runs BEFORE `004_scenarios_and_user_progress.sql` (lexical ordering `003_ < 004_`)
And no row in `users` has `tier='full'` after the migration (zero production rows exist with that value today).

**AC3 — Scenarios seeded from YAML on startup:**
Given 5 authored YAML scenarios live in `server/pipeline/scenarios/` (the-waiter, the-mugger, the-girlfriend, the-cop, the-landlord — copies of `_bmad-output/planning-artifacts/scenarios/*.yaml`)
When the FastAPI lifespan runs after `run_migrations()`
Then a seeder reads each YAML and upserts its row into `scenarios` via `INSERT … ON CONFLICT(id) DO UPDATE` (or `INSERT OR REPLACE`), serializing:
  - `briefing` = `json.dumps(yaml["briefing"])` (object preserved)
  - `exit_lines` = `json.dumps(yaml["exit_lines"])` (object preserved)
  - `language_focus` = `json.dumps([s.strip() for s in yaml["metadata"]["language_focus"].split(",") if s.strip()])` (YAML comma-string → JSON array, per ADR 001 Q3)
  - `checkpoints` = `json.dumps(yaml["checkpoints"])` (list of objects preserved)
  - `escalation_thresholds` = `json.dumps(yaml["metadata"]["escalation_thresholds"])` when not None
And re-running the seeder leaves row counts unchanged (idempotency verified by test)
And if any YAML fails to parse or is missing required keys, the seeder logs the offender and raises — startup fails loudly rather than booting with a corrupt catalog.

**AC4 — `GET /scenarios` returns ordered list with progression:**
Given a user with a valid JWT calls `GET /scenarios`
When the endpoint processes the request
Then it responds `200` with `{"data": [...], "meta": {"count": <int>, "timestamp": "<iso>"}}` (snake_case fields throughout)
And the list contains every scenario (free + paid — server never filters by tier; client renders the lock affordance in Story 5.3)
And scenarios are ordered by `difficulty` ASC in the bucket order `easy(1) < medium(2) < hard(3)`, then by `id` ASC as the stable secondary key
And each item carries the LIST-ITEM shape: `id`, `title`, `difficulty`, `is_free` (bool), `rive_character`, `language_focus` (array), `content_warning` (string|null), `best_score` (int|null), `attempts` (int)
And `best_score` + `attempts` come from a LEFT JOIN against `user_progress` for the JWT's `user_id` — NULL best_score and 0 attempts for never-attempted scenarios.

**AC5 — `GET /scenarios/{id}` returns full scenario detail:**
Given a user with a valid JWT calls `GET /scenarios/waiter_easy_01`
When the endpoint processes the request
Then it responds `200` with the DETAIL shape wrapped in the same envelope: every column from AC1 plus `best_score` + `attempts`
And JSON-encoded columns are decoded before the response is built (`briefing`, `exit_lines`, `checkpoints`, `language_focus`, `escalation_thresholds` are returned as native JSON types, NOT as strings)
And `is_free` is coerced to `bool` in the response payload
And nullable override fields are `null` (not missing keys) when their DB column is NULL — clients rely on key presence for optional-chaining.

**AC6 — Auth and error envelopes:**
Given a request has no `Authorization` header or an invalid/expired JWT
When either endpoint processes the request
Then it responds `401` with `{"error": {"code": "AUTH_UNAUTHORIZED", "message": "..."}}` (or `AUTH_TOKEN_EXPIRED`) — via the existing `AUTH_DEPENDENCY` + `http_exception_handler` in `api/app.py`
And a request for an unknown `scenario_id` on `GET /scenarios/{id}` responds `404` with `{"error": {"code": "SCENARIO_NOT_FOUND", "message": "..."}}`.

**AC7 — Regression and pre-commit gates:**
Given pre-commit requirements from CLAUDE.md
When the story is complete
Then `cd server && python -m ruff check .` + `cd server && python -m ruff format --check .` + `cd server && pytest` all return green
And every existing test (`test_auth`, `test_calls`, `test_call_endpoint`, `test_middleware`, `test_queries`, `test_envelope`, `test_health`, `test_prompts`, `test_no_audio_buffer`, `test_transcript_logger`, `test_score_transcript`, `test_config`) continues to pass — no regressions
And `cd client && flutter analyze` + `cd client && flutter test` pass unchanged (this story touches NO Flutter code, but the pre-commit gate still runs the full matrix).

## Tasks / Subtasks

- [ ] Task 1: Copy the 4 missing scenario YAMLs into `server/pipeline/scenarios/` (AC: 3)
  - [ ] 1.1 Copy `_bmad-output/planning-artifacts/scenarios/the-mugger.yaml` → `server/pipeline/scenarios/the-mugger.yaml`
  - [ ] 1.2 Copy `_bmad-output/planning-artifacts/scenarios/the-girlfriend.yaml` → `server/pipeline/scenarios/the-girlfriend.yaml`
  - [ ] 1.3 Copy `_bmad-output/planning-artifacts/scenarios/the-cop.yaml` → `server/pipeline/scenarios/the-cop.yaml`
  - [ ] 1.4 Copy `_bmad-output/planning-artifacts/scenarios/the-landlord.yaml` → `server/pipeline/scenarios/the-landlord.yaml`
  - [ ] 1.5 Do NOT modify `server/pipeline/scenarios/the-waiter.yaml` (already present since Story 4.5)
  - [ ] 1.6 Add a short note at the top of `server/pipeline/scenarios/README.md` (new file, one paragraph) saying: "Canonical source lives in `_bmad-output/planning-artifacts/scenarios/`. Copies here keep production deploys self-contained. On authoring change, copy the updated YAML into this folder and redeploy."

- [ ] Task 2: Add migration `003_tier_rename_full_to_paid.sql` (AC: 2)
  - [ ] 2.1 Create `server/db/migrations/003_tier_rename_full_to_paid.sql` using the exact SQL from ADR 002 §Files to change (see Dev Notes → Migration SQL)
  - [ ] 2.2 Do NOT modify `001_init.sql` (immutable)
  - [ ] 2.3 Verify `run_migrations()` applies 003 in lexical order between 002 and 004 (no code change needed — the sorted-glob logic already handles this)

- [ ] Task 3: Add migration `004_scenarios_and_user_progress.sql` (AC: 1)
  - [ ] 3.1 Create `server/db/migrations/004_scenarios_and_user_progress.sql` with the full SQL block from Dev Notes → Migration SQL
  - [ ] 3.2 Include the `scenarios` table (21 columns per ADR 001) and the `user_progress` table (5 columns + composite PK)
  - [ ] 3.3 Add indexes: `CREATE INDEX IF NOT EXISTS idx_user_progress_user_id ON user_progress(user_id)` (per-user list JOIN)
  - [ ] 3.4 The migration must be idempotent — every `CREATE TABLE` / `CREATE INDEX` uses `IF NOT EXISTS`
  - [ ] 3.5 No seed data in the SQL file — seeding is Python-driven (Task 4)

- [ ] Task 4: Build scenarios seeder `server/db/seed_scenarios.py` (AC: 3)
  - [ ] 4.1 Create `server/db/seed_scenarios.py` with `async def seed_scenarios() -> None`
  - [ ] 4.2 Glob `server/pipeline/scenarios/*.yaml` via `Path(__file__).resolve().parent.parent / "pipeline" / "scenarios"` (resolve to survive VPS working-dir differences — Story 4.5 `pipeline/scenarios.py` uses the same pattern)
  - [ ] 4.3 For each YAML, parse via `yaml.safe_load`, extract `metadata` + `base_prompt` + `checkpoints` + `briefing` + `exit_lines`, build the INSERT parameter tuple per ADR 001 mapping (see Dev Notes → YAML → DB column mapping)
  - [ ] 4.4 Serialize `briefing`, `exit_lines`, `checkpoints`, `escalation_thresholds` with `json.dumps(..., ensure_ascii=False)` — keeps multibyte characters readable in the DB file for debugging
  - [ ] 4.5 Parse `language_focus` (YAML comma-string) into a trimmed list and `json.dumps` it
  - [ ] 4.6 Coerce `is_free: true/false` → `1/0`
  - [ ] 4.7 Use `INSERT INTO scenarios (...) VALUES (...) ON CONFLICT(id) DO UPDATE SET col=excluded.col, ...` — one statement per row (SQLite ≥ 3.24 supports `ON CONFLICT ... DO UPDATE`; `aiosqlite` bundles 3.42+)
  - [ ] 4.8 Log one info line per scenario upserted (`logger.info(f"Seeded scenario {scenario_id!r}")`) so deploys are observable
  - [ ] 4.9 Wrap the whole batch in a single `BEGIN IMMEDIATE … COMMIT` so a mid-file crash rolls back cleanly
  - [ ] 4.10 On any parse/serialization error, log the offending file + field and `raise` — startup MUST fail loudly rather than boot with a half-seeded catalog

- [ ] Task 5: Wire `seed_scenarios()` into the FastAPI lifespan (AC: 3)
  - [ ] 5.1 In `server/api/app.py`, extend the `lifespan` context manager to call `await seed_scenarios()` AFTER `await run_migrations()` and before `yield`
  - [ ] 5.2 Do NOT call `seed_scenarios()` from `run_migrations()` — migrations are pure SQL; seeding is app-layer logic. Keep them adjacent but separate
  - [ ] 5.3 Wrap the seed call in the lifespan's normal error flow: if it raises, FastAPI fails startup, `systemd` restarts, logs carry the traceback

- [ ] Task 6: Add scenario queries to `server/db/queries.py` (AC: 4, 5)
  - [ ] 6.1 Add `async def get_all_scenarios_with_progress(db, user_id: int) -> list[aiosqlite.Row]` — runs the LEFT JOIN SQL from Dev Notes → Queries, ordered easy→medium→hard then id
  - [ ] 6.2 Add `async def get_scenario_by_id_with_progress(db, user_id: int, scenario_id: str) -> aiosqlite.Row | None` — single-row LEFT JOIN by PK
  - [ ] 6.3 Add `async def upsert_scenario(db, row: dict) -> None` — used by the seeder; accepts a dict whose keys match the canonical column list
  - [ ] 6.4 Keep these functions DB-layer only — NO JSON decoding inside `queries.py`. The route handler (Task 8) is responsible for `json.loads` the TEXT columns into native types for the response

- [ ] Task 7: Add Pydantic schemas to `server/models/schemas.py` (AC: 4, 5)
  - [ ] 7.1 Add `ScenarioListItem(BaseModel)` with fields: `id: str`, `title: str`, `difficulty: str`, `is_free: bool`, `rive_character: str`, `language_focus: list[str]`, `content_warning: str | None`, `best_score: int | None`, `attempts: int`
  - [ ] 7.2 Add `ScenarioDetail(BaseModel)` extending the list fields with: `base_prompt: str`, `checkpoints: list[dict]`, `briefing: dict`, `exit_lines: dict`, `patience_start: int | None`, `fail_penalty: int | None`, `silence_penalty: int | None`, `recovery_bonus: int | None`, `silence_prompt_seconds: int | None`, `silence_hangup_seconds: int | None`, `escalation_thresholds: list[int] | None`, `tts_voice_id: str | None`, `tts_speed: float | None`, `scoring_model: str | None`
  - [ ] 7.3 Add `ScenariosListOut(BaseModel)` = `{data: list[ScenarioListItem]}` (only for documentation — the route returns the envelope dict directly via `ok_list`, see Task 9)
  - [ ] 7.4 Do NOT add an `InitiateCallIn` / `InitiateCallOut` rewrite — those are Story 4.5's, untouched

- [ ] Task 8: Extend the envelope helper with list-count meta (AC: 4)
  - [ ] 8.1 In `server/api/responses.py`, extend `ok(data, *, extra_meta: dict | None = None)` so `meta` can carry `count` (and future keys) without breaking existing callers
  - [ ] 8.2 Keep the current signature backwards-compatible — `ok(data)` still returns `{"data": …, "meta": {"timestamp": …}}` unchanged (the 5 existing call sites in `routes_auth.py` + `routes_calls.py` must not be edited)
  - [ ] 8.3 Add a convenience wrapper `ok_list(items: list[BaseModel] | list[dict]) -> dict` that fills `meta.count = len(items)` and `meta.timestamp = now_iso()` — this is the canonical helper for every list endpoint going forward

- [ ] Task 9: Build `routes_scenarios.py` with two endpoints (AC: 4, 5, 6)
  - [ ] 9.1 Create `server/api/routes_scenarios.py`:
    ```python
    router = APIRouter(prefix="/scenarios", tags=["scenarios"], dependencies=[AUTH_DEPENDENCY])
    ```
  - [ ] 9.2 `GET /scenarios` handler: read `user_id = request.state.user_id`, call `get_all_scenarios_with_progress`, map each row → `ScenarioListItem` (decoding `language_focus` from JSON, coercing `is_free` to bool, normalising `attempts` with `row["attempts"] or 0` for the NULL case), return `ok_list(items)`
  - [ ] 9.3 `GET /scenarios/{scenario_id}` handler: call `get_scenario_by_id_with_progress`; when None → `raise HTTPException(status_code=404, detail={"code": "SCENARIO_NOT_FOUND", "message": "Scenario not found."})` so the global handler produces the `{"error": {...}}` envelope
  - [ ] 9.4 Decode JSON columns in the detail response: `briefing`, `exit_lines`, `checkpoints`, `language_focus`, `escalation_thresholds`
  - [ ] 9.5 Return `ok(ScenarioDetail(...))` for the detail endpoint (single-object envelope, no `count`)
  - [ ] 9.6 Register the router in `server/api/app.py`: `from api.routes_scenarios import router as scenarios_router` + `app.include_router(scenarios_router)` — place the `include_router` call alphabetically with the others

- [ ] Task 10: Extend `test_queries.py` with scenario-query coverage (AC: 1, 4, 5)
  - [ ] 10.1 Add `test_migration_creates_scenarios_and_user_progress_tables(migrated_db)` — assert both tables + `idx_user_progress_user_id` exist
  - [ ] 10.2 Add `test_migration_recorded_in_schema_migrations(...)` — update existing test to assert `003_tier_rename_full_to_paid` AND `004_scenarios_and_user_progress` are present alongside `001_init` + `002_calls`
  - [ ] 10.3 Add `test_users_check_constraint_is_free_paid(migrated_db)` — read `sqlite_master.sql` for `users`, assert it contains `CHECK(tier IN ('free','paid'))` (NOT `'full'`)
  - [ ] 10.4 Add `test_insert_user_then_paid_update_succeeds(migrated_db)` — insert user → `UPDATE users SET tier='paid' WHERE id=?` → confirm row, then try `UPDATE users SET tier='full'` and assert it raises `sqlite3.IntegrityError` (CHECK violation)
  - [ ] 10.5 Add `test_seed_scenarios_populates_five_rows(migrated_db)` — run `await seed_scenarios()` → assert `SELECT COUNT(*) FROM scenarios == 5`
  - [ ] 10.6 Add `test_seed_scenarios_is_idempotent(migrated_db)` — run seeder twice → row count still 5, no duplicate-PK error
  - [ ] 10.7 Add `test_get_all_scenarios_with_progress_left_joins_correctly(migrated_db)` — seed + insert a user, insert a `user_progress` row for one scenario, call the query, assert that one row has `best_score/attempts` populated and the others have NULL/0
  - [ ] 10.8 Add `test_scenarios_ordered_easy_medium_hard(migrated_db)` — assert the returned list starts with an `easy` row, then `medium`, then `hard` (relies on the seeded 1/2/2 split)

- [ ] Task 11: Add `test_scenarios.py` for the HTTP endpoints (AC: 4, 5, 6)
  - [ ] 11.1 Create `server/tests/test_scenarios.py` — structure mirrors `test_calls.py` (see Dev Notes → Test patterns)
  - [ ] 11.2 `test_list_requires_jwt` — no Auth header → 401 `AUTH_UNAUTHORIZED`
  - [ ] 11.3 `test_detail_requires_jwt` — no Auth header → 401 `AUTH_UNAUTHORIZED`
  - [ ] 11.4 `test_list_returns_five_scenarios_ordered(client, mock_resend, test_db_path)` — register user, GET `/scenarios`, assert `meta.count == 5`, assert the `id` sequence starts with `waiter_easy_01` and ends with a `*_hard_*` id
  - [ ] 11.5 `test_list_shape_includes_progression_fields(...)` — assert every item has `best_score` (None for fresh user) and `attempts == 0`, `is_free` is a bool, `language_focus` is a list
  - [ ] 11.6 `test_list_includes_free_and_paid_mix(...)` — count `is_free=True` items == 3 (waiter, mugger, girlfriend), count `is_free=False` items == 2 (cop, landlord)
  - [ ] 11.7 `test_detail_returns_full_shape(...)` — GET `/scenarios/waiter_easy_01`, assert `briefing` is an object with keys `vocabulary`/`context`/`expect`, `exit_lines` has `hangup`/`completion`, `checkpoints` is a non-empty list, `base_prompt` contains `"Tina"`, `content_warning` is null
  - [ ] 11.8 `test_detail_returns_404_on_unknown_id(...)` — GET `/scenarios/nonexistent_id` → 401? NO — auth passes; expect 404 + `error.code == "SCENARIO_NOT_FOUND"`
  - [ ] 11.9 `test_list_reflects_user_progress(...)` — insert a `user_progress` row (via raw SQL in the test) for `waiter_easy_01` with `best_score=75, attempts=2`, GET `/scenarios`, assert that one item carries `best_score=75, attempts=2` while the others stay at None/0
  - [ ] 11.10 `test_envelope_shape(...)` — assert `"data"` + `"meta"` keys, `meta.count` is an int for the list endpoint, `meta.timestamp` ends with `"Z"` — DO NOT assert the exact timestamp value (time-dependent)

- [ ] Task 12: Regression check — `/calls/initiate` and `/connect` still work (AC: 7)
  - [ ] 12.1 Re-run the full `pytest` suite — the new `seed_scenarios()` call in the lifespan MUST NOT break `test_calls.py` or `test_call_endpoint.py`
  - [ ] 12.2 If the seeder raises during a test that did NOT expect it (e.g. a YAML is missing), the `TestClient` context manager will fail at `__enter__` and every test using `client` will error out — debug the seeder path before blaming individual tests
  - [ ] 12.3 If `run_migrations()` now loops over 4 files instead of 2, `test_migration_recorded_in_schema_migrations` in `test_queries.py` needs its expected-set updated — already covered by Task 10.2

- [ ] Task 13: Pre-commit validation gates (AC: 7)
  - [ ] 13.1 `cd server && python -m ruff check .` → zero issues (use `python -m ruff` on Windows per memory — `bare ruff` path-resolves wrong)
  - [ ] 13.2 `cd server && python -m ruff format --check .` → zero diffs
  - [ ] 13.3 `cd server && pytest` → all green (including the new scenario tests AND every existing test)
  - [ ] 13.4 `cd client && flutter analyze` → "No issues found!" (no Flutter code changed, but CI gates the full matrix)
  - [ ] 13.5 `cd client && flutter test` → "All tests passed!"
  - [ ] 13.6 Only after 13.1–13.5 are all green, flip status in `sprint-status.yaml` and execute the Smoke Test Gate below (per CLAUDE.md + memory: NEVER commit autonomously — wait for Walid to say "commit ça")

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story touches the DB (two new migrations, new tables) and adds two new HTTP endpoints — Smoke Test Gate is **required** before flipping to review.
>
> **Transition rule:** Every unchecked box below is a stop-ship for the `in-progress → review` transition. Paste the actual command run and its output as proof — a checked box without evidence does not count.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->

- [ ] **Happy-path list endpoint.** Authenticated `GET /scenarios` returns the 5-scenario envelope in the expected order.
  - _Command:_ `curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/scenarios | jq '.data[].id, .meta.count'`
  - _Expected:_ `200`; `data[0].id == "waiter_easy_01"`; `meta.count == 5`; response contains both `is_free: true` and `is_free: false` entries
  - _Actual:_ <!-- paste output -->

- [ ] **Happy-path detail endpoint.** Authenticated `GET /scenarios/waiter_easy_01` returns the full scenario body with decoded JSON fields.
  - _Command:_ `curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/scenarios/waiter_easy_01 | jq '.data | {id, briefing, exit_lines, checkpoints: (.checkpoints | length)}'`
  - _Expected:_ `briefing` is an object with `vocabulary`/`context`/`expect`; `exit_lines` has `hangup`/`completion`; `checkpoints.length >= 5`
  - _Actual:_ <!-- paste output -->

- [ ] **Error / unauth path produces the `{error}` envelope.**
  - _Command:_ `curl -sS -i http://167.235.63.129/scenarios` (no Auth header) AND `curl -sS -i -H "Authorization: Bearer $JWT" http://167.235.63.129/scenarios/does_not_exist`
  - _Expected:_ first request → `401` + `{"error": {"code": "AUTH_UNAUTHORIZED", ...}}`; second → `404` + `{"error": {"code": "SCENARIO_NOT_FOUND", ...}}`
  - _Actual:_ <!-- paste output -->

- [ ] **DB side-effect verified.** Both migrations applied and 5 scenarios seeded.
  - _Command:_ `sqlite3 /opt/surviveTheTalk/app.db "SELECT version FROM schema_migrations ORDER BY version;"` AND `sqlite3 /opt/surviveTheTalk/app.db "SELECT sql FROM sqlite_master WHERE name='users';"` AND `sqlite3 /opt/surviveTheTalk/app.db "SELECT COUNT(*) FROM scenarios;"`
  - _Expected:_ migrations list includes `001_init`, `002_calls`, `003_tier_rename_full_to_paid`, `004_scenarios_and_user_progress`; users DDL contains `CHECK(tier IN ('free','paid'))`; scenarios count = 5
  - _Actual:_ <!-- paste output -->

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 100 --since "5 min ago"` shows no ERROR / Traceback on the curl round-trips above, plus one `Seeded scenario 'waiter_easy_01'` (etc.) log line per scenario at startup.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

## Dev Notes

### Scope Boundary (What This Story Does and Does NOT Do)

| In scope (this story) | Out of scope (later stories) |
|---|---|
| `scenarios` + `user_progress` tables + their indexes | Writes to `user_progress` (Story 6.4 / 7.1 — post-call) |
| `003_tier_rename_full_to_paid.sql` + `004_scenarios_and_user_progress.sql` | Any tier-enforcement branching (`if user.tier == 'paid'` on call initiate) — Story 6.1 |
| YAML → DB seeder invoked from the lifespan | BottomOverlayCard, daily call-limit UI/logic — Story 5.3 |
| `GET /scenarios` + `GET /scenarios/{id}` + their Pydantic schemas | `GET /user/profile` (returns tier + stats) — deferred |
| Envelope helper `ok_list(items)` with `meta.count` | Content-warning dialog — Story 5.4 |
| Regression tests proving old endpoints still work | ScenariosBloc / ScenarioListScreen / ScenarioCard — Story 5.2 |
| Smoke Test Gate on VPS | FK from `call_sessions.scenario_id` → `scenarios.id` — deferred |

### ADR References (READ BEFORE CODING)

- **ADR 001 — Scenarios Schema** (`_bmad-output/planning-artifacts/adr/001-scenarios-schema.md`) — canonical column list for `scenarios`, JSON-in-TEXT decisions, `language_focus` parsing rule, `briefing` / `exit_lines` shape. **The canonical table at the end of the ADR is the source of truth** — if this story's AC and the ADR disagree on a column, the ADR wins.
- **ADR 002 — Tier Naming** (`_bmad-output/planning-artifacts/adr/002-tier-naming.md`) — canonical `'paid'` literal, exact migration SQL, confirms no production row has `tier='full'`. **Any occurrence of the string `'full'` in new code is a bug.**
- **Epic 4 Retro — AI-B Smoke Test Gate** (`_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md`) — this story is the first DB-touching story after the retro; the Smoke Test Gate section above is non-optional.

### Migration SQL

**`003_tier_rename_full_to_paid.sql`** — copy verbatim from ADR 002:

```sql
-- 003_tier_rename_full_to_paid.sql
-- Rename CHECK(tier IN ('free','full')) → CHECK(tier IN ('free','paid')).
-- No rows with tier='full' exist in production; this migration is schema-only.
BEGIN;
CREATE TABLE users_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    jwt_hash TEXT,
    tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','paid')),
    created_at TEXT NOT NULL
);
INSERT INTO users_new (id, email, jwt_hash, tier, created_at)
    SELECT id, email, jwt_hash, tier, created_at FROM users;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
COMMIT;
```

> **Foreign-key safety note:** `call_sessions(user_id) REFERENCES users(id)` — because SQLite stores FKs by name, dropping and rebuilding `users` could break existing FK references. Since the migration keeps `users.id` values 1:1 across the rebuild (the INSERT copies every row including `id`) and runs inside a single transaction with `PRAGMA foreign_keys = ON`, existing FK references remain valid. Cross-check during VPS smoke test by running a `SELECT` that joins `call_sessions` with `users` after the migration.

**`004_scenarios_and_user_progress.sql`** — exact template (fill in and trim comments as you see fit, but the column types and constraints are frozen):

```sql
-- 004_scenarios_and_user_progress.sql
-- Story 5.1. Canonical column list per ADR 001 (scenarios) + user_progress
-- (progression tracking, write path lands in Story 6.4 / 7.1).

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK(difficulty IN ('easy','medium','hard')),
    is_free INTEGER NOT NULL CHECK(is_free IN (0,1)),
    rive_character TEXT NOT NULL,
    base_prompt TEXT NOT NULL,
    checkpoints TEXT NOT NULL,          -- JSON array
    briefing TEXT NOT NULL,             -- JSON object {vocabulary, context, expect}
    exit_lines TEXT NOT NULL,           -- JSON object {hangup, completion}
    language_focus TEXT NOT NULL,       -- JSON array of strings
    content_warning TEXT,               -- nullable
    patience_start INTEGER,
    fail_penalty INTEGER,
    silence_penalty INTEGER,
    recovery_bonus INTEGER,
    silence_prompt_seconds INTEGER,
    silence_hangup_seconds INTEGER,
    escalation_thresholds TEXT,         -- JSON array, nullable
    tts_voice_id TEXT,
    tts_speed REAL,
    scoring_model TEXT
);

CREATE TABLE IF NOT EXISTS user_progress (
    user_id INTEGER NOT NULL REFERENCES users(id),
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    best_score INTEGER CHECK(best_score IS NULL OR (best_score BETWEEN 0 AND 100)),
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, scenario_id)
);
CREATE INDEX IF NOT EXISTS idx_user_progress_user_id ON user_progress(user_id);
```

### YAML → DB column mapping (seeder contract)

For each YAML file under `server/pipeline/scenarios/*.yaml`:

| DB column | YAML source | Transform |
|---|---|---|
| `id` | `metadata.id` | pass-through |
| `title` | `metadata.title` | pass-through |
| `difficulty` | `metadata.difficulty` | pass-through (value ∈ `easy`/`medium`/`hard`) |
| `is_free` | `metadata.is_free` | `1 if true else 0` |
| `rive_character` | `metadata.rive_character` | pass-through |
| `base_prompt` | top-level `base_prompt` | pass-through (preserves `/no_think` prefix — do NOT strip it) |
| `checkpoints` | top-level `checkpoints` | `json.dumps(list_of_dicts, ensure_ascii=False)` |
| `briefing` | top-level `briefing` | `json.dumps(dict, ensure_ascii=False)` |
| `exit_lines` | top-level `exit_lines` | `json.dumps(dict, ensure_ascii=False)` |
| `language_focus` | `metadata.language_focus` | `json.dumps([s.strip() for s in str.split(",") if s.strip()])` |
| `content_warning` | `metadata.content_warning` | pass-through (None → SQL NULL) |
| `patience_start` | `metadata.patience_start` | pass-through (may be None) |
| `fail_penalty` | `metadata.fail_penalty` | pass-through |
| `silence_penalty` | `metadata.silence_penalty` | pass-through |
| `recovery_bonus` | `metadata.recovery_bonus` | pass-through |
| `silence_prompt_seconds` | `metadata.silence_prompt_seconds` | pass-through |
| `silence_hangup_seconds` | `metadata.silence_hangup_seconds` | pass-through |
| `escalation_thresholds` | `metadata.escalation_thresholds` | `json.dumps(...)` when not None else None |
| `tts_voice_id` | `metadata.tts_voice_id` | pass-through |
| `tts_speed` | `metadata.tts_speed` (may be missing) | `.get("tts_speed")` |
| `scoring_model` | `metadata.scoring_model` (may be missing) | `.get("scoring_model")` |

The `calibration:` block at the bottom of each YAML is NOT persisted — it's authoring metadata for Epic 3 calibration tracking only.

### Queries (exact SQL shape)

```sql
-- get_all_scenarios_with_progress
SELECT
    s.*,
    up.best_score,
    COALESCE(up.attempts, 0) AS attempts
FROM scenarios s
LEFT JOIN user_progress up
    ON up.scenario_id = s.id
    AND up.user_id = :user_id
ORDER BY
    CASE s.difficulty
        WHEN 'easy' THEN 1
        WHEN 'medium' THEN 2
        WHEN 'hard' THEN 3
    END ASC,
    s.id ASC;

-- get_scenario_by_id_with_progress
SELECT
    s.*,
    up.best_score,
    COALESCE(up.attempts, 0) AS attempts
FROM scenarios s
LEFT JOIN user_progress up
    ON up.scenario_id = s.id
    AND up.user_id = :user_id
WHERE s.id = :scenario_id;
```

> **Why the `CASE` expression:** `difficulty` is a TEXT column, so a plain `ORDER BY difficulty` sorts `easy`/`hard`/`medium` alphabetically (wrong). Mapping to an integer ordering in SQL keeps sorting inside SQLite — no post-fetch Python sorting needed.

### Response payload shapes

**`GET /scenarios`** — snake_case, `is_free` is a bool:

```json
{
  "data": [
    {
      "id": "waiter_easy_01",
      "title": "The Waiter",
      "difficulty": "easy",
      "is_free": true,
      "rive_character": "waiter",
      "language_focus": ["ordering food", "polite requests", "food adjectives"],
      "content_warning": null,
      "best_score": null,
      "attempts": 0
    }
    // ... 4 more
  ],
  "meta": { "count": 5, "timestamp": "2026-04-24T12:00:00Z" }
}
```

**`GET /scenarios/{id}`** — adds the authoring body:

```json
{
  "data": {
    "id": "waiter_easy_01",
    "title": "The Waiter",
    "difficulty": "easy",
    "is_free": true,
    "rive_character": "waiter",
    "language_focus": ["ordering food", "polite requests", "food adjectives"],
    "content_warning": null,
    "base_prompt": "/no_think\nYou are Tina, …",
    "checkpoints": [{ "id": "greet", "hint_text": "…", "prompt_segment": "…", "success_criteria": "…" }, …],
    "briefing": { "vocabulary": "…", "context": "…", "expect": "…" },
    "exit_lines": { "hangup": "*heavy sigh* I'm done. Next customer.", "completion": "Huh. …" },
    "patience_start": null,
    "fail_penalty": null,
    "silence_penalty": null,
    "recovery_bonus": null,
    "silence_prompt_seconds": null,
    "silence_hangup_seconds": null,
    "escalation_thresholds": null,
    "tts_voice_id": "62ae83ad-4f6a-430b-af41-a9bede9286ca",
    "tts_speed": null,
    "scoring_model": null,
    "best_score": null,
    "attempts": 0
  },
  "meta": { "timestamp": "2026-04-24T12:00:00Z" }
}
```

### Test patterns (what to mirror)

- **`test_calls.py`** is the closest precedent — its `_register_user` helper (register via auth flow, fetch code from SQLite, verify to obtain user_id + token) is exactly the pattern the new `test_scenarios.py` needs. Copy that helper verbatim (or extract it into `conftest.py` if you prefer — DO NOT regress existing tests if you do).
- **`test_queries.py`** is the pattern for the migration + raw-query assertions — it uses `asyncio.run(...)` to drive async code from sync `pytest` tests (no `pytest-asyncio` in this repo).
- **Mock strategy:** `mock_resend` fixture is required for any test that calls `/auth/request-code` during user registration. DO NOT add a new `mock_something_for_scenarios` — the scenarios endpoints have no external calls to mock.
- **DB isolation:** the `test_db_path` + `client` fixtures already wire a per-test temp SQLite file — every test gets a fresh migration + seeded-scenarios DB. Seeding runs inside the `TestClient(app)` context manager's `__enter__` (lifespan).

### Seeder — skeleton code to follow

```python
# server/db/seed_scenarios.py
"""Idempotent YAML → scenarios-table seeder (ADR 001).

Invoked from `api/app.py`'s lifespan AFTER `run_migrations()`. Reads every
`.yaml` file under `server/pipeline/scenarios/` and upserts it into the DB.
On any parse error or missing required key, raises so FastAPI startup fails
loudly rather than booting with a half-seeded catalog.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from loguru import logger

from db.database import get_connection

_SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "pipeline" / "scenarios"

_UPSERT_SQL = """
INSERT INTO scenarios (
    id, title, difficulty, is_free, rive_character,
    base_prompt, checkpoints, briefing, exit_lines, language_focus,
    content_warning,
    patience_start, fail_penalty, silence_penalty, recovery_bonus,
    silence_prompt_seconds, silence_hangup_seconds,
    escalation_thresholds,
    tts_voice_id, tts_speed, scoring_model
) VALUES (
    :id, :title, :difficulty, :is_free, :rive_character,
    :base_prompt, :checkpoints, :briefing, :exit_lines, :language_focus,
    :content_warning,
    :patience_start, :fail_penalty, :silence_penalty, :recovery_bonus,
    :silence_prompt_seconds, :silence_hangup_seconds,
    :escalation_thresholds,
    :tts_voice_id, :tts_speed, :scoring_model
)
ON CONFLICT(id) DO UPDATE SET
    title=excluded.title,
    difficulty=excluded.difficulty,
    is_free=excluded.is_free,
    rive_character=excluded.rive_character,
    base_prompt=excluded.base_prompt,
    checkpoints=excluded.checkpoints,
    briefing=excluded.briefing,
    exit_lines=excluded.exit_lines,
    language_focus=excluded.language_focus,
    content_warning=excluded.content_warning,
    patience_start=excluded.patience_start,
    fail_penalty=excluded.fail_penalty,
    silence_penalty=excluded.silence_penalty,
    recovery_bonus=excluded.recovery_bonus,
    silence_prompt_seconds=excluded.silence_prompt_seconds,
    silence_hangup_seconds=excluded.silence_hangup_seconds,
    escalation_thresholds=excluded.escalation_thresholds,
    tts_voice_id=excluded.tts_voice_id,
    tts_speed=excluded.tts_speed,
    scoring_model=excluded.scoring_model
"""


def _row_from_yaml(doc: dict) -> dict:
    meta = doc["metadata"]
    lf_raw = meta["language_focus"]
    language_focus = [s.strip() for s in lf_raw.split(",") if s.strip()]
    escalation = meta.get("escalation_thresholds")
    return {
        "id": meta["id"],
        "title": meta["title"],
        "difficulty": meta["difficulty"],
        "is_free": 1 if meta["is_free"] else 0,
        "rive_character": meta["rive_character"],
        "base_prompt": doc["base_prompt"],
        "checkpoints": json.dumps(doc["checkpoints"], ensure_ascii=False),
        "briefing": json.dumps(doc["briefing"], ensure_ascii=False),
        "exit_lines": json.dumps(doc["exit_lines"], ensure_ascii=False),
        "language_focus": json.dumps(language_focus, ensure_ascii=False),
        "content_warning": meta.get("content_warning"),
        "patience_start": meta.get("patience_start"),
        "fail_penalty": meta.get("fail_penalty"),
        "silence_penalty": meta.get("silence_penalty"),
        "recovery_bonus": meta.get("recovery_bonus"),
        "silence_prompt_seconds": meta.get("silence_prompt_seconds"),
        "silence_hangup_seconds": meta.get("silence_hangup_seconds"),
        "escalation_thresholds": (
            json.dumps(escalation) if escalation is not None else None
        ),
        "tts_voice_id": meta.get("tts_voice_id"),
        "tts_speed": meta.get("tts_speed"),
        "scoring_model": meta.get("scoring_model"),
    }


async def seed_scenarios() -> None:
    files = sorted(_SCENARIOS_DIR.glob("*.yaml"))
    if not files:
        raise RuntimeError(f"No scenario YAMLs found under {_SCENARIOS_DIR}")
    async with get_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            for path in files:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
                row = _row_from_yaml(doc)
                await db.execute(_UPSERT_SQL, row)
                logger.info(f"Seeded scenario {row['id']!r} from {path.name}")
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
```

> **The seeder uses named parameters (`:id`)** — `aiosqlite` + standard sqlite3 accept dict-style binding with this syntax. Matches the style the rest of the codebase avoids (positional `?`), but for a 21-column INSERT the named form is dramatically less error-prone.

### What NOT to Do

1. **Do NOT modify `001_init.sql`** — migrations are immutable once applied. The tier rename MUST be migration 003, even though it feels natural to "just fix 001".
2. **Do NOT write the literal string `'full'`** anywhere in new code. ADR 002 canonical value is `'paid'`. If you find `'full'` in a grep, it's a bug.
3. **Do NOT add tier-enforcement branching** (`if user.tier == 'paid': …`) to `routes_scenarios.py` — the endpoints return the full list regardless of tier. Tier-aware call-limit logic lives in Story 6.1, and client-side tier rendering lives in Story 5.3.
4. **Do NOT add a FK from `call_sessions.scenario_id` → `scenarios.id`.** The comment at the top of `002_calls.sql` says the FK "will be added in a future migration" — that future is NOT this story. Leave `call_sessions` untouched.
5. **Do NOT add `INSERT INTO scenarios (…)` statements to the SQL migration file.** Seeding is Python-driven (Task 4). A hardcoded SQL seed duplicates the YAML source of truth and drifts on every authoring change.
6. **Do NOT decode JSON columns inside `db/queries.py`** — queries return raw `aiosqlite.Row` objects. The route handler in `routes_scenarios.py` owns JSON decoding. Keep layers separated (Architecture Boundary 4 — raw-SQL only in queries).
7. **Do NOT import `pipeline.scenarios.TUTORIAL_SCENARIO_ID` from the new code.** Story 4.5's tutorial loader stays alive; it's orthogonal to the scenarios table. Story 6.1 reconciles both by retiring the loader.
8. **Do NOT add `SELECT * FROM scenarios WHERE is_free = 1` filtering on the list endpoint.** The full list is returned — client is the tier-rendering authority.
9. **Do NOT cache the seeder's work in a module-level variable.** The seeder is called once per process (lifespan). No in-memory cache needed; `INSERT … ON CONFLICT DO UPDATE` is idempotent for the deployment case where YAMLs were edited.
10. **Do NOT add a `-- seed --` section inside the SQL migration file.** See #5.
11. **Do NOT build a Flutter `Scenario` model, `ScenariosBloc`, or `ScenarioListScreen`** — that is Story 5.2's scope. This story is server-only.
12. **Do NOT modify or remove the existing `server/pipeline/scenarios.py` tutorial loader.** It's Story 4.5's contract; Story 6.1 retires it by routing `/calls/initiate` through the scenarios table.
13. **Do NOT use `pytest-asyncio`.** The repo uses plain `asyncio.run(...)` inside sync tests (see `test_queries.py`). Adding `pytest-asyncio` would churn the whole suite.
14. **Do NOT forget to update `sprint-status.yaml`** AT START (`ready-for-dev → in-progress`) and BEFORE COMMIT (`in-progress → review`) — memory: Epic 1 Retro Lesson, reaffirmed in every subsequent epic.
15. **Do NOT commit autonomously.** Memory rule (Git Commit Rules): Walid invokes `/commit` or says "commit ça" explicitly. Dev workflow stops at "review" status.
16. **Do NOT skip the Smoke Test Gate.** Epic 4 retro AI-B put this section in the template exactly so it can't be forgotten on a DB story. Every unchecked box = stop-ship.
17. **Do NOT add `/scenarios` tier-filtering or quota fields (`calls_remaining`, `daily_quota`, `is_locked`) to the response.** Those belong to the `/user/profile` or `/calls/quota` endpoints (future work).
18. **Do NOT add a dedicated `briefing_text` column** — ADR 001 Q1 renamed it to `briefing` (JSON object). Any grep for `briefing_text` in new code is a bug.

### Library & Version Requirements

**No new Python dependencies.** `pyyaml>=6.0,<7.0.0` is already in `server/pyproject.toml` (Story 4.5 added it). `aiosqlite` + `fastapi` + `loguru` + `pydantic` are all already in place.

**No new Flutter dependencies** — this story is server-only.

### Key Imports (Epic 1 Retro Lesson — exact imports = #1 velocity multiplier)

```python
# server/api/routes_scenarios.py
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from api.middleware import AUTH_DEPENDENCY
from api.responses import ok, ok_list
from db.database import get_connection
from db.queries import (
    get_all_scenarios_with_progress,
    get_scenario_by_id_with_progress,
)
from models.schemas import ScenarioDetail, ScenarioListItem
```

```python
# server/db/seed_scenarios.py
from __future__ import annotations

import json
from pathlib import Path

import yaml
from loguru import logger

from db.database import get_connection
```

```python
# server/tests/test_scenarios.py
from __future__ import annotations

import sqlite3
from unittest.mock import patch  # only if you stub anything — no external calls in these routes

import pytest
from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
```

### Previous Story Intelligence

**From Story 4.5 (Call Initiate + First-Call UX):**
- The `lifespan` context manager is the correct place for startup work — migrations are already there. Adding `seed_scenarios()` after `run_migrations()` matches the existing pattern.
- `mock_resend` must be injected into every test that goes through `/auth/request-code` (the `_register_user` helper) — otherwise the TestClient attempts a real Resend HTTP call and tests flake in CI.
- `subprocess.Popen` is mocked in `test_calls.py` with `@patch("api.routes_calls.subprocess.Popen")` — the same pattern applies if you ever need to patch a call-spawn elsewhere. **This story touches ZERO subprocess code**, so no Popen mocking needed.
- `ok(data)` is the envelope helper. Extending it with `extra_meta` keeps 5 existing call sites (auth, calls) untouched — see Task 8.2.
- `from __future__ import annotations` is the project's default EXCEPT in `conftest.py` (FastAPI's `Request` type hint needs runtime). Keep the exception when editing `conftest.py`.

**From Story 4.2 (Auth + JWT):**
- `AUTH_DEPENDENCY` on the `APIRouter` level is the one-liner for "every handler in this router requires JWT". No per-handler dependency needed.
- `http_exception_handler` in `api/app.py` wraps `HTTPException(detail={"code": "...", "message": "..."})` into the `{"error": {…}}` envelope automatically — matching the shape we use for `SCENARIO_NOT_FOUND`.
- Deterministic tests: the `JWT_SECRET` in `conftest.py` is 32 zero-bytes so `issue_token(user_id)` produces a reproducible token. Cross-test determinism is already wired.

**From Story 4.1 (Monorepo + Server Skeleton):**
- The `run_migrations()` function is idempotent and self-locking (BEGIN IMMEDIATE per migration). Your new migrations inherit that behavior for free — DO NOT attempt to wrap the batch in a new lock.
- `schema_migrations` table tracks applied versions by filename stem. Migration files MUST be named `NNN_snake_case.sql` — the file stem is the version string.

**From Epic 3 Retro (2026-04-15):**
- Calibration fields (`patience_start`, `fail_penalty`, etc.) remain nullable — presets come from `difficulty-calibration.md` §8 applied at the bot-spawn layer (Epic 6), not from the scenarios table. This story just persists the override values as-is.
- The Waiter YAML is the only pipeline-validated scenario (verdict: `pipeline-validated`); the other 4 are content-ready but not calibration-complete. **Story 5.1 seeds all 5 regardless** — calibration state lives in the YAML `calibration:` block which is NOT persisted.

**From Epic 4 Retro (2026-04-23):**
- Smoke Test Gate failed in both Epic 3 and Epic 4 because it was oral. The template now carries it as a checklist section. **Every unchecked box below the horizontal rule is a stop-ship.** Copy actual curl output, don't paraphrase.
- Tier-rename migration is intentionally separate from the scenarios migration so each can be reviewed and rolled back independently. Don't be tempted to combine them.

### Git Intelligence

Recent commit pattern to follow (from `git log --oneline -5`):
```
c00f3af feat: resolve Epic 5 blocking ADRs and add Smoke Test Gate to story template
d97ff27 feat: run Epic 4 retrospective and prepare Epic 5 kickoff
fd117b6 feat: implement first-call incoming call experience (Story 4.5)
28c2dca feat: implement consent, AI disclosure, and mic permission flow (Story 4.4)
```

**Files to read before starting (for patterns, NOT to modify beyond what tasks require):**
- `server/db/database.py` — `run_migrations()` idempotency + lifespan wiring (do NOT change the function; `seed_scenarios()` is a separate call from the lifespan)
- `server/db/migrations/001_init.sql` — existing CHECK constraint to be replaced (reference only; immutable file)
- `server/db/migrations/002_calls.sql` — migration file-naming + `IF NOT EXISTS` idioms
- `server/api/routes_calls.py` — `APIRouter(prefix=..., dependencies=[AUTH_DEPENDENCY])` + `ok(...)` + `HTTPException(detail={"code": ...})` pattern
- `server/api/routes_auth.py` — Pydantic IN/OUT models + `ok(Model(...))` pattern at the handler return site
- `server/db/queries.py` — raw-SQL boundary; every new query function goes here
- `server/tests/test_calls.py` — `_register_user` helper to copy; Popen/token mocking (not needed here but structure is the template)
- `server/tests/test_queries.py` — migration-assertion pattern (`sqlite_master` introspection) + `asyncio.run` style
- `server/tests/conftest.py` — fixtures already provide `test_db_path` + `client` + `mock_resend` + `protected_client`. Reuse as-is.
- `_bmad-output/planning-artifacts/adr/001-scenarios-schema.md` — canonical column list
- `_bmad-output/planning-artifacts/adr/002-tier-naming.md` — migration SQL + rationale
- `_bmad-output/planning-artifacts/scenarios/*.yaml` — source YAMLs (all 5 exist and are content-ready)

### Testing Requirements

**Target:** ~15 new Python tests (8 in `test_queries.py` per Task 10, 9 in `test_scenarios.py` per Task 11). ALL previous server tests must continue passing (currently 94+ from Epic 4). ALL Flutter tests unchanged.

**Mock strategy — Python:**
- `mock_resend` fixture → required for any test that registers a user via `/auth/request-code`
- No external-call mocking needed for `/scenarios` endpoints themselves (pure DB reads)
- `TestClient(app)` context runs the real lifespan → real migrations → real `seed_scenarios()` against the temp DB. This is the desired behavior (true integration tests).
- For the idempotency test (Task 10.6): either call `seed_scenarios()` twice directly inside the test, or re-instantiate the `TestClient` (each instance triggers a fresh lifespan). The direct double-call is simpler.

**Assertion helpers worth factoring:**
- Extract `_register_user(client, test_db_path)` into `conftest.py` if both `test_calls.py` and `test_scenarios.py` end up needing it (they will). DO NOT break `test_calls.py` during the extraction — run the suite after the refactor.

### Project Structure Notes

**Alignment with architecture (`architecture.md` §Backend Folder):** the target layout
```
server/api/routes_scenarios.py    # new — matches planned `routes_scenarios.py` in §Backend Folder
server/db/migrations/003_*.sql    # new
server/db/migrations/004_*.sql    # new
server/db/seed_scenarios.py       # new — DB-layer concern (not pipeline)
server/pipeline/scenarios/*.yaml  # 4 new copies + existing the-waiter.yaml
server/tests/test_scenarios.py    # new
```
matches the architecture plan line-for-line — no deviation, no new folders.

**Files to modify:**
- `server/api/app.py` — add `seed_scenarios` import, wire into lifespan, register `scenarios_router`
- `server/api/responses.py` — add `ok_list` helper (+ optional `extra_meta` on `ok`)
- `server/db/queries.py` — add three new query functions
- `server/models/schemas.py` — add `ScenarioListItem`, `ScenarioDetail`
- `server/tests/test_queries.py` — extend with 8 new tests (Task 10)
- (optionally) `server/tests/conftest.py` — extract `_register_user` helper if reused

**Files to verify but DO NOT modify:**
- `server/db/migrations/001_init.sql` — immutable
- `server/db/migrations/002_calls.sql` — immutable
- `server/api/routes_calls.py` — Story 4.5 contract, keep green
- `server/api/call_endpoint.py` — legacy `/connect`, keep green
- `server/pipeline/scenarios.py` — Story 4.5 tutorial loader, keep green
- `client/**/*.dart` — not touched by this story; Flutter checks still run in pre-commit

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Epic 5 Story 5.1`] — BDD acceptance criteria
- [Source: `_bmad-output/planning-artifacts/adr/001-scenarios-schema.md`] — canonical `scenarios` column list + JSON-in-TEXT decisions
- [Source: `_bmad-output/planning-artifacts/adr/002-tier-naming.md`] — `'paid'` canonical value + migration 003 SQL
- [Source: `_bmad-output/planning-artifacts/architecture.md#API & Communication Patterns`] — `/scenarios` + `/scenarios/{id}` contract, `{data, meta}` envelope, error shape
- [Source: `_bmad-output/planning-artifacts/architecture.md#Data Model`] — scenarios + user_progress rows
- [Source: `_bmad-output/planning-artifacts/prd.md#FR18 FR19 FR20 FR21 FR38`] — progression, ordering, tier access rules, content warnings
- [Source: `_bmad-output/planning-artifacts/scenarios/*.yaml`] — authoring-source-of-truth for the 5 seeded scenarios
- [Source: `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-23.md#AI-B`] — Smoke Test Gate requirement for DB/deploy stories
- [Source: `CLAUDE.md`] — pre-commit validation gates (ruff + pytest + flutter analyze + flutter test)

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
