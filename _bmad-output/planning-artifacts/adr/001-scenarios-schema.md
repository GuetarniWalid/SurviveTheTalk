# ADR 001 — Scenarios Schema (YAML → SQLite)

**Status:** Accepted
**Date:** 2026-04-23
**Deciders:** Winston (Architect), Walid (Project Lead)
**Supersedes:** 4 open questions in `architecture.md:247` (Story 3.1 review notes)
**Blocks resolved:** Story 5.1

---

## Context

Epic 5 Story 5.1 extends migrations with a `scenarios` table seeded from 5 YAML files (`_bmad-output/planning-artifacts/scenarios/*.yaml`). The architecture row description (`architecture.md:247`) left 4 shape questions unresolved between the authored YAML form and the stored SQLite form. Each must be frozen before the migration and loader can be written.

Project constraints that shape the answers:
- Raw SQL via `server/db/queries.py`, no ORM. Migrations are numbered and immutable once applied (`001_init.sql`, `002_calls.sql`).
- Response envelope `{data, meta}` on `GET /scenarios` and `GET /scenarios/{id}`. No per-sub-key querying is required by either endpoint.
- Existing precedent in the same table: `checkpoints` and `escalation_thresholds` are already stored as JSON-encoded TEXT.

---

## Decisions

### Q1 — Briefing sub-keys (`vocabulary` / `context` / `expect`)

**Decision:** Store as **one `briefing` TEXT column, JSON-encoded** with the three sub-keys preserved. Rename from `briefing_text` to `briefing` to reflect the structured payload.

**Rationale:** No endpoint filters on a sub-key; both endpoints return the whole scenario. JSON encoding matches the existing `checkpoints` pattern in the same row, keeps the schema flat, and stays forward-compatible if a 4th sub-key is ever added without a migration.

**Loader impact:** `json.dumps(yaml_doc["briefing"])` → one INSERT parameter.
**Query impact:** `json.loads(row["briefing"])` in the response shaper. UI renders three labelled sections client-side. No SQL changes between `/scenarios` and `/scenarios/{id}`.

---

### Q2 — `exit_lines` (hangup / completion)

**Decision:** Dedicated **`exit_lines` TEXT column, JSON-encoded** as `{"hangup": "...", "completion": "..."}`. Not embedded in `base_prompt`, not a separate table.

**Rationale:** These are verbatim strings the bot must utter exactly on call end — they are runtime-addressable (`exit_lines.hangup` vs `exit_lines.completion`), not LLM steering. Embedding in `base_prompt` would force the LLM to paraphrase, defeating the purpose. A separate table is overkill for two static strings per scenario.

**Loader impact:** `json.dumps(yaml_doc["exit_lines"])`.
**Query impact:** `GET /scenarios/{id}` includes `exit_lines` in the scenario payload; the orchestrator reads `.hangup` or `.completion` at the appropriate call-end event. `GET /scenarios` omits this field from the list response (not needed for card rendering).

---

### Q3 — `language_focus` storage type

**Decision:** Store as **JSON array** in a TEXT column (e.g. `["refusing demands", "asking for clarification", "describing financial situation"]`). The loader parses the YAML comma-separated string into a trimmed array.

**Rationale:** `difficulty-calibration.md` §8.3 treats `language_focus` as an array (authoritative reference). UI will render this as chips or a bulleted list — consumers should not re-parse a delimited string. Storing canonical array form also makes future JSON1 queries (`json_each`) possible without string fragility.

**Loader impact:** `json.dumps([s.strip() for s in yaml_str.split(",") if s.strip()])`.
**Query impact:** Both endpoints expose `language_focus` as a JSON array in the response envelope. `GET /scenarios` may include it (useful for card subtitles); `GET /scenarios/{id}` always includes it.

---

### Q4 — `tts_speed` and `scoring_model`

**Decision:** **Persist as nullable columns in DB** (`tts_speed REAL`, `scoring_model TEXT`), populated by the loader from YAML when present, NULL otherwise. No runtime reads from YAML on the server.

**Rationale:** Consistency with the existing nullable-override pattern on the same row (`patience_start`, `fail_penalty`, `silence_penalty`, etc. — all nullable, default pulled from difficulty preset). Single source of truth = DB. Avoids a second read path where the bot spawner goes back to the YAML file on disk. Cost: two rarely-populated columns — negligible at 5–20 scenarios.

**Loader impact:** Pass through with `.get("tts_speed")` / `.get("scoring_model")`; SQLite stores NULL when absent.
**Query impact:** `GET /scenarios/{id}` exposes both fields (post-calibration tooling will read them). `GET /scenarios` omits them (list-view irrelevant).

---

## Consequences

**Positive**
- Schema matches the `checkpoints` / JSON-in-TEXT pattern already proven in this table — reviewers see consistency, not novelty.
- No runtime file I/O beyond DB reads. All scenario state is queryable from SQL.
- All four questions resolvable in a single Story 5.1 migration — no follow-up schema churn expected before Epic 6.

**Negative / trade-offs**
- JSON-in-TEXT loses per-sub-key constraint checking (e.g. we can't `NOT NULL` `briefing.vocabulary`). Validation moves to the loader.
- `exit_lines` and `briefing` cannot be filtered/joined via SQL without `json_extract`. Acceptable — no endpoint currently needs this.

**Canonical column list for Story 5.1 migration (`scenarios` table)**

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | TEXT | NO | PK, matches `metadata.id` in YAML |
| `title` | TEXT | NO | |
| `difficulty` | TEXT | NO | CHECK(`easy`/`medium`/`hard`) |
| `is_free` | INTEGER | NO | CHECK(0,1) |
| `rive_character` | TEXT | NO | |
| `base_prompt` | TEXT | NO | |
| `checkpoints` | TEXT | NO | JSON array |
| `briefing` | TEXT | NO | JSON object `{vocabulary, context, expect}` |
| `exit_lines` | TEXT | NO | JSON object `{hangup, completion}` |
| `language_focus` | TEXT | NO | JSON array of strings |
| `content_warning` | TEXT | YES | nullable |
| `patience_start` | INTEGER | YES | override; preset default if NULL |
| `fail_penalty` | INTEGER | YES | override |
| `silence_penalty` | INTEGER | YES | override |
| `recovery_bonus` | INTEGER | YES | override |
| `silence_prompt_seconds` | INTEGER | YES | override |
| `silence_hangup_seconds` | INTEGER | YES | override |
| `escalation_thresholds` | TEXT | YES | JSON array `[60,30,0]`; NULL = preset |
| `tts_voice_id` | TEXT | YES | |
| `tts_speed` | REAL | YES | |
| `scoring_model` | TEXT | YES | |

Architecture.md:247 table cell should be updated post-acceptance to reflect the renamed `briefing`, the added `exit_lines`, and the typed `language_focus` / `tts_speed` / `scoring_model` columns.
