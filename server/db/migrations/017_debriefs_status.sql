-- 017_debriefs_status.sql
-- Story 10.7 (Bug B — progressive debrief) — a two-phase lifecycle column.
--
-- ADD-only, no table rebuild (so it replays cleanly against
-- `tests/fixtures/prod_snapshot.sqlite` — every existing debriefs row pre-dates
-- the column and is BACKFILLED to 'ready' by the DEFAULT; same safe posture as
-- 011/012/014/015/016, no `PRAGMA foreign_keys` toggle needed — nothing is
-- rebuilt, and a NOT NULL column with a literal DEFAULT backfills existing rows
-- without touching them).
--
-- WHY: today the debrief is generated ONCE inside the bot teardown and frozen —
-- if the LLM call exceeds the budget, a degraded (score-only) row is stored and
-- that is what the client shows forever (call_id=340 ReadTimeout). The
-- progressive design splits the debrief in two and persists them in two writes:
--   1. the SCORE half (survival %, checkpoints, attempt #, framing) is written
--      INSTANTLY at teardown with `status='pending'` (no LLM) so the client
--      renders the scorecard with ~no wait;
--   2. the ANALYSIS half (errors, idioms, areas, …) is generated INLINE and the
--      SAME row is UPDATEd to `status='ready'` once it lands.
-- A guarded `WHERE status='pending'` on the second write keeps a duplicate /
-- late writer (Popen retry, pooled re-run) from clobbering a completed blob or
-- resurrecting a degraded one.
--
-- Values: 'pending' = score stored, analysis still coming (keep polling);
-- 'ready' = terminal (full analysis OR the never-blank `degraded` fallback,
-- which lives INSIDE `debrief_json`). Existing rows backfill to 'ready' for
-- back-compat: every stored row pre-dates the two-phase write and is complete.

ALTER TABLE debriefs ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'
    CHECK (status IN ('pending', 'ready'));
