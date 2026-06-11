-- 013_remove_scenario_difficulty.sql
-- Story 6.28 — Remove per-scenario difficulty (global-only product ruling).
--
-- Walid, 2026-06-10 (Story 6.27 decision pass D3): the ONLY difficulty
-- cursor is the user's GLOBAL setting; scenarios exist purely to vary the
-- experience. The authored `scenarios.difficulty` label (legacy from the
-- pre-6.19 design) is dropped; hub ordering — previously a CASE bucket on
-- that column — is replaced by an explicit nullable `display_order`
-- (authored in YAML `metadata.display_order`, seeded on every boot, NULLs
-- sort last so future daily scenarios append at the end by default).
--
-- Replay note: `ALTER TABLE … DROP COLUMN` exists since SQLite 3.35 and
-- drops the column-level CHECK('easy','medium','hard') with the column
-- (empirically verified 2026-06-11 on 3.49.1 local + rows + inbound-FK
-- tables; VPS runs 3.45.1). Inbound FKs reference `scenarios.id`, not
-- `difficulty`, so no table rebuild and no `PRAGMA foreign_keys=OFF` is
-- needed (the Story-5.1 rebuild trap does not apply). Replays green
-- against `tests/fixtures/prod_snapshot.sqlite` — existing rows keep all
-- other columns, `display_order` backfills NULL until the seeder runs.

ALTER TABLE scenarios DROP COLUMN difficulty;
ALTER TABLE scenarios ADD COLUMN display_order INTEGER;
