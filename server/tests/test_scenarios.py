"""Tests for the /scenarios endpoints (Story 5.1)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from tests.conftest import register_user as _register_user


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_requires_jwt(client):
    """No Authorization header → 401 AUTH_UNAUTHORIZED."""
    response = client.get("/scenarios")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_detail_requires_jwt(client):
    """No Authorization header → 401 AUTH_UNAUTHORIZED."""
    response = client.get("/scenarios/waiter_easy_01")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


# Story 6.16/6.17 — the catalog grows as scenarios are generated, so these tests
# read the expected set/order from the YAML files (source of truth) instead of
# hard-coding "5". The 5 originals must always be present.
_ORIGINAL_IDS = {
    "waiter_easy_01",
    "mugger_medium_01",
    "girlfriend_medium_01",
    "cop_hard_01",
    "landlord_hard_01",
}


def _yaml_scenarios() -> dict:
    """{id: {difficulty, is_free}} read straight from pipeline/scenarios/*.yaml."""
    import pathlib

    import yaml

    d = pathlib.Path(__file__).resolve().parent.parent / "pipeline" / "scenarios"
    out: dict = {}
    for p in sorted(d.glob("*.yaml")):
        meta = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get(
            "metadata"
        ) or {}
        out[meta["id"]] = {
            "difficulty": meta["difficulty"],
            "is_free": bool(meta.get("is_free")),
        }
    return out


def _expected_order(scn: dict) -> list:
    """The list ordering contract: difficulty bucket (easy<medium<hard), then id ASC."""
    rank = {"easy": 0, "medium": 1, "hard": 2}
    return sorted(scn, key=lambda i: (rank[scn[i]["difficulty"]], i))


def test_list_returns_all_scenarios_ordered(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Authenticated GET /scenarios returns every catalog scenario in order.

    Order contract (AC4): easy bucket first, then medium, then hard; inside each
    bucket, `id` ASC. Computed from the YAML catalog so it survives new scenarios.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios", headers=_auth_header(token))

    assert response.status_code == 200
    body = response.json()
    scn = _yaml_scenarios()
    assert body["meta"]["count"] == len(scn)
    ids = [item["id"] for item in body["data"]]
    assert ids == _expected_order(scn)
    assert _ORIGINAL_IDS.issubset(set(ids))


def test_list_shape_includes_progression_fields(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Each item has progression fields with expected types for a fresh user."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios", headers=_auth_header(token))
    items = response.json()["data"]

    for item in items:
        assert item["best_score"] is None
        assert item["attempts"] == 0
        assert isinstance(item["is_free"], bool)
        assert isinstance(item["language_focus"], list)
        # `content_warning` is either null or a string — never missing.
        assert "content_warning" in item


def test_list_items_carry_end_phrases(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Story 7.2 AC-S2/AC-S3 — `end_phrases` round-trips YAML → DB →
    `ScenarioListItem`. Every shipped YAML carries the block, so every list
    item must expose a dict with the 3 non-empty string variants the Call
    Ended overlay picks from.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    items = client.get("/scenarios", headers=_auth_header(token)).json()["data"]

    assert len(items) > 0
    for item in items:
        phrases = item["end_phrases"]
        assert isinstance(phrases, dict), f"{item['id']}: end_phrases={phrases!r}"
        assert {"hung_up", "voluntary", "survived"} <= phrases.keys(), (
            f"{item['id']}: missing variant in {phrases!r}"
        )
        for variant in ("hung_up", "voluntary", "survived"):
            assert isinstance(phrases[variant], str) and phrases[variant].strip(), (
                f"{item['id']}: empty end_phrases.{variant}"
            )


def test_list_end_phrases_matches_yaml_authoring(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Story 7.2 AC-S2 — the seeded waiter phrases are byte-identical to the
    Walid-approved YAML copy (catches a seeder serialization drift)."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    items = client.get("/scenarios", headers=_auth_header(token)).json()["data"]
    waiter = next(item for item in items if item["id"] == "waiter_easy_01")

    assert waiter["end_phrases"] == {
        "hung_up": "The waitress kicked you out",
        "voluntary": "You walked out",
        "survived": "You actually got your food",
    }


def test_list_returns_500_on_corrupt_end_phrases_json(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Story 7.2 AC-S4 — corrupt `end_phrases` JSON → 500 SCENARIO_CORRUPT.

    Unlike the 5 detail-route JSON columns covered by the parametrized test
    below, `end_phrases` is decoded by the LIST route only (`get_scenario`
    deliberately leaves it unset on the detail payload), so the corruption
    probe must hit `GET /scenarios`.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE scenarios SET end_phrases = ? WHERE id = ?",
        ("not-valid-json{", "waiter_easy_01"),
    )
    conn.commit()
    conn.close()

    response = client.get("/scenarios", headers=_auth_header(token))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SCENARIO_CORRUPT"


def test_list_includes_free_and_paid_mix(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """The list has BOTH free and paid scenarios, in the proportions the YAML
    catalog declares (originals: 3 free + 2 paid; generated paid scenarios add to
    the paid side)."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    items = client.get("/scenarios", headers=_auth_header(token)).json()["data"]

    scn = _yaml_scenarios()
    free_expected = sum(1 for v in scn.values() if v["is_free"])
    paid_expected = len(scn) - free_expected
    free_count = sum(1 for item in items if item["is_free"])
    paid_count = sum(1 for item in items if not item["is_free"])
    assert free_count == free_expected
    assert paid_count == paid_expected
    assert free_count > 0 and paid_count > 0  # a genuine mix


def test_detail_returns_full_shape(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """GET /scenarios/waiter_easy_01 returns the full authoring body."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios/waiter_easy_01", headers=_auth_header(token))

    assert response.status_code == 200
    data = response.json()["data"]

    briefing = data["briefing"]
    assert isinstance(briefing, dict)
    assert {"vocabulary", "context", "expect"}.issubset(briefing.keys())

    exit_lines = data["exit_lines"]
    assert {"hangup", "completion"}.issubset(exit_lines.keys())

    checkpoints = data["checkpoints"]
    assert isinstance(checkpoints, list)
    assert len(checkpoints) > 0

    assert "Tina" in data["base_prompt"]
    assert data["content_warning"] is None


def test_detail_returns_404_on_unknown_id(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Unknown scenario id → 404 SCENARIO_NOT_FOUND."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios/nonexistent_id", headers=_auth_header(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCENARIO_NOT_FOUND"


def test_list_reflects_user_progress(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """A user_progress row surfaces in the list endpoint via LEFT JOIN."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "INSERT INTO user_progress(user_id, scenario_id, best_score, "
        "attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            user_id,
            "waiter_easy_01",
            75,
            2,
            "2026-04-24T10:05:00Z",
            "2026-04-24T10:05:00Z",
        ),
    )
    conn.commit()
    conn.close()

    items = client.get("/scenarios", headers=_auth_header(token)).json()["data"]
    by_id = {item["id"]: item for item in items}

    waiter = by_id["waiter_easy_01"]
    assert waiter["best_score"] == 75
    assert waiter["attempts"] == 2

    mugger = by_id["mugger_medium_01"]
    assert mugger["best_score"] is None
    assert mugger["attempts"] == 0


@pytest.mark.parametrize(
    "column",
    [
        "briefing",
        "exit_lines",
        "checkpoints",
        "language_focus",
        "escalation_thresholds",
    ],
)
def test_detail_returns_500_on_corrupt_json_column(
    client: TestClient, mock_resend, test_db_path: str, column: str
) -> None:
    """Manual DB corruption of any JSON-in-TEXT column → 500 SCENARIO_CORRUPT.

    Covers all 5 JSON-in-TEXT columns on the scenarios table. Schema enforces
    NOT NULL on 4 of them (escalation_thresholds is nullable, but a corrupt
    non-null value must still fail loud). The handler MUST surface
    SCENARIO_CORRUPT, not FastAPI's default 500.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        f"UPDATE scenarios SET {column} = ? WHERE id = ?",
        ("not-valid-json{", "waiter_easy_01"),
    )
    conn.commit()
    conn.close()

    response = client.get("/scenarios/waiter_easy_01", headers=_auth_header(token))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SCENARIO_CORRUPT"


def test_detail_returns_500_on_shape_mismatch_json_column(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Valid JSON of the wrong Pydantic shape → 500 SCENARIO_CORRUPT.

    `_safe_json_load` only catches parse errors. When a JSON-in-TEXT column
    holds *valid* JSON that violates the Pydantic schema (e.g. briefing is a
    list instead of a dict), the route must still surface SCENARIO_CORRUPT
    instead of leaking a generic FastAPI 500.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    # `briefing` must be an object per ADR 001 — we store a list instead.
    conn.execute(
        "UPDATE scenarios SET briefing = ? WHERE id = ?",
        ('["wrong", "shape"]', "waiter_easy_01"),
    )
    conn.commit()
    conn.close()

    response = client.get("/scenarios/waiter_easy_01", headers=_auth_header(token))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SCENARIO_CORRUPT"


def test_envelope_shape(client: TestClient, mock_resend, test_db_path: str) -> None:
    """The list envelope carries `data` + `meta.count` + ISO-Z `meta.timestamp`.

    Story 5.3 widened `meta` with the call-usage policy block — the four
    `tier` / `calls_remaining` / `calls_per_period` / `period` keys are
    asserted present here so a future regression that drops the fold-in
    fails this test instead of slipping past the dedicated usage tests.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    body = client.get("/scenarios", headers=_auth_header(token)).json()

    assert "data" in body
    assert "meta" in body
    assert isinstance(body["meta"]["count"], int)
    assert body["meta"]["timestamp"].endswith("Z")
    # Story 5.3 — call-usage policy folded into meta.
    for key in ("tier", "calls_remaining", "calls_per_period", "period"):
        assert key in body["meta"], f"missing meta.{key} (Story 5.3)"


def test_meta_includes_usage_for_free_user(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Fresh free user → meta.tier='free', period='lifetime', remaining=3, cap=3."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    body = client.get("/scenarios", headers=_auth_header(token)).json()

    assert body["meta"]["tier"] == "free"
    assert body["meta"]["period"] == "lifetime"
    assert body["meta"]["calls_remaining"] == 3
    assert body["meta"]["calls_per_period"] == 3


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token")
@patch("api.routes_calls.generate_token", return_value="user-token")
def test_meta_calls_remaining_decrements_after_initiate(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """One successful /calls/initiate → meta.calls_remaining drops 3 → 2."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    init = client.post(
        "/calls/initiate",
        json={"scenario_id": "waiter_easy_01"},
        headers=_auth_header(token),
    )
    assert init.status_code == 200

    body = client.get("/scenarios", headers=_auth_header(token)).json()
    assert body["meta"]["calls_remaining"] == 2


def test_meta_period_is_day_for_paid_user(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Promoting tier to 'paid' flips period='day' and resets remaining=3 (no sessions today)."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    conn.execute("UPDATE users SET tier = 'paid' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    body = client.get("/scenarios", headers=_auth_header(token)).json()
    assert body["meta"]["tier"] == "paid"
    assert body["meta"]["period"] == "day"
    # No call_sessions exist for this user today → cap untouched.
    assert body["meta"]["calls_remaining"] == 3


def test_meta_count_and_timestamp_still_present(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Regression guard: pre-5.3 keys (`count`, `timestamp`) survive the meta widening."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    meta = client.get("/scenarios", headers=_auth_header(token)).json()["meta"]

    assert meta["count"] == len(_yaml_scenarios())
    assert meta["timestamp"].endswith("Z")


# ---------- Story 6.3 — load_scenario_metadata helper ----------


def test_load_scenario_metadata_returns_rive_character() -> None:
    """`load_scenario_metadata("waiter_easy_01")` returns a dict whose
    `rive_character` field is `"waiter"` (matches the YAML metadata block).
    """
    from pipeline.scenarios import load_scenario_metadata

    metadata = load_scenario_metadata("waiter_easy_01")
    assert metadata["rive_character"] == "waiter"


def test_load_scenario_metadata_unknown_id_raises() -> None:
    """Unknown scenario ids raise FileNotFoundError (parity with
    `load_scenario_prompt` so the route's existing exception arm at
    `routes_calls.py` surfaces them as the canonical `SCENARIO_LOAD_FAILED`
    envelope).
    """
    from pipeline.scenarios import load_scenario_metadata

    with pytest.raises(FileNotFoundError):
        load_scenario_metadata("does_not_exist")


# ---------- Story 6.4 — resolve_patience_config helper ----------


def test_resolve_patience_config_happy_path_easy() -> None:
    """`waiter_easy_01` (all overrides null, difficulty=easy) resolves
    to the easy preset row plus `total_checkpoints` derived from the
    YAML's checkpoints list.
    """
    from pipeline.scenarios import resolve_patience_config

    config = resolve_patience_config("waiter_easy_01")
    assert config["initial_patience"] == 100
    assert config["fail_penalty"] == -15
    assert config["silence_penalty"] == -10
    assert config["recovery_bonus"] == 5
    assert config["silence_prompt_seconds"] == 6.0
    assert config["silence_hangup_seconds"] == 10.0
    assert config["escalation_thresholds"] == [75, 50, 25, 0]
    # The waiter YAML defines 6 checkpoints (greet → close).
    assert config["total_checkpoints"] == 6


def test_resolve_patience_config_yaml_override_wins(tmp_path, monkeypatch) -> None:
    """A non-null `silence_hangup_seconds` in the YAML overrides the
    preset value.
    """
    from pipeline import scenarios as scenarios_mod

    fake_yaml = tmp_path / "synthetic.yaml"
    fake_yaml.write_text(
        """
metadata:
  id: synthetic_easy_01
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  patience_start: null
  fail_penalty: null
  silence_penalty: null
  recovery_bonus: null
  silence_prompt_seconds: null
  silence_hangup_seconds: 7.0
  escalation_thresholds: null
base_prompt: |
  test
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
  - id: b
    hint_text: b
    prompt_segment: b
    success_criteria: b
""",
        encoding="utf-8",
    )

    patched_index = dict(scenarios_mod._SCENARIO_INDEX)
    patched_index["synthetic_easy_01"] = fake_yaml
    monkeypatch.setattr(scenarios_mod, "_SCENARIO_INDEX", patched_index)

    config = scenarios_mod.resolve_patience_config("synthetic_easy_01")
    assert config["silence_hangup_seconds"] == 7.0
    # Preset wins for un-overridden fields.
    assert config["initial_patience"] == 100
    assert config["total_checkpoints"] == 2


def test_resolve_patience_config_rejects_non_positive_patience_start(
    tmp_path, monkeypatch
) -> None:
    """A YAML `patience_start: 0` override would silently produce a
    survival_pct denominator of zero. The resolver must fail loud at
    config-resolution time so the bug surfaces at process start, not
    on the first hang-up. Defensive against future YAML drift."""
    from pipeline import scenarios as scenarios_mod

    fake_yaml = tmp_path / "synthetic.yaml"
    fake_yaml.write_text(
        """
metadata:
  id: synthetic_zero_01
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  patience_start: 0
  fail_penalty: null
  silence_penalty: null
  recovery_bonus: null
  silence_prompt_seconds: null
  silence_hangup_seconds: null
  escalation_thresholds: null
base_prompt: |
  test
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
""",
        encoding="utf-8",
    )

    patched_index = dict(scenarios_mod._SCENARIO_INDEX)
    patched_index["synthetic_zero_01"] = fake_yaml
    monkeypatch.setattr(scenarios_mod, "_SCENARIO_INDEX", patched_index)

    with pytest.raises(RuntimeError, match="initial_patience"):
        scenarios_mod.resolve_patience_config("synthetic_zero_01")


def test_resolve_patience_config_unknown_difficulty_raises(
    tmp_path, monkeypatch
) -> None:
    """Difficulty outside `easy`/`medium`/`hard` is a fail-loud condition."""
    from pipeline import scenarios as scenarios_mod

    fake_yaml = tmp_path / "synthetic.yaml"
    fake_yaml.write_text(
        """
metadata:
  id: synthetic_trivial_01
  title: Synthetic
  difficulty: trivial
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  test
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
""",
        encoding="utf-8",
    )

    patched_index = dict(scenarios_mod._SCENARIO_INDEX)
    patched_index["synthetic_trivial_01"] = fake_yaml
    monkeypatch.setattr(scenarios_mod, "_SCENARIO_INDEX", patched_index)

    with pytest.raises(RuntimeError, match="trivial"):
        scenarios_mod.resolve_patience_config("synthetic_trivial_01")


# ============================================================
# Story 6.6 — deepcopy + validation + exit_lines + new helpers
# ============================================================


def _write_synthetic_yaml(
    tmp_path,
    monkeypatch,
    yaml_body: str,
    *,
    scenario_id: str,
) -> None:
    """Helper that drops a synthetic YAML into `_SCENARIO_INDEX` for the
    duration of a single test."""
    from pipeline import scenarios as scenarios_mod

    fake_yaml = tmp_path / f"{scenario_id}.yaml"
    fake_yaml.write_text(yaml_body, encoding="utf-8")
    patched_index = dict(scenarios_mod._SCENARIO_INDEX)
    patched_index[scenario_id] = fake_yaml
    monkeypatch.setattr(scenarios_mod, "_SCENARIO_INDEX", patched_index)


_BASE_YAML = """
metadata:
  id: {scenario_id}
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  patience_start: null
  fail_penalty: {fail_penalty}
  silence_penalty: null
  recovery_bonus: {recovery_bonus}
  silence_prompt_seconds: null
  silence_hangup_seconds: {silence_hangup_seconds}
  escalation_thresholds: {escalation_thresholds}
base_prompt: |
  base test prompt
checkpoints:
  - id: a
    hint_text: a-hint
    prompt_segment: a-segment
    success_criteria: a-success
  - id: b
    hint_text: b-hint
    prompt_segment: b-segment
    success_criteria: b-success
exit_lines:
  hangup: "Synth hangup."
  completion: "Synth completion."
"""


def test_resolve_patience_config_uses_deepcopy_so_overrides_dont_mutate_preset() -> (
    None
):
    """Deferred-work line 357 regression net: a downstream mutation of
    `escalation_thresholds` on one returned config MUST NOT corrupt the
    shared preset row that subsequent calls read from. Story 6.6 makes
    multiple `CheckpointManager` instances coexist on a single VPS, so a
    future bug that appends to the list (e.g. as part of a per-call
    rolling-window) would leak globally without this guard."""
    from pipeline.scenarios import _DIFFICULTY_PRESETS, resolve_patience_config

    original_easy = list(_DIFFICULTY_PRESETS["easy"]["escalation_thresholds"])

    config_a = resolve_patience_config("waiter_easy_01")
    config_a["escalation_thresholds"].append(999)

    config_b = resolve_patience_config("waiter_easy_01")
    assert config_b["escalation_thresholds"] == original_easy, (
        "mutating one returned config must not corrupt the preset row"
    )
    # And the preset row itself stays clean.
    assert _DIFFICULTY_PRESETS["easy"]["escalation_thresholds"] == original_easy


def test_resolve_patience_config_validates_fail_penalty_must_be_non_positive(
    tmp_path, monkeypatch
) -> None:
    """A YAML `fail_penalty: 5` would APPLY a positive offset to the
    meter on a failed exchange — the user would get rewarded for failing.
    Fail loud at resolve time."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_bad_fail",
            fail_penalty=5,
            recovery_bonus="null",
            silence_hangup_seconds="null",
            escalation_thresholds="null",
        ),
        scenario_id="synth_bad_fail",
    )
    with pytest.raises(RuntimeError, match="fail_penalty"):
        scenarios_mod.resolve_patience_config("synth_bad_fail")


def test_resolve_patience_config_validates_recovery_bonus_must_be_non_negative(
    tmp_path, monkeypatch
) -> None:
    """A negative `recovery_bonus` would PENALIZE the user on a successful
    exchange — fail loud."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_bad_rec",
            fail_penalty="null",
            recovery_bonus=-1,
            silence_hangup_seconds="null",
            escalation_thresholds="null",
        ),
        scenario_id="synth_bad_rec",
    )
    with pytest.raises(RuntimeError, match="recovery_bonus"):
        scenarios_mod.resolve_patience_config("synth_bad_rec")


def test_resolve_patience_config_validates_escalation_thresholds_must_be_list_of_int(
    tmp_path, monkeypatch
) -> None:
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_bad_thr",
            fail_penalty="null",
            recovery_bonus="null",
            silence_hangup_seconds="null",
            escalation_thresholds='"75,50"',
        ),
        scenario_id="synth_bad_thr",
    )
    with pytest.raises(RuntimeError, match="escalation_thresholds"):
        scenarios_mod.resolve_patience_config("synth_bad_thr")


def test_resolve_patience_config_validates_silence_hangup_seconds_must_be_positive(
    tmp_path, monkeypatch
) -> None:
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_bad_sh",
            fail_penalty="null",
            recovery_bonus="null",
            silence_hangup_seconds=0,
            escalation_thresholds="null",
        ),
        scenario_id="synth_bad_sh",
    )
    with pytest.raises(RuntimeError, match="silence_hangup_seconds"):
        scenarios_mod.resolve_patience_config("synth_bad_sh")


def test_resolve_patience_config_loads_exit_lines_from_yaml(
    tmp_path, monkeypatch
) -> None:
    """`exit_lines.hangup` flows into BOTH `hang_up_line_silence` and
    `hang_up_line_inappropriate` (single source of truth per Deviation #3);
    `exit_lines.completion` flows into `hang_up_line_survived`."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_lines",
            fail_penalty="null",
            recovery_bonus="null",
            silence_hangup_seconds="null",
            escalation_thresholds="null",
        ),
        scenario_id="synth_lines",
    )
    config = scenarios_mod.resolve_patience_config("synth_lines")
    assert config["hang_up_line_silence"] == "Synth hangup."
    assert config["hang_up_line_inappropriate"] == "Synth hangup."
    assert config["hang_up_line_survived"] == "Synth completion."


def test_resolve_patience_config_loads_waiter_exit_lines() -> None:
    """End-to-end against the real `the-waiter.yaml`: the tutorial
    completion line is the documented one."""
    from pipeline.scenarios import resolve_patience_config

    config = resolve_patience_config("waiter_easy_01")
    assert config["hang_up_line_silence"] == "*heavy sigh* I'm done. Next customer."
    assert config["hang_up_line_inappropriate"] == (
        "*heavy sigh* I'm done. Next customer."
    )
    assert config["hang_up_line_survived"] == (
        "Huh. You actually knew what you wanted. That's a first."
    )


def test_resolve_patience_config_loads_patience_warning_line_from_yaml(
    tmp_path, monkeypatch
) -> None:
    """`exit_lines.patience_warning` flows into the `patience_warning_line`
    config key consumed by PatienceTracker (Deviation #6)."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_warning
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "Done."
  completion: "Wow."
  patience_warning: "Custom last-chance line for this scenario."
"""
    _write_synthetic_yaml(tmp_path, monkeypatch, yaml_body, scenario_id="synth_warning")
    config = scenarios_mod.resolve_patience_config("synth_warning")
    assert (
        config["patience_warning_line"] == "Custom last-chance line for this scenario."
    )


def test_resolve_patience_config_patience_warning_falls_back_when_yaml_omits_it(
    tmp_path, monkeypatch
) -> None:
    """A YAML without `exit_lines.patience_warning` falls back to the
    generic default — backward-compat for scenarios that haven't been
    edited yet."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_no_warn
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "Done."
  completion: "Wow."
"""
    _write_synthetic_yaml(tmp_path, monkeypatch, yaml_body, scenario_id="synth_no_warn")
    config = scenarios_mod.resolve_patience_config("synth_no_warn")
    assert "Last chance" in config["patience_warning_line"]


def test_waiter_yaml_loads_patience_warning_line_end_to_end() -> None:
    """The shipping `the-waiter.yaml` carries the scenario-tailored
    warning line (sighs + "wasting my time here")."""
    from pipeline.scenarios import resolve_patience_config

    config = resolve_patience_config("waiter_easy_01")
    assert "wasting my time" in config["patience_warning_line"].lower()


def test_load_scenario_checkpoints_returns_full_ordered_list() -> None:
    """`waiter_easy_01` has 6 checkpoints in order: greet → main_course →
    clarify → drink → confirm → close."""
    from pipeline.scenarios import load_scenario_checkpoints

    checkpoints = load_scenario_checkpoints("waiter_easy_01")
    ids = [c["id"] for c in checkpoints]
    assert ids == ["greet", "main_course", "clarify", "drink", "confirm", "close"]
    # Each entry has the required fields.
    for entry in checkpoints:
        for field in ("id", "hint_text", "prompt_segment", "success_criteria"):
            assert field in entry
            assert isinstance(entry[field], str)
            assert entry[field].strip()


def test_load_scenario_checkpoints_raises_FileNotFoundError_on_unknown_id() -> None:
    from pipeline.scenarios import load_scenario_checkpoints

    with pytest.raises(FileNotFoundError):
        load_scenario_checkpoints("does_not_exist")


def test_load_scenario_checkpoints_rejects_malformed_entry(
    tmp_path, monkeypatch
) -> None:
    """A checkpoint entry missing a required field must raise at load
    time, not silently produce a degenerate prompt at call init."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_malformed
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    # missing success_criteria
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(
        tmp_path, monkeypatch, yaml_body, scenario_id="synth_malformed"
    )
    with pytest.raises(RuntimeError, match="success_criteria"):
        scenarios_mod.load_scenario_checkpoints("synth_malformed")


def test_load_scenario_checkpoints_rejects_duplicate_ids(tmp_path, monkeypatch) -> None:
    """Story 6.10 review patch — duplicate checkpoint ids must raise at
    load time. The goal-tracking engine keys state by id
    (`CheckpointManager._goals` / `_id_to_index`); a duplicate silently
    collapses two goals into one map entry while `len(checkpoints)` counts
    both, so the client HUD `metCount` can never reach `total`."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_dup
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  base
checkpoints:
  - id: greet
    hint_text: a
    prompt_segment: a
    success_criteria: a
  - id: greet
    hint_text: b
    prompt_segment: b
    success_criteria: b
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(tmp_path, monkeypatch, yaml_body, scenario_id="synth_dup")
    with pytest.raises(RuntimeError, match="duplicate checkpoint id"):
        scenarios_mod.load_scenario_checkpoints("synth_dup")


# ---------- Story 6.23 — `requires` reactive-gating edge validation ----------


def _requires_yaml(*, requires_value: str) -> str:
    """A 2-checkpoint synthetic YAML where the 2nd beat carries `requires`."""
    return f"""
metadata:
  id: synth_req
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  base
checkpoints:
  - id: first
    hint_text: a
    prompt_segment: a
    success_criteria: a
  - id: second
    requires: {requires_value}
    hint_text: b
    prompt_segment: b
    success_criteria: b
exit_lines:
  hangup: "h"
  completion: "c"
"""


def test_load_scenario_checkpoints_accepts_valid_requires_edge(
    tmp_path, monkeypatch
) -> None:
    """A `requires` pointing at an existing, earlier checkpoint loads cleanly and
    the edge is preserved on the returned dict (it reaches the runtime)."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _requires_yaml(requires_value="first"),
        scenario_id="synth_req",
    )
    checkpoints = scenarios_mod.load_scenario_checkpoints("synth_req")
    assert checkpoints[1]["requires"] == "first"


def test_load_scenario_checkpoints_rejects_requires_unknown_id(
    tmp_path, monkeypatch
) -> None:
    """A `requires` pointing at a non-existent checkpoint id raises at load."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _requires_yaml(requires_value="nope"),
        scenario_id="synth_req",
    )
    with pytest.raises(RuntimeError, match="unknown checkpoint id"):
        scenarios_mod.load_scenario_checkpoints("synth_req")


def test_load_scenario_checkpoints_rejects_requires_self_reference(
    tmp_path, monkeypatch
) -> None:
    """A `requires` pointing at the beat itself (or any later beat) raises —
    a reactive beat can only depend on an EARLIER one (acyclic by construction)."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _requires_yaml(requires_value="second"),
        scenario_id="synth_req",
    )
    with pytest.raises(RuntimeError, match="must reference an EARLIER checkpoint"):
        scenarios_mod.load_scenario_checkpoints("synth_req")


def test_cop_scenario_requires_edges_load() -> None:
    """The shipped cop scenario's 7 reactive edges all validate (existence +
    earlier-order) — guards the Story 6.23 T4 data migration against drift."""
    from pipeline.scenarios import load_scenario_checkpoints

    checkpoints = load_scenario_checkpoints("cop_interrogation_01")
    by_id = {c["id"]: c for c in checkpoints}
    expected = {
        "correct_misquoted_time": "lock_arrival_and_departure",
        "address_named_associate": "deny_knowing_crew",
        "explain_prints_on_inside_handle": "react_to_fingerprint_accusation",
        "elaborate_through_silence": "explain_prints_on_inside_handle",
        "reconcile_cctv_timestamp": "deny_grey_hood_witness",
        "hold_consistency_on_recall": "name_who_was_with_them",
        "answer_biggest_hole": "reconcile_cctv_timestamp",
    }
    for beat, trigger in expected.items():
        assert by_id[beat]["requires"] == trigger


def test_load_scenario_base_prompt_does_not_include_SPEAK_FIRST_directive() -> None:
    """The CheckpointManager composes the live system message from
    `base_prompt + checkpoint.prompt_segment` after every advance. The
    `_SPEAK_FIRST_DIRECTIVE` ("You will speak first when the call
    begins…") applies ONLY to the very first turn — re-injecting it on
    checkpoint 2+ would corrupt the system prompt."""
    from pipeline.scenarios import (
        _SPEAK_FIRST_DIRECTIVE,
        load_scenario_base_prompt,
    )

    base = load_scenario_base_prompt("waiter_easy_01")
    assert _SPEAK_FIRST_DIRECTIVE.strip() not in base
    assert "speak first" not in base.lower()
    # And it IS the rstrip'd base prompt — should mention "Tina".
    assert "Tina" in base


def test_load_scenario_base_prompt_raises_FileNotFoundError_on_unknown_id() -> None:
    from pipeline.scenarios import load_scenario_base_prompt

    with pytest.raises(FileNotFoundError):
        load_scenario_base_prompt("does_not_exist")


# ============================================================
# Story 6.6 review patches — defensive validators added 2026-05-18
# ============================================================


def test_resolve_patience_config_rejects_fail_penalty_bool(
    tmp_path, monkeypatch
) -> None:
    """`isinstance(False, int)` is True in Python — without the explicit
    bool check, a YAML `fail_penalty: false` would silently be accepted
    as `0` (the warning band would never trigger because terminal-turn
    detection requires `patience + fail_penalty <= 0` to advance toward
    0; with fail_penalty=0 it can only fire when meter is already 0,
    short-circuiting the preemptive path)."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_bool_fp",
            fail_penalty="false",
            recovery_bonus="null",
            silence_hangup_seconds="null",
            escalation_thresholds="null",
        ),
        scenario_id="synth_bool_fp",
    )
    with pytest.raises(RuntimeError, match="fail_penalty"):
        scenarios_mod.resolve_patience_config("synth_bool_fp")


def test_resolve_patience_config_rejects_recovery_bonus_bool(
    tmp_path, monkeypatch
) -> None:
    """A YAML `recovery_bonus: true` would silently coerce to `1` —
    forbid bool explicitly to avoid silent type-coercion bugs."""
    from pipeline import scenarios as scenarios_mod

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_bool_rb",
            fail_penalty="null",
            recovery_bonus="true",
            silence_hangup_seconds="null",
            escalation_thresholds="null",
        ),
        scenario_id="synth_bool_rb",
    )
    with pytest.raises(RuntimeError, match="recovery_bonus"):
        scenarios_mod.resolve_patience_config("synth_bool_rb")


def test_resolve_patience_config_rejects_exit_lines_list(tmp_path, monkeypatch) -> None:
    """A YAML `exit_lines: []` (list, not dict) used to slip past the
    type check because `data.get('exit_lines') or {}` falsy-coerced the
    empty list to an empty dict — the malformed-shape error never fired.
    The patched code type-checks the raw value BEFORE the fallback."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_exit_list
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines: []
"""
    _write_synthetic_yaml(
        tmp_path, monkeypatch, yaml_body, scenario_id="synth_exit_list"
    )
    with pytest.raises(RuntimeError, match="exit_lines"):
        scenarios_mod.resolve_patience_config("synth_exit_list")


def test_resolve_patience_config_validates_silence_prompt_seconds_positive(
    tmp_path, monkeypatch
) -> None:
    """A negative or zero `silence_prompt_seconds` would `asyncio.sleep(<=0)`
    and skip ladder stages instantly, silently disabling impatience
    escalation. Reject at resolve time."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_sps_neg
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  silence_prompt_seconds: -1.0
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(tmp_path, monkeypatch, yaml_body, scenario_id="synth_sps_neg")
    with pytest.raises(RuntimeError, match="silence_prompt_seconds"):
        scenarios_mod.resolve_patience_config("synth_sps_neg")


def test_resolve_patience_config_validates_silence_penalty_non_positive(
    tmp_path, monkeypatch
) -> None:
    """`silence_penalty` is added to the meter at ladder stage 4 — must
    be non-positive (or it would REWARD silence). Reject at resolve."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_sp_pos
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  silence_penalty: 5
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(tmp_path, monkeypatch, yaml_body, scenario_id="synth_sp_pos")
    with pytest.raises(RuntimeError, match="silence_penalty"):
        scenarios_mod.resolve_patience_config("synth_sp_pos")


def test_load_scenario_base_prompt_rejects_speak_first_directive(
    tmp_path, monkeypatch
) -> None:
    """A YAML author who pastes the composed prompt (with the speak-first
    directive baked in) into `base_prompt` would otherwise have the bot
    re-deliver the canned opening line on EVERY checkpoint advance.
    Reject at load time so the mistake surfaces at boot, not mid-call."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_speak_first_in_base
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  You are Tina. You will speak first when the call begins.
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(
        tmp_path, monkeypatch, yaml_body, scenario_id="synth_speak_first_in_base"
    )
    with pytest.raises(RuntimeError, match="speak-first directive"):
        scenarios_mod.load_scenario_base_prompt("synth_speak_first_in_base")


# ============================================================
# Story 6.13 AC6 — Waiter clarify success_criteria accepts drink answers
# ============================================================


# ============================================================
# Story 6.13 AC3 — ladder_impatience_seconds per-difficulty preset + validator
# ============================================================


def test_easy_preset_ladder_impatience_seconds_is_4_5() -> None:
    """Story 6.13 AC3 — easy default raised from the deleted 3.0 s
    constant to 4.5 s. Natural response time per smoke gate
    call_id=148 is ~1.5-2.5 s + parse 0.5-1 s; 4.5 s gives the user
    breathing room without feeling abandoned."""
    from pipeline.scenarios import _DIFFICULTY_PRESETS

    assert _DIFFICULTY_PRESETS["easy"]["ladder_impatience_seconds"] == 4.5
    assert _DIFFICULTY_PRESETS["medium"]["ladder_impatience_seconds"] == 3.5
    assert _DIFFICULTY_PRESETS["hard"]["ladder_impatience_seconds"] == 2.5


# ============================================================
# Story 6.19 — global difficulty selector (override + behavior block + tts_speed)
# ============================================================


def test_difficulty_override_swaps_preset_on_resolve_patience_config() -> None:
    """AC3 — a global `hard` pick on the easy-authored waiter resolves to the
    HARD patience preset (not easy), proving the override selects the base
    preset for the call."""
    from pipeline.scenarios import _DIFFICULTY_PRESETS, resolve_patience_config

    hard = _DIFFICULTY_PRESETS["hard"]
    config = resolve_patience_config("waiter_easy_01", difficulty_override="hard")
    assert config["initial_patience"] == hard["initial_patience"] == 60
    assert config["fail_penalty"] == hard["fail_penalty"] == -25
    assert config["escalation_thresholds"] == hard["escalation_thresholds"] == [30, 0]
    assert config["tts_speed"] == hard["tts_speed"] == 1.0


def test_difficulty_override_none_uses_authored_difficulty() -> None:
    """AC7 — no override → the scenario's authored difficulty (easy) is used,
    exactly as before the story."""
    from pipeline.scenarios import resolve_patience_config

    config = resolve_patience_config("waiter_easy_01")
    assert config["initial_patience"] == 100  # easy preset
    assert config["tts_speed"] == 0.9

    config_explicit_none = resolve_patience_config(
        "waiter_easy_01", difficulty_override=None
    )
    assert config_explicit_none["initial_patience"] == 100


def test_resolve_patience_config_rejects_bad_difficulty_override() -> None:
    """A bad override is a fail-loud condition (defensive; the API Literal
    already 422s before this point)."""
    from pipeline.scenarios import resolve_patience_config

    with pytest.raises(RuntimeError, match="difficulty_override"):
        resolve_patience_config("waiter_easy_01", difficulty_override="bogus")


def test_presets_carry_tts_speed_easy_slowed_medium_hard_natural() -> None:
    """Story 6.19 follow-up — speech speed is a narrow band inside natural
    bounds: easy is only gently slowed; medium and hard BOTH sit at the natural
    rate (1.0, the ceiling — never accelerated). Difficulty above easy is carried
    by language/interaction, not by a faster voice."""
    from pipeline.scenarios import _DIFFICULTY_PRESETS

    speeds = {
        k: _DIFFICULTY_PRESETS[k]["tts_speed"] for k in ("easy", "medium", "hard")
    }
    assert speeds == {"easy": 0.9, "medium": 1.0, "hard": 1.0}
    # Easy is slower than medium; hard never exceeds the natural ceiling (== medium).
    assert speeds["easy"] < speeds["medium"] == speeds["hard"]
    assert all(0.6 <= s <= 1.0 for s in speeds.values())


def test_yaml_tts_speed_override_wins_over_preset(tmp_path, monkeypatch) -> None:
    """AC5 — a nullable per-scenario `metadata.tts_speed` overrides the preset
    value (mirrors the other patience overrides)."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_speed
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  tts_speed: 0.95
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(tmp_path, monkeypatch, yaml_body, scenario_id="synth_speed")
    config = scenarios_mod.resolve_patience_config("synth_speed")
    # YAML override (0.95) beats the easy preset (0.9).
    assert config["tts_speed"] == 0.95


def test_resolve_patience_config_rejects_out_of_range_tts_speed(
    tmp_path, monkeypatch
) -> None:
    """Story 6.19 follow-up — natural rate (1.0) is the ceiling: a `tts_speed`
    above 1.0 (here 1.2, the value Walid heard as too fast) now fails loud at
    resolve time. The old cap was 1.5."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_bad_speed
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  tts_speed: 1.2
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(
        tmp_path, monkeypatch, yaml_body, scenario_id="synth_bad_speed"
    )
    with pytest.raises(RuntimeError, match="tts_speed"):
        scenarios_mod.resolve_patience_config("synth_bad_speed")


def test_load_scenario_base_prompt_appends_authored_difficulty_block() -> None:
    """AC4 — the composed base prompt carries the persona AND the authored
    difficulty's behavior block (sourced from the code constant). Asserts on
    rewrite-proof markers (the header + the constant itself), not a hand-picked
    sentence, so future block tightening never breaks this test."""
    from pipeline.scenarios import _DIFFICULTY_PROMPTS, load_scenario_base_prompt

    composed = load_scenario_base_prompt("waiter_easy_01")
    assert "Tina" in composed  # persona preserved
    assert "Difficulty behavior (easy):" in composed
    assert composed.endswith(_DIFFICULTY_PROMPTS["easy"])


def test_load_scenario_base_prompt_override_swaps_behavior_block() -> None:
    """AC4 — a global `hard` pick on the easy waiter makes it SPEAK hard: the
    hard block is composed in place of the easy one. Structural markers only
    (rewrite-proof); the neutrality lint below is the real content guard."""
    from pipeline.scenarios import _DIFFICULTY_PROMPTS, load_scenario_base_prompt

    composed = load_scenario_base_prompt("waiter_easy_01", difficulty_override="hard")
    assert "Difficulty behavior (hard):" in composed
    assert composed.endswith(_DIFFICULTY_PROMPTS["hard"])
    # The easy block must NOT leak through.
    assert "Difficulty behavior (easy):" not in composed


def test_load_scenario_base_prompt_rejects_inline_difficulty_block(
    tmp_path, monkeypatch
) -> None:
    """AC4 — the behavior block lives in `_DIFFICULTY_PROMPTS` now; a YAML that
    still carries an inline block is rejected at load (single source of truth)."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_inline_block
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
base_prompt: |
  You are Tina.

  Difficulty behavior (hard): speak fast and press hard.
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(
        tmp_path, monkeypatch, yaml_body, scenario_id="synth_inline_block"
    )
    with pytest.raises(RuntimeError, match="Difficulty behavior"):
        scenarios_mod.load_scenario_base_prompt("synth_inline_block")


def test_load_scenario_base_prompt_rejects_bad_difficulty_override() -> None:
    """A bad override is fail-loud (defensive; the API Literal 422s first)."""
    from pipeline.scenarios import load_scenario_base_prompt

    with pytest.raises(RuntimeError, match="difficulty"):
        load_scenario_base_prompt("waiter_easy_01", difficulty_override="bogus")


def test_shipped_scenarios_have_no_inline_difficulty_block() -> None:
    """AC4 / Task 2 regression net — every shipped scenario YAML dropped its
    inline behavior block, so the composed prompt contains EXACTLY ONE
    'Difficulty behavior (' (the one appended from the code constant). A double
    would mean a YAML still carries an inline block."""
    from pipeline.scenarios import _SCENARIO_INDEX, load_scenario_base_prompt

    for scenario_id in _SCENARIO_INDEX:
        composed = load_scenario_base_prompt(scenario_id)
        assert composed.count("Difficulty behavior (") == 1, (
            f"{scenario_id!r} composed prompt has a duplicated/inline difficulty block"
        )


def test_shipped_personas_have_no_difficulty_coded_phrases() -> None:
    """Story 6.19 follow-up — every shipped persona is DIFFICULTY-NEUTRAL: the
    RAW base_prompt (the persona, BEFORE the difficulty block is appended) must
    contain none of the known difficulty-coded phrases. The difficulty knob lives
    ONLY in `_DIFFICULTY_PROMPTS`; a coded phrase frozen in a persona leaks the
    authored difficulty and defeats the global difficulty pick. Deterministic, no
    LLM — the cheap CI complement to the live A/B (compare_difficulty.py)."""
    import yaml

    from pipeline.scenarios import _SCENARIO_INDEX, find_persona_difficulty_leaks

    offenders: dict[str, list[str]] = {}
    for scenario_id, path in _SCENARIO_INDEX.items():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        leaks = find_persona_difficulty_leaks(data.get("base_prompt") or "")
        if leaks:
            offenders[scenario_id] = leaks
    assert not offenders, (
        f"difficulty-coded phrase(s) in persona base_prompt(s): {offenders}. Move "
        "that behavior into scenarios._DIFFICULTY_PROMPTS — personas must be "
        "difficulty-NEUTRAL."
    )


# Identity tokens that MUST survive any persona rewrite (a careless 'strip coded
# phrases' pass that also gutted the name would silently break test_calls.py /
# the env-threading tests downstream). Cheap tripwire.
_PERSONA_IDENTITY_TOKENS = {
    "waiter_easy_01": "Tina",
    "cop_hard_01": "Sergeant Price",
    "cop_interrogation_01": "Mercer",
    "girlfriend_medium_01": "Rachel",
    "landlord_hard_01": "Gerald",
    "mugger_medium_01": "Danny",
}


def test_shipped_personas_preserve_character_identity() -> None:
    """Story 6.19 follow-up — the neutral-persona rewrite must keep each
    character's IDENTITY (name); only difficulty behavior was removed."""
    import yaml

    from pipeline.scenarios import _SCENARIO_INDEX

    for scenario_id, name in _PERSONA_IDENTITY_TOKENS.items():
        path = _SCENARIO_INDEX[scenario_id]
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        base_prompt = data.get("base_prompt") or ""
        assert name in base_prompt, (
            f"{scenario_id!r} persona lost its identity token {name!r}"
        )


def test_difficulty_blocks_are_distinct_and_personality_neutral() -> None:
    """Story 6.19 follow-up — by-construction guard that difficulty CAN change
    behavior: the three blocks are mutually distinct + non-empty, the composed
    persona differs across difficulties, and each block carries the persona-
    preservation clause (so it can't silently revert to scripting personality)."""
    from pipeline.scenarios import _DIFFICULTY_PROMPTS, load_scenario_base_prompt

    blocks = _DIFFICULTY_PROMPTS
    assert set(blocks) == {"easy", "medium", "hard"}
    assert len({blocks["easy"], blocks["medium"], blocks["hard"]}) == 3
    # Symmetric to the persona denylist: the BLOCKS must stay PERSONALITY-neutral
    # too (they change only language/accommodation). These words would appear only
    # if a future edit re-injected warmth/kindness/affect — the original easy-block
    # sin ("stay patient and encouraging"). Chosen so they never collide with the
    # blocks' own NEGATED uses (e.g. hard's "do NOT become angrier").
    block_personality_denylist = (
        "encouraging",
        "reassuring",
        "be warm",
        "be gentle",
        "be nicer",
        "be kinder",
        "comfort them",
    )
    for level, text in blocks.items():
        assert text.strip(), f"{level} block is empty"
        assert "LANGUAGE setting only" in text, (
            f"{level} block dropped the neutral clause"
        )
        # The retired hard catchphrase scripted personality — it must not return.
        assert "You heard me." not in text
        injected = [w for w in block_personality_denylist if w in text.lower()]
        assert not injected, f"{level} block injects personality: {injected}"
    # Composition actually threads difficulty: easy vs hard differ for a scenario.
    easy = load_scenario_base_prompt("waiter_easy_01", difficulty_override="easy")
    hard = load_scenario_base_prompt("waiter_easy_01", difficulty_override="hard")
    assert easy != hard


def test_build_stt_terms_returns_scenario_proper_nouns() -> None:
    """Story 6.19 follow-up — the per-scenario Soniox STT proper-noun bias list."""
    from pipeline.scenarios import build_stt_terms

    waiter = build_stt_terms("waiter_easy_01")
    assert "Tina" in waiter
    assert "The Golden Fork" in waiter
    assert "fish and chips" in waiter
    cop = build_stt_terms("cop_interrogation_01")
    assert "Halloran's Electronics" in cop
    assert "Carver Street" in cop
    # Unknown scenario → no bias (graceful: exactly today's behavior).
    assert build_stt_terms("nope_404") == []
    # learner_name hook prepends it first + trims + de-dups case-insensitively.
    named = build_stt_terms("girlfriend_medium_01", learner_name="  Walid  ")
    assert named[0] == "Walid"
    assert "Rachel" in named
    deduped = build_stt_terms("girlfriend_medium_01", learner_name="rachel")
    assert sum(1 for t in deduped if t.lower() == "rachel") == 1


def test_stt_terms_compose_into_soniox_context_object() -> None:
    """The terms list drops cleanly into the pipecat SonioxContextObject and
    serializes — the exact shape bot.py sends to Soniox in the config frame."""
    from pipecat.services.soniox.stt import SonioxContextObject

    from pipeline.scenarios import build_stt_terms

    dumped = SonioxContextObject(terms=build_stt_terms("waiter_easy_01")).model_dump()
    assert "Tina" in dumped["terms"]


def test_resolve_patience_config_validates_ladder_impatience_seconds_range(
    tmp_path, monkeypatch
) -> None:
    """A YAML override outside [0.5, 10.0] is rejected at resolve time."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_ladder_too_small
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  ladder_impatience_seconds: 0.1
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        yaml_body,
        scenario_id="synth_ladder_too_small",
    )
    with pytest.raises(RuntimeError, match="ladder_impatience_seconds"):
        scenarios_mod.resolve_patience_config("synth_ladder_too_small")


def test_resolve_patience_config_accepts_ladder_impatience_seconds_override(
    tmp_path, monkeypatch
) -> None:
    """A valid override (e.g. 6.0) is propagated into the resolved
    config dict, replacing the preset value."""
    from pipeline import scenarios as scenarios_mod

    yaml_body = """
metadata:
  id: synth_ladder_override
  title: Synthetic
  difficulty: easy
  is_free: true
  rive_character: waiter
  language_focus: test
  tts_voice_id: test
  content_warning: null
  ladder_impatience_seconds: 6.0
base_prompt: |
  base
checkpoints:
  - id: a
    hint_text: a
    prompt_segment: a
    success_criteria: a
exit_lines:
  hangup: "h"
  completion: "c"
"""
    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        yaml_body,
        scenario_id="synth_ladder_override",
    )
    config = scenarios_mod.resolve_patience_config("synth_ladder_override")
    assert config["ladder_impatience_seconds"] == 6.0


def test_waiter_clarify_accepts_drink_answer_after_drinks_offered() -> None:
    """Story 6.13 AC6 — when Tina's `clarify` prompt slides into drinks
    (smoke-gate call_id=148 + 151 showed she sometimes phrases it as
    "What about a drink? Water, juice, cola, or coffee?"), a user
    answering "Cola" / "Water" must be classified as a valid clarify
    response, not penalised as `checkpoint_unmet`. Verify the YAML's
    `clarify.success_criteria` prose tells the classifier so.
    """
    from pipeline.scenarios import load_scenario_checkpoints

    checkpoints = load_scenario_checkpoints("waiter_easy_01")
    clarify = next(c for c in checkpoints if c["id"] == "clarify")
    criteria = clarify["success_criteria"].lower()
    # The amended criteria must mention drink answers + at least one
    # drink synonym so the classifier picks up the wide net.
    assert "drink" in criteria, (
        "clarify criteria must mention 'drink' to signal the wide net to the classifier"
    )
    assert "cola" in criteria or "coke" in criteria, (
        "clarify criteria must list at least one drink synonym (cola / coke)"
    )


# ============================================================
# Story 6.11 — exit_lines.noisy_environment loading + fallback
# ============================================================


def test_resolve_patience_config_loads_waiter_noisy_environment_line() -> None:
    """End-to-end against the real `the-waiter.yaml`: Tina's per-character
    noisy_environment override is loaded into the config (AC5)."""
    from pipeline.scenarios import resolve_patience_config

    config = resolve_patience_config("waiter_easy_01")
    assert config["hang_up_line_noisy_environment"] == (
        "I can't hear you — there's another voice talking over you. "
        "Call me back when it's just you, somewhere quieter."
    )


def test_resolve_patience_config_noisy_environment_falls_back_to_default(
    tmp_path, monkeypatch
) -> None:
    """A scenario YAML WITHOUT `exit_lines.noisy_environment` inherits the
    generic `NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT` constant (AC5 — the 4
    un-overridden scenarios use the default)."""
    from pipeline import scenarios as scenarios_mod
    from pipeline.prompts import NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT

    _write_synthetic_yaml(
        tmp_path,
        monkeypatch,
        _BASE_YAML.format(
            scenario_id="synth_no_noisy",
            fail_penalty="null",
            recovery_bonus="null",
            silence_hangup_seconds="null",
            escalation_thresholds="null",
        ),
        scenario_id="synth_no_noisy",
    )
    config = scenarios_mod.resolve_patience_config("synth_no_noisy")
    assert (
        config["hang_up_line_noisy_environment"] == NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT
    )


def test_waiter_greet_criteria_requires_ordering_intent() -> None:
    """2026-05-30 fix — `greet` used to end with "Any coherent response
    counts", so an irrelevant line ("there is a lot of people here") passed
    it (smoke call_id=204). The criteria must now require a move toward
    ordering, and explicitly exclude bare greeting/small-talk."""
    from pipeline.scenarios import load_scenario_checkpoints

    greet = next(
        c for c in load_scenario_checkpoints("waiter_easy_01") if c["id"] == "greet"
    )
    crit = greet["success_criteria"].lower()
    assert "any coherent response" not in crit, (
        "the catch-all 'any coherent response counts' clause must be gone"
    )
    assert "order" in crit, "greet must require engaging with ordering"


def test_cop_curveball_criteria_rejects_offtopic_smalltalk() -> None:
    """2026-06-06 calibration fix — `curveball` used to end with "or provides
    any coherent response", so off-topic small talk ("there are a lot of people
    here", "the traffic was terrible this morning", "did you watch the game")
    passed the universal off-topic golden seed. The criteria must require the
    user to actually engage with the officer's question and exclude unrelated
    small talk, while STILL accepting a calm "I don't know" (the beat tests
    composure under pressure, not factual accuracy)."""
    from pipeline.scenarios import load_scenario_checkpoints

    cp = next(
        c for c in load_scenario_checkpoints("cop_hard_01") if c["id"] == "curveball"
    )
    crit = cp["success_criteria"].lower()
    assert "any coherent response" not in crit, (
        "the catch-all 'provides any coherent response' clause must be gone"
    )
    assert "small talk" in crit, (
        "curveball must explicitly exclude off-topic small talk"
    )
    assert "question" in crit, "curveball must require engaging with the question"


def test_girlfriend_explain_criteria_rejects_offtopic_remarks() -> None:
    """2026-06-06 calibration fix — `explain` accepted "any concrete excuse", so
    off-topic remarks ("the traffic was terrible this morning", a phone merely
    "almost dead") passed the universal off-topic golden seed. The criteria must
    require the reason to account for the missed contact and exclude off-topic
    remarks, while STILL accepting a genuine "my phone died" excuse."""
    from pipeline.scenarios import load_scenario_checkpoints

    cp = next(
        c
        for c in load_scenario_checkpoints("girlfriend_medium_01")
        if c["id"] == "explain"
    )
    crit = cp["success_criteria"].lower()
    assert "any concrete excuse" not in crit, (
        "the loose 'any concrete excuse counts' clause must be gone"
    )
    assert "off-topic" in crit, "explain must explicitly exclude off-topic remarks"
    assert "missed contact" in crit, (
        "explain must require the reason to account for the missed contact"
    )


def test_girlfriend_react_criteria_rejects_offtopic_smalltalk() -> None:
    """2026-06-06 calibration fix — `react` ended with "Any coherent response
    that acknowledges the confrontation counts", so off-topic small talk ("there
    are a lot of people here today") passed the universal off-topic golden seed.
    The criteria must require the reply to engage with the confrontation and
    exclude off-topic small talk."""
    from pipeline.scenarios import load_scenario_checkpoints

    cp = next(
        c
        for c in load_scenario_checkpoints("girlfriend_medium_01")
        if c["id"] == "react"
    )
    crit = cp["success_criteria"].lower()
    assert "any coherent response" not in crit, (
        "the catch-all 'any coherent response counts' clause must be gone"
    )
    assert "small talk" in crit, "react must explicitly exclude off-topic small talk"
