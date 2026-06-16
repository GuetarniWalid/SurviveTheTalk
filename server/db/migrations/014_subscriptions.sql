-- 014_subscriptions.sql
-- Story 8.1 — Integrate StoreKit 2 and Google Play Billing (Epic 8 opener).
--
-- Two schema changes, both ADD-only (no table rebuild), so the migration
-- replays cleanly against `tests/fixtures/prod_snapshot.sqlite` (existing
-- rows pre-date every new column and take NULL / the new empty table is
-- never touched by them). Same safe `ALTER TABLE ADD COLUMN` posture as
-- 008/009/010/011 — every added column is nullable, so SQLite backfills
-- existing rows with NULL without touching them. No `PRAGMA foreign_keys`
-- toggle needed (nothing is rebuilt; the new FK is on a fresh table).
--
--   1. `users.tier_changed_at` — ISO-8601 UTC timestamp stamped on EVERY
--      tier flip (free<->paid). Decision D3: added now so we don't need a
--      second migration in Story 8.3, which owns the free-tier lifetime
--      call-count rework (deferred-work.md:401-403). 8.1 only stamps it;
--      the counting fix is 8.3's. Nullable — legacy users pre-date any flip.
--
--   2. `purchases` — one row per verify attempt; the audit trail behind the
--      tier flip. `verification_token` stores a STORE VERIFICATION ARTIFACT
--      (iOS: the StoreKit 2 signed-transaction JWS; Android: the Google
--      `purchaseToken`) — NOT a card number, NOT a payment token, NOT any
--      cardholder data (NFR11 — zero PCI-DSS scope). `validation_status`
--      tracks the D2 validate-then-flip lifecycle: 'pending' on insert,
--      'valid' once Apple/Google confirm, 'invalid' on a definitive reject.

ALTER TABLE users ADD COLUMN tier_changed_at TEXT;

CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform TEXT NOT NULL CHECK(platform IN ('ios','android')),
    product_id TEXT NOT NULL,
    verification_token TEXT NOT NULL,     -- JWS (iOS) / purchaseToken (Android); a store artifact, NOT payment data (NFR11)
    transaction_id TEXT,                  -- Apple transactionId / Google orderId, once known
    validation_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(validation_status IN ('pending','valid','invalid')),
    expires_at TEXT,                      -- subscription expiry from the validation response
    created_at TEXT NOT NULL,
    validated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id);
