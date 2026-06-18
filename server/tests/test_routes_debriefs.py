"""Story 7.1 — tests for `GET /debriefs/{call_id}` (AC8).

Happy path + the two 404 envelopes (cross-user `CALL_NOT_FOUND`, missing
`DEBRIEF_NOT_READY`) + auth. Uses the real auth flow (`register_user` +
`issue_token`) and writes the call_session / debrief rows straight into the
per-test DB (the bot's job in prod).
"""

from __future__ import annotations

import asyncio
import json

from auth.jwt_service import issue_token
from db.database import get_connection
from db.queries import insert_call_session, insert_debrief
from tests.conftest import register_user

_NOW = "2026-06-08T12:00:00Z"
_SCENARIO_ID = "mugger_medium_01"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _full_debrief(survival: int = 73) -> dict:
    debrief = {
        "survival_pct": survival,
        "character_name": "The Mugger",
        "scenario_title": "Give me your wallet",
        "attempt_number": 1,
        "previous_best": None,
        "errors": [
            {
                "user_said": "I am agree",
                "correction": "I agree",
                "context": "Responding to the demand",
                "count": 3,
            }
        ],
        "hesitations": [{"duration_sec": 4.2, "context": "After the threat"}],
        "idioms": [],
        "areas_to_work_on": ["Negative structure", "Articles"],
        "inappropriate_behavior": None,
    }
    if survival > 40:
        debrief["encouraging_framing"] = {
            "proximity": f"{100 - survival}% away from surviving The Mugger"
        }
    return debrief


def _seed_call(user_id: int, *, with_debrief: bool, survival: int = 73) -> int:
    async def _go() -> int:
        async with get_connection() as db:
            call_id = await insert_call_session(db, user_id, _SCENARIO_ID, _NOW)
            if with_debrief:
                await insert_debrief(
                    db,
                    call_session_id=call_id,
                    survival_pct=survival,
                    checkpoints_passed=2,
                    total_checkpoints=3,
                    debrief_json=json.dumps(_full_debrief(survival)),
                    prompt_version="1.0",
                    created_at=_NOW,
                )
        return call_id

    return asyncio.run(_go())


def test_get_debrief_happy_path(client, test_db_path):
    user_id = register_user(client, test_db_path, email="a@example.com")
    call_id = _seed_call(user_id, with_debrief=True)

    resp = client.get(f"/debriefs/{call_id}", headers=_auth(issue_token(user_id)))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["survival_pct"] == 73
    assert data["character_name"] == "The Mugger"
    assert data["scenario_title"] == "Give me your wallet"
    assert len(data["errors"]) == 1
    assert 2 <= len(data["areas_to_work_on"]) <= 3
    assert "encouraging_framing" in data
    assert resp.json()["meta"]["timestamp"]


def test_free_user_retains_access_to_past_debrief(client, test_db_path):
    """Story 8.3 AC6 — a free (or reverted-to-free) user keeps access to all
    past debriefs. The debrief route is NOT tier-gated; it enforces only
    call_session ownership. `register_user` mints a default `free` user, so a
    200 here proves a churned paid->free user still reads their history."""
    import sqlite3

    user_id = register_user(client, test_db_path, email="reverted@example.com")
    call_id = _seed_call(user_id, with_debrief=True)
    # Make the tier explicitly free (the reverted-payer state).
    conn = sqlite3.connect(test_db_path)
    conn.execute("UPDATE users SET tier = 'free' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    resp = client.get(f"/debriefs/{call_id}", headers=_auth(issue_token(user_id)))

    assert resp.status_code == 200
    assert resp.json()["data"]["survival_pct"] == 73


def test_get_debrief_omits_framing_below_threshold(client, test_db_path):
    user_id = register_user(client, test_db_path, email="low@example.com")
    call_id = _seed_call(user_id, with_debrief=True, survival=30)

    resp = client.get(f"/debriefs/{call_id}", headers=_auth(issue_token(user_id)))

    assert resp.status_code == 200
    # encouraging_framing is ABSENT (not null) below 41% — client keys on presence.
    assert "encouraging_framing" not in resp.json()["data"]


def test_cross_user_returns_404_call_not_found(client, test_db_path):
    owner = register_user(client, test_db_path, email="owner@example.com")
    intruder = register_user(client, test_db_path, email="intruder@example.com")
    call_id = _seed_call(owner, with_debrief=True)

    resp = client.get(f"/debriefs/{call_id}", headers=_auth(issue_token(intruder)))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CALL_NOT_FOUND"


def test_nonexistent_call_returns_404_call_not_found(client, test_db_path):
    user_id = register_user(client, test_db_path, email="ghost@example.com")

    resp = client.get("/debriefs/999999", headers=_auth(issue_token(user_id)))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CALL_NOT_FOUND"


def test_not_ready_returns_404_debrief_not_ready(client, test_db_path):
    user_id = register_user(client, test_db_path, email="pending@example.com")
    call_id = _seed_call(user_id, with_debrief=False)

    resp = client.get(f"/debriefs/{call_id}", headers=_auth(issue_token(user_id)))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DEBRIEF_NOT_READY"


def test_missing_token_returns_401(client, test_db_path):
    user_id = register_user(client, test_db_path, email="noauth@example.com")
    call_id = _seed_call(user_id, with_debrief=True)

    resp = client.get(f"/debriefs/{call_id}")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def _seed_call_with_raw_blob(user_id: int, raw_json: str) -> int:
    async def _go() -> int:
        async with get_connection() as db:
            call_id = await insert_call_session(db, user_id, _SCENARIO_ID, _NOW)
            await insert_debrief(
                db,
                call_session_id=call_id,
                survival_pct=50,
                checkpoints_passed=1,
                total_checkpoints=2,
                debrief_json=raw_json,
                prompt_version="1.0",
                created_at=_NOW,
            )
        return call_id

    return asyncio.run(_go())


def test_blob_missing_required_fields_returns_500_envelope(client, test_db_path):
    # A stored blob that's valid JSON but violates the DebriefOut contract →
    # shaped 500 DEBRIEF_UNAVAILABLE, never a raw 500.
    user_id = register_user(client, test_db_path, email="corrupt1@example.com")
    call_id = _seed_call_with_raw_blob(user_id, json.dumps({"survival_pct": 73}))

    resp = client.get(f"/debriefs/{call_id}", headers=_auth(issue_token(user_id)))

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "DEBRIEF_UNAVAILABLE"


def test_non_json_blob_returns_500_envelope(client, test_db_path):
    user_id = register_user(client, test_db_path, email="corrupt2@example.com")
    call_id = _seed_call_with_raw_blob(user_id, "not json at all")

    resp = client.get(f"/debriefs/{call_id}", headers=_auth(issue_token(user_id)))

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "DEBRIEF_UNAVAILABLE"
