-- 003_tier_rename_full_to_paid.sql
-- Rename CHECK(tier IN ('free','full')) → CHECK(tier IN ('free','paid')).
-- No rows with tier='full' exist in production; this migration is schema-only.
--
-- The SQLite table-rebuild idiom MUST disable foreign_keys for the duration
-- of the DROP/RENAME — otherwise call_sessions(user_id) → users(id)
-- triggers a FOREIGN KEY constraint violation on DROP TABLE users.
-- PRAGMA foreign_keys can only be toggled OUTSIDE an active transaction,
-- so the OFF/ON statements sit before BEGIN and after COMMIT respectively.
-- Reference: https://www.sqlite.org/lang_altertable.html §"Making Other Kinds Of Table Schema Changes"
PRAGMA foreign_keys = OFF;
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
PRAGMA foreign_keys = ON;
