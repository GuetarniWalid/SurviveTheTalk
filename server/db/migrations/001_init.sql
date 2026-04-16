CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- `email` uses `COLLATE NOCASE` because our route layer lower-cases input
-- defensively but the UNIQUE constraint must still reject mixed-case
-- duplicates produced by any future code path that skips normalisation.
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    jwt_hash TEXT,
    tier TEXT NOT NULL DEFAULT 'free' CHECK(tier IN ('free','full')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS auth_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL COLLATE NOCASE,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0 CHECK(used IN (0, 1))
);
-- Composite index matches the predicate used by `claim_active_code` and
-- `fetch_active_code` (email + code + used=0) so both queries hit an index
-- scan even when the `auth_codes` table grows.
CREATE INDEX IF NOT EXISTS idx_auth_codes_email_code_used
    ON auth_codes(email, code, used);
