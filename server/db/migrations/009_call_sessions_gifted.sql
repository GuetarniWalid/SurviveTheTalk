-- Story 6.5 Déviation #27 — "free gifts" anti-frustration system.
--
-- When `/calls/{id}/end` fires with a reason that is not the user's
-- explicit choice (network drop, character hung up after silence,
-- inappropriate-content cut) AND specific eligibility conditions are
-- met, the row is gifted: status flips to 'failed' (excluded from the
-- daily cap counter via the existing status filter) AND the new
-- `gifted` column flags the row so the per-day-3 quota query can count
-- gifts independently of `'failed'` rows from other paths (e.g. Popen
-- rollback, janitor sweep).
--
-- See routes_calls.end_call() for the gift eligibility rules.

ALTER TABLE call_sessions
    ADD COLUMN gifted INTEGER NOT NULL DEFAULT 0 CHECK (gifted IN (0, 1));
