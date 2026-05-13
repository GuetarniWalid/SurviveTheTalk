-- 008_call_sessions_status.sql
-- Story 6.5 — voluntary call end + janitor sweep.
--
-- Adds a `status` column to `call_sessions` so:
--   - 'pending'   = INSERTed by /calls/initiate, not yet ended; counts toward
--                   the cap so a malicious tight-loop /initiate cannot bypass
--                   FR21. Janitor flips abandoned-`pending` rows older than
--                   1 h to 'failed' (see db/janitor.py).
--   - 'completed' = /calls/{id}/end fired successfully; counts toward cap.
--   - 'failed'    = Janitored or never spawned (Popen rollback). Does NOT
--                   count toward cap — the user gets the quota back.
--
-- Plan A chosen: `ALTER TABLE ADD COLUMN` with inline CHECK constraint
-- (SQLite ≥ 3.25 supports CHECK on ADD COLUMN). Historical rows backfill
-- as 'completed' via the DEFAULT — they represent calls that already
-- happened pre-migration, so `calls_remaining` semantics are preserved
-- across the migration boundary (see story §"Why 'completed' is the
-- default backfill"). Plan B (full table-rebuild per 005) was the
-- documented fallback but is unnecessary at the SQLite version we ship.
ALTER TABLE call_sessions
ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'
    CHECK (status IN ('pending', 'completed', 'failed'));
