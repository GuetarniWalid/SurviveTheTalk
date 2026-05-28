"""Tests for character prompts."""

from pipeline.prompts import CARTESIA_VOICE_ID, SARCASTIC_CHARACTER_PROMPT


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


def test_exchange_classifier_multi_prompt_present_and_shaped() -> None:
    """Story 6.10 AC3 — the multi-goal classifier prompt exists, carries
    the 4 substitution placeholders, requests the goals_met/goals_unmet
    JSON schema, preserves the intent-first principles + any-order
    framing, and keeps the Story 6.6 D3 XML injection-resistance tags."""
    from pipeline.prompts import EXCHANGE_CLASSIFIER_MULTI_PROMPT

    p = EXCHANGE_CLASSIFIER_MULTI_PROMPT
    # Substitution placeholders the classifier fills.
    assert "{pending_goals_block}" in p
    assert "{user_text}" in p
    assert "{last_character_line}" in p
    assert "{scenario_description}" in p
    # Output schema.
    assert "goals_met" in p
    assert "goals_unmet" in p
    # Intent-first principles preserved + the any-order contract.
    assert "INTENT" in p
    assert "Default to MET" in p
    assert "any order" in p.lower()
    assert "Synonyms" in p
    # Story 6.6 D3 — prompt-injection resistance via XML tags.
    assert "<user_response>" in p
    assert "<character_line>" in p


def test_multi_prompt_formats_without_error() -> None:
    """The multi prompt must `.format()` cleanly with the 4 named
    placeholders (the JSON example braces are escaped as `{{ }}`)."""
    from pipeline.prompts import EXCHANGE_CLASSIFIER_MULTI_PROMPT

    out = EXCHANGE_CLASSIFIER_MULTI_PROMPT.format(
        scenario_description="The Waiter",
        last_character_line="What can I get you?",
        user_text="a coke please",
        pending_goals_block='1. [goal_id="greet"] say hi',
    )
    assert "a coke please" in out
    assert 'goal_id="greet"' in out
    # The literal JSON braces survive as single braces in the output.
    assert '{"goals_met"' in out


def test_cartesia_voice_id_is_valid_uuid() -> None:
    import re

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    assert uuid_pattern.match(CARTESIA_VOICE_ID)
