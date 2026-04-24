-- 006_user_progress_created_at_and_cascade.sql
-- Story 5.1 cleanup #3 + #5:
--   - Add `created_at` column (Story 7.1 debrief will want "first attempt"
--     timestamp; backfilling later = pain. Adding now while user_progress
--     is empty in production = trivial).
--   - Switch both FKs (user_id, scenario_id) to ON DELETE CASCADE so:
--     * RGPD user-deletion cleans up progression rows automatically
--     * removing a scenario from the catalog doesn't leave orphan rows
--
-- SQLite cannot ALTER FK behavior (or ADD COLUMN with NOT NULL+no DEFAULT
-- on a non-empty table), so we rebuild. user_progress is empty in prod
-- today, so the SELECT … FROM picks up zero rows — the rebuild is purely
-- schema. The COALESCE on the historical updated_at copy keeps the SELECT
-- shape correct if any row ever exists in dev DBs.
--
-- For pre-existing rows (none in prod, but possible in test DBs that ran
-- the 5.1 batch before this cleanup), `created_at` is backfilled to
-- `updated_at` — best-effort approximation since we have no better signal.
PRAGMA foreign_keys = OFF;
BEGIN;
CREATE TABLE user_progress_new (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    best_score INTEGER CHECK(best_score IS NULL OR (best_score BETWEEN 0 AND 100)),
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, scenario_id)
);
INSERT INTO user_progress_new (user_id, scenario_id, best_score, attempts, created_at, updated_at)
    SELECT user_id, scenario_id, best_score, attempts, updated_at, updated_at FROM user_progress;
DROP TABLE user_progress;
ALTER TABLE user_progress_new RENAME TO user_progress;
CREATE INDEX IF NOT EXISTS idx_user_progress_user_id ON user_progress(user_id);
COMMIT;
PRAGMA foreign_keys = ON;
