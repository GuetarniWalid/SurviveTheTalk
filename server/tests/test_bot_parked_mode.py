"""Story 6.26 — `bot.apply_parked_job` (warm-pool job parsing).

The pure helper a parked bot runs when it receives its one stdin job line:
JSON-parse `{"url","room","token","env":{...}}`, apply the per-call env to
`os.environ` (so `run_bot` — which reads `os.environ.get(...)` at call time —
behaves identically to a cold spawn), and return the connection args. These
tests cover ONLY that pure parsing/env-application step — the actual pipeline
run is integration/smoke territory.

`patch.dict(os.environ, {}, clear=False)` snapshots+restores `os.environ`, so any
keys the helper sets are rolled back at block exit (no cross-test leakage).
"""

import os
from unittest.mock import patch

import pytest

from pipeline.bot import apply_parked_job


def test_apply_parked_job_returns_connection_args_and_sets_env() -> None:
    line = (
        '{"url": "wss://lk", "room": "call-1", "token": "agent-tok", '
        '"env": {"SYSTEM_PROMPT": "be Tina", "SCENARIO_CHARACTER": "waiter", '
        '"SCENARIO_ID": "waiter_easy_01", "CALL_ID": "42", '
        '"SCENARIO_DIFFICULTY": "hard"}}'
    )
    with patch.dict(os.environ, {}, clear=False):
        url, room, token = apply_parked_job(line)
        assert (url, room, token) == ("wss://lk", "call-1", "agent-tok")
        assert os.environ["SYSTEM_PROMPT"] == "be Tina"
        assert os.environ["SCENARIO_CHARACTER"] == "waiter"
        assert os.environ["SCENARIO_ID"] == "waiter_easy_01"
        assert os.environ["CALL_ID"] == "42"
        assert os.environ["SCENARIO_DIFFICULTY"] == "hard"


def test_apply_parked_job_omits_absent_difficulty() -> None:
    """AC7 parity with the cold path — an absent SCENARIO_DIFFICULTY is NOT set
    (the bot's loaders then resolve to the server default
    `scenarios.DEFAULT_DIFFICULTY` — Story 6.28); it must never leak as the
    literal string "None"."""
    line = (
        '{"url": "wss://lk", "room": "call-2", "token": "tok", '
        '"env": {"SCENARIO_ID": "waiter_easy_01"}}'
    )
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SCENARIO_DIFFICULTY", None)
        apply_parked_job(line)
        assert "SCENARIO_DIFFICULTY" not in os.environ


def test_apply_parked_job_skips_none_valued_env_keys() -> None:
    """A null in the job env (defensive) is skipped, not stringified to "None"."""
    line = (
        '{"url": "u", "room": "r", "token": "t", '
        '"env": {"SCENARIO_ID": "s", "SCENARIO_DIFFICULTY": null}}'
    )
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SCENARIO_DIFFICULTY", None)
        apply_parked_job(line)
        assert "SCENARIO_DIFFICULTY" not in os.environ
        assert os.environ["SCENARIO_ID"] == "s"


def test_apply_parked_job_ignores_non_whitelisted_env_keys() -> None:
    """A parked job can only set the whitelisted per-call keys — it must NOT be
    able to rewrite arbitrary process env (e.g. GROQ_API_KEY)."""
    line = (
        '{"url": "u", "room": "r", "token": "t", '
        '"env": {"GROQ_API_KEY": "evil", "SCENARIO_ID": "s"}}'
    )
    with patch.dict(os.environ, {"GROQ_API_KEY": "real-key"}, clear=False):
        apply_parked_job(line)
        assert os.environ["GROQ_API_KEY"] == "real-key"  # untouched


def test_apply_parked_job_missing_connection_key_raises() -> None:
    for bad in (
        '{"room": "r", "token": "t"}',  # no url
        '{"url": "u", "token": "t"}',  # no room
        '{"url": "u", "room": "r"}',  # no token
    ):
        with patch.dict(os.environ, {}, clear=False):
            with pytest.raises(ValueError, match="missing required connection key"):
                apply_parked_job(bad)


def test_apply_parked_job_bad_json_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        with pytest.raises(ValueError, match="not valid JSON"):
            apply_parked_job("this is not json")


def test_apply_parked_job_non_object_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        with pytest.raises(ValueError, match="must be a JSON object"):
            apply_parked_job('["a", "list"]')


def test_apply_parked_job_bad_env_type_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        with pytest.raises(ValueError, match="'env' must be a JSON object"):
            apply_parked_job('{"url": "u", "room": "r", "token": "t", "env": "nope"}')
