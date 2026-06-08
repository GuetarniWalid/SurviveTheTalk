-- 011_debriefs.sql
-- Story 7.1 — post-call debrief generation backend.
--
-- Three schema changes, all ADD-only (no table rebuild), so the migration
-- replays cleanly against `tests/fixtures/prod_snapshot.sqlite` (existing
-- rows pre-date every new column and take NULL / the new empty table is
-- never touched by them):
--
--   1. `debriefs` — one distilled debrief per call. The FULL transcript is
--      NEVER persisted (privacy, Decision 1 = Option A); only the LLM-core
--      analysis (`debrief_json`) + the backend-computed survival counts.
--      `call_session_id` is UNIQUE so a call has at most one debrief — the
--      bot writes it once at teardown (`INSERT OR IGNORE`-style idempotence
--      enforced by the UNIQUE constraint + the bot's single write).
--   2. `call_sessions.checkpoints_passed` / `total_checkpoints` — the
--      SERVER-authoritative checkpoint counts, written by the bot at
--      teardown (today the counts only ride the LiveKit data channel to the
--      CLIENT; the server never saw them). Nullable: legacy rows pre-date
--      the bot write, and a call whose bot crashed before teardown keeps
--      NULL.
--   3. `scenarios.scenario_title` — the dedicated debrief "mission" title
--      (e.g. "Give me your wallet"), distinct from `title` (the character
--      name, e.g. "The Mugger"). Decision 3. Nullable; seeded from each
--      scenario YAML's `metadata.scenario_title` on every server start.
--
-- `ALTER TABLE ADD COLUMN` (no rebuild) is safe here exactly as in 008/009/
-- 010 — every added column is nullable, so SQLite backfills existing rows
-- with NULL without touching them. No `PRAGMA foreign_keys` toggle needed
-- (no table is rebuilt; the new FK is on a fresh table).

CREATE TABLE IF NOT EXISTS debriefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_session_id INTEGER NOT NULL UNIQUE REFERENCES call_sessions(id),
    survival_pct INTEGER NOT NULL CHECK (survival_pct BETWEEN 0 AND 100),
    checkpoints_passed INTEGER,
    total_checkpoints INTEGER,
    debrief_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

ALTER TABLE call_sessions ADD COLUMN checkpoints_passed INTEGER;
ALTER TABLE call_sessions ADD COLUMN total_checkpoints INTEGER;

ALTER TABLE scenarios ADD COLUMN scenario_title TEXT;
