"""Tests for character prompts."""

from pipeline.prompts import (
    CARTESIA_VOICE_ID,
    NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT,
    SARCASTIC_CHARACTER_PROMPT,
)


def test_noisy_environment_exit_line_default_is_non_empty() -> None:
    """Story 6.11 AC5 — the generic scenario-agnostic exit line exists and
    is non-empty (the fallback when a scenario YAML omits the override)."""
    assert isinstance(NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT, str)
    assert NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT.strip()


def test_sarcastic_prompt_is_non_empty() -> None:
    assert len(SARCASTIC_CHARACTER_PROMPT) > 0


def test_sarcastic_prompt_contains_persona_instructions() -> None:
    prompt = SARCASTIC_CHARACTER_PROMPT.lower()
    assert "sarcastic" in prompt
    assert "impatient" in prompt
    assert "english" in prompt
    assert "never" in prompt  # "never break character" / "never be encouraging"


def test_sarcastic_prompt_mentions_character_name() -> None:
    assert "Tina" in SARCASTIC_CHARACTER_PROMPT


def test_sarcastic_prompt_is_difficulty_neutral() -> None:
    """Story 6.19 follow-up — even the LEGACY fallback persona must stay
    difficulty-NEUTRAL: no inline 'Difficulty behavior' block and no coded
    phrase. Difficulty lives only in scenarios._DIFFICULTY_PROMPTS."""
    from pipeline.scenarios import find_persona_difficulty_leaks

    assert "Difficulty behavior (" not in SARCASTIC_CHARACTER_PROMPT
    assert find_persona_difficulty_leaks(SARCASTIC_CHARACTER_PROMPT) == []


def test_exchange_classifier_multi_prompt_present_and_shaped() -> None:
    """Story 6.10 AC3 (2026-05-29 structured-output rev) — the multi-goal
    classifier prompt exists, carries the 4 substitution placeholders,
    instructs the per-id met/unmet/unsure verdict (the strict json_schema
    enforces the object shape), preserves the intent-first principles +
    any-order framing, and keeps the Story 6.6 D3 XML injection tags."""
    from pipeline.prompts import EXCHANGE_CLASSIFIER_MULTI_PROMPT

    p = EXCHANGE_CLASSIFIER_MULTI_PROMPT
    # Substitution placeholders the classifier fills.
    assert "{pending_goals_block}" in p
    assert "{user_text}" in p
    assert "{last_character_line}" in p
    assert "{scenario_description}" in p
    # Per-id verdict vocabulary (schema-enforced enum).
    assert '"met"' in p
    assert '"unmet"' in p
    assert '"unsure"' in p
    # The old free-form array contract is gone (it caused the goal_id echo bug).
    assert "goals_met" not in p
    assert "goals_unmet" not in p
    # Intent-first principles preserved + the any-order contract.
    assert "INTENT" in p
    # 2026-05-30 fix — the judge must DEFAULT TO UNMET (was "Default to MET",
    # which passed every checkpoint regardless of input; smoke call_id=203/204).
    assert "Default to UNMET" in p
    assert "Default to MET" not in p
    assert "any order" in p.lower()
    assert "Synonyms" in p
    # Story 6.6 D3 — prompt-injection resistance via XML tags.
    assert "<user_response>" in p
    assert "<character_line>" in p


def test_multi_prompt_credits_polite_indirect_question_form_intent() -> None:
    """Story 10.8 Stream C (call 339) — judge-reliability hardening. A genuine
    move phrased POLITELY / INDIRECTLY / as a QUESTION-REQUEST must be credited
    (the call-339 false-negative: "I would like to know if it is possible to
    order?" was wrongly read as a precondition/dodge question and 'unmet',
    spiralling patience to a hang-up). The prompt must carry that principle AND
    the dodge-vs-genuine-question distinction — WITHOUT regressing the 10.7
    anti-permissive line (a genuine question can be met; an evasive/contentless
    one stays unmet)."""
    from pipeline.prompts import EXCHANGE_CLASSIFIER_MULTI_PROMPT

    p = EXCHANGE_CLASSIFIER_MULTI_PROMPT
    low = p.lower()
    # The 339 fix: polite/indirect/question-form genuine intent counts.
    assert "question/request" in low
    assert "ends in a question mark" in low
    assert "indirectly" in low
    # The distinction is explicit: a DODGE-question is still unmet, but a genuine
    # move phrased as a question/request performs the move.
    assert "dodge" in low
    # 10.7 anti-permissive content is preserved (no regression to "plays itself").
    assert "Default to UNMET" in p
    assert "PERFORM the move" in p
    assert '"No other choice"' in p  # the call-340 evasion still listed as unmet


def test_multi_prompt_formats_without_error() -> None:
    """The multi prompt must `.format()` cleanly with the 4 named
    placeholders."""
    from pipeline.prompts import EXCHANGE_CLASSIFIER_MULTI_PROMPT

    out = EXCHANGE_CLASSIFIER_MULTI_PROMPT.format(
        scenario_description="The Waiter",
        last_character_line="What can I get you?",
        user_text="a coke please",
        pending_goals_block="- greet: say hi",
    )
    assert "a coke please" in out
    assert "- greet: say hi" in out
    # Bare ids only — the tagged form is the bug.
    assert 'goal_id="greet"' not in out


def test_cartesia_voice_id_is_valid_uuid() -> None:
    import re

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    assert uuid_pattern.match(CARTESIA_VOICE_ID)
