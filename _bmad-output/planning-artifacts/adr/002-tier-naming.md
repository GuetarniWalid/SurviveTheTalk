# ADR 002 — Tier Naming: `free` / `paid` Canonical

**Status:** Accepted
**Date:** 2026-04-23
**Deciders:** Winston (Architect), Walid (Project Lead)
**Blocks resolved:** Story 5.3 (BottomOverlayCard + daily call limit enforcement)

---

## Context

Naming drift between layers:

- `server/db/migrations/001_init.sql:13` — `CHECK(tier IN ('free','full'))`
- `_bmad-output/planning-artifacts/prd.md`, `epics.md`, `architecture.md` — consistently use `free` / `paid` (≥ 20 occurrences across FR20, FR21, FR28–31, NFR26, Epic 8 story ACs, UX-DR5, UX-DR16).
- Flutter client — no tier code exists yet (lands in Story 5.3).
- Python server code (`server/db/queries.py`, tests) — only references the `'free'` literal; no `'full'` ever written in practice. Production VPS DB has zero rows with `tier='full'`.

Story 5.3 will add tier branching on the client (BottomOverlayCard states) and server (call-limit enforcement: free = 3 lifetime, paid = 3/day). The divergence must be frozen before the first tier-aware code is written.

---

## Decision

**Canonical tier value for `paid` users = `'paid'`.** `'full'` is a legacy naming from the PoC migration and is retired.

Enum (both DB CHECK and application code): `('free', 'paid')`.

---

## Rationale

- PRD / epics / architecture / UX spec all use `paid` — the documentation side has zero `full` references. Aligning the DB to the docs costs one migration; aligning the docs to the DB would cost ~20 surgical edits across 4 canonical documents and dozens of story ACs.
- No production row has `tier='full'` (only insert path in `queries.py:40` hard-codes `'free'`). Migration is schema-only, zero data rewrite needed.
- Stripe/IAP vocabulary standardly pairs `free` with `paid` (not `full`). Future subscription tier work (Epic 8) reads more naturally.

---

## Consequences

**Positive**
- Zero semantic drift between server code, DB, and specs going into Story 5.3.
- Flutter tier enum can be named directly off the DB string (`Tier.free`, `Tier.paid`).

**Negative / trade-offs**
- Requires a new migration using the SQLite table-rebuild pattern (SQLite ≤ 3.35 cannot `ALTER` a `CHECK` constraint).
- The VPS must run the migration on next deploy before any `'paid'` write attempt lands.

---

## Files to change

### Migrations (required — new file)

- **`server/db/migrations/003_tier_rename_full_to_paid.sql`** — new migration. SQLite table-rebuild idiom in a single transaction:
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
  **Do not modify `001_init.sql` in place** — migrations are immutable once applied.

### Files already consistent (no change needed)

- `server/db/queries.py` — only writes `'free'`; no `'full'` literal.
- `server/tests/test_auth.py`, `server/tests/test_middleware.py` — use `'free'` only.
- `_bmad-output/planning-artifacts/architecture.md:245` — table cell already reads "tier (free/paid)" ✓.
- `_bmad-output/planning-artifacts/architecture.md:523` — example JSON already `"tier": "free"` ✓.
- `_bmad-output/planning-artifacts/epics.md`, `prd.md`, `ux-design-specification.md` — no change.
- Flutter client — no tier code yet.

### Forward work (Story 5.3 onwards — informational, not an "apply now" change)

- `client/lib/features/.../user_tier.dart` (or equivalent) — Dart enum `{ free, paid }` with JSON deserialization aligned to the string literals.
- `server/routes/...` call-limit enforcement branch: `if user.tier == "paid": ...`.
- `GET /user/profile` response payload: `{"data": {"tier": "paid" | "free", ...}}`.

### Smoke test for the 003 migration (fits the AI-B template section of ADR linked work)

On VPS after deploy:
```bash
sqlite3 /path/to/app.db "SELECT sql FROM sqlite_schema WHERE name='users';"
# Expected: the CREATE TABLE text contains: CHECK(tier IN ('free','paid'))
sqlite3 /path/to/app.db "SELECT version FROM schema_migrations ORDER BY version;"
# Expected: 003 present alongside 001, 002
```
