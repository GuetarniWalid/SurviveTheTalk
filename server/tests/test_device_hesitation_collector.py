"""Story 7.5 (D3-c) — tests for the bot-side device hesitation collector + the
teardown merge that prefers device gaps over the server observer."""

from __future__ import annotations

from pipeline.device_hesitation_collector import (
    DeviceHesitationCollector,
    merge_hesitation_sources,
)


class _FakeCollector:
    def __init__(self, transcript=None):
        self.transcript = transcript or []


def test_record_accepts_a_gap_and_shapes_the_output():
    coll = DeviceHesitationCollector(
        collector=_FakeCollector([{"role": "character", "text": "Answer me."}])
    )
    coll.record(gap_ms=6000, censored=False)
    assert coll.has_device_gaps
    assert coll.top_hesitations() == [
        {
            "id": "d1",
            "duration_sec": 6.0,
            "preceding_character_line": "Answer me.",
            "resolved": True,
            "source": "device",
        }
    ]


def test_record_ignores_censored_subthreshold_and_non_numeric():
    coll = DeviceHesitationCollector(collector=_FakeCollector([]))
    coll.record(gap_ms=6000, censored=True)  # censored → the server covers it
    coll.record(gap_ms=2000, censored=False)  # 2 s < 4 s threshold
    coll.record(gap_ms=None, censored=False)  # non-numeric
    coll.record(gap_ms=True, censored=False)  # bool is not a gap
    assert coll.top_hesitations() == []
    assert not coll.has_device_gaps


def test_top_hesitations_keeps_the_three_longest():
    coll = DeviceHesitationCollector(
        collector=_FakeCollector([{"role": "character", "text": "x"}])
    )
    for ms in (4000, 8000, 5000, 6000):
        coll.record(gap_ms=ms, censored=False)
    assert [h["duration_sec"] for h in coll.top_hesitations()] == [8.0, 6.0, 5.0]


def test_merge_falls_back_to_server_when_no_device_gaps():
    server = [
        {
            "id": "h1",
            "duration_sec": 5.0,
            "context": "",
            "resolved": True,
            "source": "server",
        }
    ]
    assert merge_hesitation_sources([], server) == server


def test_merge_no_device_branch_returns_a_fresh_list_not_the_input():
    """Story 7.6 (AC5) — the no-device fallback returns `list(server)`, a NEW
    list with the same contents, NOT the caller's reference. Mutating the merge
    result must never reach back into the observer's internal list (the latent
    aliasing the 7.5 review flagged)."""
    server = [{"id": "h1", "duration_sec": 5.0, "resolved": True, "source": "server"}]
    merged = merge_hesitation_sources([], server)
    assert merged == server  # same contents…
    assert merged is not server  # …but a distinct list object
    merged.append({"id": "x"})  # mutating the result…
    assert len(server) == 1  # …leaves the observer's list untouched


def test_merge_prefers_device_and_adds_server_unresolved_freezes():
    device = [
        {
            "id": "d1",
            "duration_sec": 5.0,
            "preceding_character_line": "a",
            "resolved": True,
            "source": "device",
        }
    ]
    server = [
        # A resolved server gap — DROPPED (the device measured it accurately).
        {
            "id": "h1",
            "duration_sec": 4.0,
            "preceding_character_line": "a",
            "resolved": True,
            "source": "server",
        },
        # An UNRESOLVED freeze — the device can't see it (it disarms on the
        # re-speak), so it is KEPT.
        {
            "id": "h2",
            "duration_sec": 9.0,
            "preceding_character_line": "b",
            "resolved": False,
            "source": "server",
        },
    ]
    merged = merge_hesitation_sources(device, server)
    assert [h["id"] for h in merged] == ["h2", "d1"]
    assert all(h["id"] != "h1" for h in merged)


def test_merge_caps_at_top_n():
    device = [
        {"id": f"d{i}", "duration_sec": float(i), "resolved": True, "source": "device"}
        for i in (3, 4, 5, 6)
    ]
    assert [h["duration_sec"] for h in merge_hesitation_sources(device, [])] == [
        6.0,
        5.0,
        4.0,
    ]
