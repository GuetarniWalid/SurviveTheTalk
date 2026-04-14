"""Tests for score_transcript.py CLI scoring tool."""

import json
from unittest.mock import patch

import pytest

from scripts.score_transcript import (
    build_scoring_payload,
    calculate_survival_pct,
    count_successful_exchanges,
    format_report,
    get_hang_up_reason,
    parse_args,
    save_result,
    validate_response_keys,
)


class TestCalculateSurvivalPct:
    def test_all_successful(self):
        transcript = [
            {"role": "character", "text": "Welcome", "timestamp_ms": 0},
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
            {"role": "character", "text": "What?", "timestamp_ms": 2000},
            {"role": "user", "text": "I want chicken", "timestamp_ms": 3000},
            {"role": "character", "text": "Which one?", "timestamp_ms": 4000},
            {"role": "user", "text": "The grilled one", "timestamp_ms": 5000},
        ]
        assert calculate_survival_pct(transcript, 3) == 100

    def test_partial_success(self):
        transcript = [
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
            {"role": "user", "text": "I want", "timestamp_ms": 3000},
            {
                "role": "user",
                "text": "",
                "timestamp_ms": None,
                "event": "silence_timeout",
            },
        ]
        assert calculate_survival_pct(transcript, 5) == 40

    def test_zero_successful(self):
        transcript = [
            {
                "role": "user",
                "text": "",
                "timestamp_ms": None,
                "event": "silence_timeout",
            },
            {
                "role": "user",
                "text": "",
                "timestamp_ms": None,
                "event": "silence_timeout",
            },
        ]
        assert calculate_survival_pct(transcript, 5) == 0

    def test_caps_at_100(self):
        transcript = [
            {"role": "user", "text": f"Turn {i}", "timestamp_ms": i * 1000}
            for i in range(10)
        ]
        assert calculate_survival_pct(transcript, 3) == 100

    def test_zero_expected_exchanges(self):
        transcript = [{"role": "user", "text": "Hello", "timestamp_ms": 0}]
        assert calculate_survival_pct(transcript, 0) == 0

    def test_empty_text_not_counted(self):
        transcript = [
            {"role": "user", "text": "", "timestamp_ms": 1000},
            {"role": "user", "text": "   ", "timestamp_ms": 2000},
            {"role": "user", "text": "Hello", "timestamp_ms": 3000},
        ]
        assert calculate_survival_pct(transcript, 5) == 20

    def test_silence_timeout_not_counted(self):
        transcript = [
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
            {
                "role": "user",
                "text": "Some text",
                "timestamp_ms": 2000,
                "event": "silence_timeout",
            },
        ]
        assert calculate_survival_pct(transcript, 5) == 20

    def test_character_turns_ignored(self):
        transcript = [
            {"role": "character", "text": "Welcome", "timestamp_ms": 0},
            {"role": "character", "text": "What?", "timestamp_ms": 2000},
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
        ]
        assert calculate_survival_pct(transcript, 3) == 33

    def test_uses_floor_division(self):
        transcript = [
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
        ]
        # 1 * 100 // 3 = 33 (floor)
        assert calculate_survival_pct(transcript, 3) == 33


class TestCountSuccessfulExchanges:
    def test_counts_valid_user_turns(self):
        transcript = [
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
            {"role": "character", "text": "Hi", "timestamp_ms": 2000},
            {"role": "user", "text": "I want", "timestamp_ms": 3000},
        ]
        assert count_successful_exchanges(transcript) == 2

    def test_excludes_silence_timeout(self):
        transcript = [
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
            {
                "role": "user",
                "text": "",
                "timestamp_ms": None,
                "event": "silence_timeout",
            },
        ]
        assert count_successful_exchanges(transcript) == 1


class TestGetHangUpReason:
    def test_empty_transcript(self):
        assert get_hang_up_reason([]) == "no_transcript"

    def test_silence_timeout(self):
        transcript = [
            {"role": "user", "text": "Hello", "timestamp_ms": 1000},
            {
                "role": "user",
                "text": "",
                "timestamp_ms": None,
                "event": "silence_timeout",
            },
        ]
        assert get_hang_up_reason(transcript) == "silence_timeout"

    def test_completed(self):
        transcript = [
            {"role": "user", "text": "Goodbye", "timestamp_ms": 5000},
        ]
        assert get_hang_up_reason(transcript) == "completed"


class TestParseArgs:
    def test_all_required_args(self):
        args = parse_args(
            [
                "--transcript",
                "/tmp/test.json",
                "--scenario-name",
                "The Waiter",
                "--difficulty",
                "easy",
                "--expected-exchanges",
                "6",
                "--language-focus",
                "ordering food,polite requests",
            ]
        )
        assert args.transcript == "/tmp/test.json"
        assert args.scenario_name == "The Waiter"
        assert args.difficulty == "easy"
        assert args.expected_exchanges == 6
        assert args.language_focus == "ordering food,polite requests"

    def test_invalid_difficulty_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(
                [
                    "--transcript",
                    "/tmp/test.json",
                    "--scenario-name",
                    "Test",
                    "--difficulty",
                    "impossible",
                    "--expected-exchanges",
                    "6",
                    "--language-focus",
                    "test",
                ]
            )


class TestValidateResponseKeys:
    def test_all_keys_present(self):
        scoring = {
            "language_errors": [],
            "hesitations": [],
            "idioms_encountered": [],
            "areas_to_work_on": [],
            "call_summary": "Test call.",
        }
        assert validate_response_keys(scoring) == []

    def test_missing_keys(self):
        scoring = {"language_errors": [], "call_summary": "Test."}
        missing = validate_response_keys(scoring)
        assert "hesitations" in missing
        assert "idioms_encountered" in missing
        assert "areas_to_work_on" in missing

    def test_all_keys_missing(self):
        assert len(validate_response_keys({})) == 5


class TestFormatReport:
    def test_in_range_easy(self):
        report = format_report(
            scenario_name="The Waiter",
            difficulty="easy",
            survival_pct=70,
            successful=4,
            expected_exchanges=6,
            duration_seconds=47,
            hang_up_reason="completed",
            scoring={
                "language_errors": [{"user_said": "test"}],
                "hesitations": [],
                "idioms_encountered": [],
                "areas_to_work_on": [{"area": "test"}],
                "call_summary": "Test.",
            },
            missing_keys=[],
        )
        assert "IN RANGE" in report
        assert "The Waiter" in report
        assert "70%" in report
        assert "4/6" in report
        assert "47s" in report
        assert "ALL FIELDS PRESENT" in report

    def test_too_low(self):
        report = format_report(
            scenario_name="Test",
            difficulty="easy",
            survival_pct=30,
            successful=2,
            expected_exchanges=6,
            duration_seconds=30,
            hang_up_reason="silence_timeout",
            scoring={},
            missing_keys=[],
        )
        assert "TOO LOW" in report

    def test_too_high(self):
        report = format_report(
            scenario_name="Test",
            difficulty="easy",
            survival_pct=95,
            successful=6,
            expected_exchanges=6,
            duration_seconds=60,
            hang_up_reason="completed",
            scoring={},
            missing_keys=[],
        )
        assert "TOO HIGH" in report

    def test_missing_keys_shown(self):
        report = format_report(
            scenario_name="Test",
            difficulty="medium",
            survival_pct=40,
            successful=3,
            expected_exchanges=6,
            duration_seconds=30,
            hang_up_reason="completed",
            scoring={},
            missing_keys=["hesitations", "call_summary"],
        )
        assert "MISSING: hesitations, call_summary" in report

    def test_hard_difficulty_range(self):
        report = format_report(
            scenario_name="The Cop",
            difficulty="hard",
            survival_pct=25,
            successful=2,
            expected_exchanges=8,
            duration_seconds=40,
            hang_up_reason="completed",
            scoring={},
            missing_keys=[],
        )
        assert "IN RANGE" in report
        assert "15-35%" in report


class TestBuildScoringPayload:
    def test_payload_structure(self):
        transcript = [{"role": "user", "text": "Hi", "timestamp_ms": 0}]
        payload = build_scoring_payload(
            transcript=transcript,
            scenario_name="The Waiter",
            difficulty="easy",
            expected_exchanges=6,
            language_focus=["ordering food"],
            duration_seconds=47,
            survival_pct=60,
            successful=3,
        )
        assert "transcript" in payload
        assert payload["scenario"]["character_name"] == "The Waiter"
        assert payload["scenario"]["difficulty"] == "easy"
        assert payload["call_metadata"]["survival_pct"] == 60
        assert payload["call_metadata"]["successful_exchanges"] == 3


class TestSaveResult:
    def test_saves_json_file(self, tmp_path):
        with patch("scripts.score_transcript.CALIBRATION_DIR", tmp_path):
            path = save_result(
                scenario_name="The Waiter",
                difficulty="easy",
                payload={"test": True},
                scoring={"call_summary": "Test."},
                survival_pct=70,
                missing_keys=[],
            )
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["survival_pct"] == 70
            assert data["status"] == "IN RANGE"
            assert "the_waiter_easy_" in path.name

    def test_filename_format(self, tmp_path):
        with patch("scripts.score_transcript.CALIBRATION_DIR", tmp_path):
            path = save_result(
                scenario_name="The Mugger",
                difficulty="hard",
                payload={},
                scoring={},
                survival_pct=10,
                missing_keys=["call_summary"],
            )
            assert "the_mugger_hard_" in path.name
            assert path.suffix == ".json"
