"""CLI tool for scoring voice call transcripts against scenario calibration targets.

Usage:
    python scripts/score_transcript.py \
        --transcript /tmp/transcript_abc123.json \
        --scenario-name "The Waiter" \
        --difficulty easy \
        --expected-exchanges 6 \
        --language-focus "ordering food,polite requests,food adjectives"
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCORING_SYSTEM_PROMPT = """\
You are an English language evaluator for a conversation practice app. You analyze transcripts of voice conversations between a language learner (B1 intermediate level) and an AI character.

Your task is to produce a structured evaluation in JSON format. Be specific, honest, and constructive. Never praise without merit. Never soften the truth.

## Rules

1. **Language errors**: Identify grammar, vocabulary, and syntax errors the USER made. For each error, provide the exact quote, the correction, and brief context. Deduplicate — if the same error pattern appears multiple times, report it once with a repetition count. Maximum 5 errors, prioritized by frequency and severity.

2. **Hesitations**: Identify moments where the user paused for more than 3 seconds before responding. Use timestamp gaps between character speech end and user speech start. Report the duration and what the character said just before the pause (the trigger). Maximum 3 hesitations, longest first.

3. **Idioms and slang**: Identify idiomatic expressions or slang the CHARACTER used that a B1 learner might not know. Provide the expression, its meaning, and the context in which it appeared. Maximum 3 idioms.

4. **Areas to work on**: Based on the error patterns and hesitations, suggest 2–3 specific, actionable improvement areas. Be concrete — not "improve grammar" but "practice negative sentence structures (don't/doesn't instead of 'not want')". Each area must reference at least one specific error from the transcript.

5. **Call summary**: One sentence describing what happened in the call (factual, no judgment). If the character hung up, state why objectively.

## Output format

Return ONLY valid JSON matching the schema below. No markdown, no explanation, no preamble.\
"""

REQUIRED_RESPONSE_KEYS = [
    "language_errors",
    "hesitations",
    "idioms_encountered",
    "areas_to_work_on",
    "call_summary",
]

TARGET_RANGES = {
    "easy": (60, 80),
    "medium": (35, 55),
    "hard": (15, 35),
}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CALIBRATION_DIR = (
    REPO_ROOT / "_bmad-output" / "implementation-artifacts" / "calibration-tests"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Score a voice call transcript against calibration targets."
    )
    parser.add_argument(
        "--transcript", required=True, help="Path to transcript JSON file"
    )
    parser.add_argument("--scenario-name", required=True, help="Scenario display name")
    parser.add_argument(
        "--difficulty",
        required=True,
        choices=["easy", "medium", "hard"],
        help="Difficulty level",
    )
    parser.add_argument(
        "--expected-exchanges",
        required=True,
        type=int,
        help="Number of expected exchanges in scenario",
    )
    parser.add_argument(
        "--language-focus",
        required=True,
        help="Comma-separated language focus areas",
    )
    return parser.parse_args(argv)


def calculate_survival_pct(transcript: list[dict], expected_exchanges: int) -> int:
    """Calculate survival percentage from transcript turns."""
    successful = sum(
        1
        for t in transcript
        if t["role"] == "user"
        and t.get("text", "").strip()
        and t.get("event") != "silence_timeout"
    )
    if expected_exchanges <= 0:
        return 0
    return min(100, successful * 100 // expected_exchanges)


def count_successful_exchanges(transcript: list[dict]) -> int:
    """Count the number of successful user exchanges."""
    return sum(
        1
        for t in transcript
        if t["role"] == "user"
        and t.get("text", "").strip()
        and t.get("event") != "silence_timeout"
    )


def get_hang_up_reason(transcript: list[dict]) -> str:
    """Determine the hang-up reason from the last transcript events."""
    if not transcript:
        return "no_transcript"
    last_user_turns = [t for t in transcript if t["role"] == "user"]
    if last_user_turns and last_user_turns[-1].get("event") == "silence_timeout":
        return "silence_timeout"
    return "completed"


def build_scoring_payload(
    transcript: list[dict],
    scenario_name: str,
    difficulty: str,
    expected_exchanges: int,
    language_focus: list[str],
    duration_seconds: int,
    survival_pct: int,
    successful: int,
) -> dict:
    """Build the payload for the AI scoring LLM call."""
    return {
        "transcript": transcript,
        "scenario": {
            "character_name": scenario_name,
            "difficulty": difficulty,
            "expected_exchanges": expected_exchanges,
            "language_focus": language_focus,
        },
        "call_metadata": {
            "duration_seconds": duration_seconds,
            "successful_exchanges": successful,
            "survival_pct": survival_pct,
            "hang_up_reason": get_hang_up_reason(transcript),
        },
    }


def call_openrouter(payload: dict) -> dict:
    """Send the scoring payload to OpenRouter and return parsed JSON response."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print(
            "ERROR: OPENROUTER_API_KEY environment variable not set.", file=sys.stderr
        )
        sys.exit(1)

    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "qwen/qwen3-235b-a22b",
            "messages": [
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            "response_format": {"type": "json_object"},
            "reasoning": {"enabled": False},
        },
        timeout=60.0,
    )
    response.raise_for_status()

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        print(f"ERROR: Unexpected API response structure: {e}", file=sys.stderr)
        print(f"Response: {json.dumps(data, indent=2)[:500]}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"ERROR: LLM returned non-JSON content: {e}", file=sys.stderr)
        print(f"Content: {str(content)[:500]}", file=sys.stderr)
        sys.exit(1)


def validate_response_keys(scoring: dict) -> list[str]:
    """Check for missing required keys in LLM response. Returns list of missing keys."""
    return [k for k in REQUIRED_RESPONSE_KEYS if k not in scoring]


def format_report(
    scenario_name: str,
    difficulty: str,
    survival_pct: int,
    successful: int,
    expected_exchanges: int,
    duration_seconds: int,
    hang_up_reason: str,
    scoring: dict,
    missing_keys: list[str],
) -> str:
    """Format the calibration report for stdout."""
    lo, hi = TARGET_RANGES[difficulty]
    if lo <= survival_pct <= hi:
        status = "IN RANGE"
    elif survival_pct < lo:
        status = "TOO LOW"
    else:
        status = "TOO HIGH"

    lang_errors = len(scoring.get("language_errors", []))
    hesitations = len(scoring.get("hesitations", []))
    idioms = len(scoring.get("idioms_encountered", []))
    areas = len(scoring.get("areas_to_work_on", []))

    if missing_keys:
        debrief_quality = f"MISSING: {', '.join(missing_keys)}"
    else:
        debrief_quality = "ALL FIELDS PRESENT"

    lines = [
        "",
        "\u2550" * 51,
        f" CALIBRATION REPORT — {scenario_name} ({difficulty})",
        "\u2550" * 51,
        f" Survival: {survival_pct}% (target: {lo}-{hi}%) {status}",
        f" Exchanges: {successful}/{expected_exchanges} successful",
        f" Duration: {duration_seconds}s",
        f" Hang-up reason: {hang_up_reason}",
        "",
        f" Language errors found: {lang_errors}",
        f" Hesitations found: {hesitations}",
        f" Idioms encountered: {idioms}",
        f" Areas to work on: {areas}",
        "",
        f" Debrief quality: {debrief_quality}",
        "\u2550" * 51,
        "",
    ]
    return "\n".join(lines)


def save_result(
    scenario_name: str,
    difficulty: str,
    payload: dict,
    scoring: dict,
    survival_pct: int,
    missing_keys: list[str],
) -> Path:
    """Save the full result JSON to calibration-tests directory."""
    lo, hi = TARGET_RANGES[difficulty]
    if lo <= survival_pct <= hi:
        status = "IN RANGE"
    elif survival_pct < lo:
        status = "TOO LOW"
    else:
        status = "TOO HIGH"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = scenario_name.replace(" ", "_").lower()
    filename = f"{safe_name}_{difficulty}_{timestamp}.json"

    result = {
        "input": payload,
        "scoring": scoring,
        "survival_pct": survival_pct,
        "target_range": f"{lo}-{hi}%",
        "status": status,
        "missing_keys": missing_keys,
        "scored_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CALIBRATION_DIR / filename
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return output_path


def main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    args = parse_args(argv)

    transcript_path = Path(args.transcript)
    if not transcript_path.exists():
        print(f"ERROR: Transcript file not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    try:
        transcript_data = json.loads(transcript_path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in transcript file: {e}", file=sys.stderr)
        sys.exit(1)

    if "transcript" not in transcript_data:
        print("ERROR: Transcript file missing 'transcript' key.", file=sys.stderr)
        sys.exit(1)

    transcript = transcript_data["transcript"]
    duration_seconds = transcript_data.get("duration_seconds", 0)
    language_focus = [s.strip() for s in args.language_focus.split(",")]

    successful = count_successful_exchanges(transcript)
    survival_pct = calculate_survival_pct(transcript, args.expected_exchanges)
    hang_up_reason = get_hang_up_reason(transcript)

    payload = build_scoring_payload(
        transcript=transcript,
        scenario_name=args.scenario_name,
        difficulty=args.difficulty,
        expected_exchanges=args.expected_exchanges,
        language_focus=language_focus,
        duration_seconds=duration_seconds,
        survival_pct=survival_pct,
        successful=successful,
    )

    scoring = call_openrouter(payload)
    missing_keys = validate_response_keys(scoring)
    if missing_keys:
        print(
            f"WARNING: LLM response missing keys: {', '.join(missing_keys)}",
            file=sys.stderr,
        )

    report = format_report(
        scenario_name=args.scenario_name,
        difficulty=args.difficulty,
        survival_pct=survival_pct,
        successful=successful,
        expected_exchanges=args.expected_exchanges,
        duration_seconds=duration_seconds,
        hang_up_reason=hang_up_reason,
        scoring=scoring,
        missing_keys=missing_keys,
    )
    print(report)

    output_path = save_result(
        scenario_name=args.scenario_name,
        difficulty=args.difficulty,
        payload=payload,
        scoring=scoring,
        survival_pct=survival_pct,
        missing_keys=missing_keys,
    )
    print(f"Full result saved to: {output_path}")


if __name__ == "__main__":
    main()
