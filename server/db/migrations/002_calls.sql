-- Call sessions: one row per initiated voice call. Created by
-- POST /calls/initiate and, in a future story, terminated by
-- POST /calls/{id}/end which will fill in duration_sec + cost_cents.
--
-- `scenario_id` is TEXT with no FK on purpose: the scenarios table
-- arrives in Story 5.1. Storing the string keeps the column forward
-- compatible — a later migration can add the FK constraint.
CREATE TABLE IF NOT EXISTS call_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    scenario_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_sec INTEGER,
    cost_cents INTEGER
);
CREATE INDEX IF NOT EXISTS idx_call_sessions_user_id ON call_sessions(user_id);
