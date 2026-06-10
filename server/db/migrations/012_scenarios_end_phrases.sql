-- 012_scenarios_end_phrases.sql
-- Story 7.2 — Call Ended overlay theatrical phrases.
--
-- One ADD-only schema change (no table rebuild), mirroring 011's
-- `scenarios.scenario_title`: the per-scenario `end_phrases` JSON object
-- (`{"hung_up": …, "voluntary": …, "survived": …}`) that the post-call
-- Call Ended overlay renders. Authored in each scenario YAML under
-- `metadata.end_phrases`, seeded on every server start, and exposed on the
-- client-facing `ScenarioListItem` so the app holds the phrases at
-- call-end with no extra fetch (Decision A — all user-facing content is
-- server-driven, never baked into the app).
--
-- Nullable: legacy rows pre-date the column and a YAML without the block
-- seeds NULL (the overlay hides the phrase element entirely — design P-7).
-- `ALTER TABLE ADD COLUMN` with a nullable column replays cleanly against
-- `tests/fixtures/prod_snapshot.sqlite` (existing rows backfill NULL, no
-- FK/CHECK is touched).

ALTER TABLE scenarios ADD COLUMN end_phrases TEXT;
