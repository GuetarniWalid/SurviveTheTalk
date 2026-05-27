-- 010_scenarios_ladder_impatience.sql
-- Story 6.13 AC3 — per-difficulty stage-1 impatience anchor.
--
-- Adds a nullable `ladder_impatience_seconds` column to `scenarios` so
-- the existing override pattern (`silence_prompt_seconds` /
-- `silence_hangup_seconds`) extends to the new knob. When null, the
-- difficulty preset wins (easy=4.5 / medium=3.5 / hard=2.5 s); when
-- non-null, the YAML override wins. The column is REAL (not INTEGER —
-- production values are fractional) and seeded by `seed_scenarios.py`
-- on every server start; pre-existing rows backfill to NULL which is
-- explicitly the "use preset" sentinel.
--
-- See `_bmad-output/implementation-artifacts/6-13-epic-6-prelaunch-hardening.md`
-- AC3 + Deviation #3 for the rationale (smoke gate call_id=148 found
-- the previously-hardcoded 3.0 s too aggressive; harder scenarios get
-- snappier face-shifts to match "Mugger should be impatient by
-- design" semantics).

ALTER TABLE scenarios ADD COLUMN ladder_impatience_seconds REAL;
