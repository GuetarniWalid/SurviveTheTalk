-- 004_scenarios_and_user_progress.sql
-- Story 5.1. Canonical column list per ADR 001 (scenarios) + user_progress
-- (progression tracking, write path lands in Story 6.4 / 7.1).

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK(difficulty IN ('easy','medium','hard')),
    is_free INTEGER NOT NULL CHECK(is_free IN (0,1)),
    rive_character TEXT NOT NULL,
    base_prompt TEXT NOT NULL,
    checkpoints TEXT NOT NULL,          -- JSON array
    briefing TEXT NOT NULL,             -- JSON object {vocabulary, context, expect}
    exit_lines TEXT NOT NULL,           -- JSON object {hangup, completion}
    language_focus TEXT NOT NULL,       -- JSON array of strings
    content_warning TEXT,               -- nullable
    patience_start INTEGER,
    fail_penalty INTEGER,
    silence_penalty INTEGER,
    recovery_bonus INTEGER,
    silence_prompt_seconds INTEGER,
    silence_hangup_seconds INTEGER,
    escalation_thresholds TEXT,         -- JSON array, nullable
    tts_voice_id TEXT,
    tts_speed REAL,
    scoring_model TEXT
);

CREATE TABLE IF NOT EXISTS user_progress (
    user_id INTEGER NOT NULL REFERENCES users(id),
    scenario_id TEXT NOT NULL REFERENCES scenarios(id),
    best_score INTEGER CHECK(best_score IS NULL OR (best_score BETWEEN 0 AND 100)),
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, scenario_id)
);
CREATE INDEX IF NOT EXISTS idx_user_progress_user_id ON user_progress(user_id);
