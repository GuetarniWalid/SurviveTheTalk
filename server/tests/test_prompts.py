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
    assert "Marcus" in SARCASTIC_CHARACTER_PROMPT


def test_cartesia_voice_id_is_valid_uuid() -> None:
    import re

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    assert uuid_pattern.match(CARTESIA_VOICE_ID)
