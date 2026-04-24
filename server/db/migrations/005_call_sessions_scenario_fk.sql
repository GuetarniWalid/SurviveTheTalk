-- 005_call_sessions_scenario_fk.sql
-- Story 5.1 cleanup #4: add the FK call_sessions(scenario_id) → scenarios(id).
-- The comment in 002_calls.sql said the FK "will be added in a future
-- migration" — that future is now, since 004 just created the scenarios
-- table. Deferring further would compound the dependency debt every story
-- that touches calls.
--
-- SQLite < 3.35 cannot ALTER ADD CONSTRAINT FOREIGN KEY, so we rebuild the
-- table. PRAGMA foreign_keys=OFF wraps the rebuild because DROP TABLE
-- triggers FK validation otherwise (see migration 003 lesson).
PRAGMA foreign_keys = OFF;
BEGIN;
CREATE TABLE call_sessions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    started_at TEXT NOT NULL,
    duration_sec INTEGER,
    cost_cents INTEGER
);
INSERT INTO call_sessions_new (id, user_id, scenario_id, started_at, duration_sec, cost_cents)
    SELECT id, user_id, scenario_id, started_at, duration_sec, cost_cents FROM call_sessions;
DROP TABLE call_sessions;
ALTER TABLE call_sessions_new RENAME TO call_sessions;
CREATE INDEX IF NOT EXISTS idx_call_sessions_user_id ON call_sessions(user_id);
COMMIT;
PRAGMA foreign_keys = ON;
