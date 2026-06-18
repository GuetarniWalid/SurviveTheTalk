-- 015_tier_at_call_and_subscription_events.sql
-- Story 8.3 — Subscription Management and Full Tier Enforcement.
--
-- Two schema changes, both ADD-only (no table rebuild), so the migration
-- replays cleanly against `tests/fixtures/prod_snapshot.sqlite` — every
-- existing call_sessions row pre-dates the new column and takes NULL, and the
-- new subscription_events table is empty + never referenced by old rows. Same
-- safe `ALTER TABLE ADD COLUMN` / `CREATE TABLE IF NOT EXISTS` posture as
-- 008/011/012/014 — no `PRAGMA foreign_keys` toggle is needed (nothing is
-- rebuilt; the added column is nullable, SQLite backfills NULL without
-- touching rows).
--
--   1. `call_sessions.tier_at_call` — the user's tier STAMPED at call-initiate
--      time (D2). The free lifetime cap counts only calls made WHILE free, so a
--      churned paid->free user "returns where they were" (used 2 free before
--      paying -> 1 left after cancel) — a single `tier_changed_at` timestamp
--      cannot reconstruct multi-transition history, a per-call stamp can.
--      Nullable, no default: LEGACY rows stay NULL and are treated as 'free'
--      via `COALESCE(tier_at_call,'free')` in the count (prod history is
--      effectively all free-era — a documented assumption). The CHECK allows
--      NULL so existing rows satisfy it without a backfill.
--
--   2. `subscription_events` — the webhook idempotency / audit ledger (D3).
--      One row per received store lifecycle notification. `notification_id` is
--      Apple's `notificationUUID` / Google Pub/Sub's `messageId`; the UNIQUE
--      constraint makes a replayed notification a no-op (insert-or-skip), the
--      structural guarantee behind "return 200 quickly + idempotent" (Apple &
--      Pub/Sub retry on non-2xx). `processed_at` is NULL until the handler
--      finishes acting on the event.

ALTER TABLE call_sessions ADD COLUMN tier_at_call TEXT
    CHECK(tier_at_call IS NULL OR tier_at_call IN ('free','paid'));

CREATE TABLE IF NOT EXISTS subscription_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK(provider IN ('apple','google')),
    notification_id TEXT NOT NULL UNIQUE,  -- Apple notificationUUID / Google Pub/Sub messageId; UNIQUE = replay no-op.
    notification_type TEXT,
    received_at TEXT NOT NULL,
    processed_at TEXT
);
