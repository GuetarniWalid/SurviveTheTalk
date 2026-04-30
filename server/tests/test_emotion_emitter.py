"""Story 6.3 — Tests for EmotionEmitter FrameProcessor (AC1, AC9)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipeline.emotion_emitter import (
    _ALLOWED_EMOTIONS,
    EmotionEmitter,
    _parse_classifier_output,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_emitter() -> EmotionEmitter:
    return EmotionEmitter(character="waiter", openrouter_api_key="test-key")


def _make_user_frame(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(
        text=text,
        user_id="user",
        timestamp="2026-04-30T12:00:00Z",
        finalized=True,
    )


def _capture_pushed(emitter: EmotionEmitter) -> list[Frame]:
    """Replace `push_frame` with a recorder that returns the pushed frames."""
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    emitter.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _mock_classifier(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any] | None = None
) -> AsyncMock:
    """Replace EmotionEmitter._classify with a simple AsyncMock."""
    mock = AsyncMock(return_value=payload)
    monkeypatch.setattr(EmotionEmitter, "_classify", mock)
    return mock


# ---------- Test 1: pass-through ----------


def test_process_frame_is_pass_through_for_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every TranscriptionFrame is forwarded downstream regardless of branch."""
    _mock_classifier(monkeypatch, payload=None)
    emitter = _make_emitter()
    captured = _capture_pushed(emitter)
    frame = _make_user_frame("I want a chicken.")

    async def _drive() -> None:
        await emitter.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(emitter)

    _run(_drive())

    assert frame in captured, "TranscriptionFrame must be forwarded downstream"


def test_process_frame_is_pass_through_for_other_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-transcription frames pass through without scheduling a classify."""
    _mock_classifier(monkeypatch, payload=None)
    emitter = _make_emitter()
    captured = _capture_pushed(emitter)

    other = OutputTransportMessageFrame(message={"unrelated": True})
    _run(emitter.process_frame(other, FrameDirection.DOWNSTREAM))

    assert other in captured
    assert emitter._in_flight is None


# ---------- Test 2: happy path ----------


def test_happy_path_emits_emotion_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful classify result becomes an OutputTransportMessageFrame."""
    _mock_classifier(monkeypatch, payload={"emotion": "satisfaction", "intensity": 0.7})
    emitter = _make_emitter()
    captured = _capture_pushed(emitter)
    frame = _make_user_frame("I would like the grilled chicken, please.")

    async def _drive() -> None:
        await emitter.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(emitter)

    _run(_drive())

    envelopes = [f for f in captured if isinstance(f, OutputTransportMessageFrame)]
    assert len(envelopes) == 1
    assert envelopes[0].message == {
        "type": "emotion",
        "data": {"emotion": "satisfaction", "intensity": 0.7},
    }


# ---------- Test 3: invalid emotion rejected ----------


def test_classifier_returning_reserved_emotion_is_rejected(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Reserved enums (sadness/boredom/impressed) MUST NOT be emitted."""
    # The parser is the layer that enforces _ALLOWED_EMOTIONS — go through
    # it to mirror the real call path.

    async def _fake_classify(self: EmotionEmitter, text: str) -> Any:
        # Simulate the model returning a value reserved for downstream stories.
        return _parse_classifier_output(
            json.dumps({"emotion": "sadness", "intensity": 0.5})
        )

    monkeypatch.setattr(EmotionEmitter, "_classify", _fake_classify)
    emitter = _make_emitter()
    captured = _capture_pushed(emitter)
    frame = _make_user_frame("hello")

    async def _drive() -> None:
        await emitter.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(emitter)

    _run(_drive())

    envelopes = [f for f in captured if isinstance(f, OutputTransportMessageFrame)]
    assert envelopes == []


# ---------- Test 4: JSON parse failure ----------


def test_parser_handles_prose_around_json() -> None:
    """Models occasionally wrap JSON in prose; parser falls back to {...} extract."""
    out = _parse_classifier_output(
        'Sure, here is the answer: {"emotion": "smirk", "intensity": 0.4}.'
    )
    assert out == {"emotion": "smirk", "intensity": 0.4}


def test_parser_returns_none_for_pure_prose() -> None:
    """No JSON object at all → None."""
    assert _parse_classifier_output("I think frustration") is None


# ---------- Test 5: timeout ----------


def test_classifier_timeout_emits_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A slow classifier that exceeds the 2.0s budget MUST NOT emit."""
    # Patch the timeout constant on the module so the test runs fast.
    import pipeline.emotion_emitter as ee

    monkeypatch.setattr(ee, "_CLASSIFIER_TIMEOUT_SECONDS", 0.05)

    async def _slow_classify(self: EmotionEmitter, text: str) -> Any:
        await asyncio.sleep(0.5)
        return {"emotion": "satisfaction", "intensity": 1.0}

    monkeypatch.setattr(EmotionEmitter, "_classify", _slow_classify)
    emitter = _make_emitter()
    captured = _capture_pushed(emitter)
    frame = _make_user_frame("hello")

    async def _drive() -> None:
        await emitter.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(emitter)

    _run(_drive())

    envelopes = [f for f in captured if isinstance(f, OutputTransportMessageFrame)]
    assert envelopes == []


# ---------- Test 6: stale-task cancellation ----------


def test_rapid_user_turns_only_last_emits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 transcription frames in quick succession → only the third's verdict
    reaches push_frame as an OutputTransportMessageFrame.
    """
    call_count = {"n": 0}

    async def _slow_classify(self: EmotionEmitter, text: str) -> Any:
        call_count["n"] += 1
        # Long enough that earlier calls are still in flight when the next
        # transcription arrives.
        await asyncio.sleep(0.05)
        return {"emotion": "confusion", "intensity": 0.6, "_text": text}

    monkeypatch.setattr(EmotionEmitter, "_classify", _slow_classify)
    emitter = _make_emitter()
    captured = _capture_pushed(emitter)

    async def _drive() -> None:
        # Fire three frames back-to-back, awaiting each call to process_frame
        # (which performs the cancel-then-create_task transition).
        await emitter.process_frame(
            _make_user_frame("first"), FrameDirection.DOWNSTREAM
        )
        await emitter.process_frame(
            _make_user_frame("second"), FrameDirection.DOWNSTREAM
        )
        await emitter.process_frame(
            _make_user_frame("third"), FrameDirection.DOWNSTREAM
        )
        # Wait for the last task to finish.
        if emitter._in_flight is not None:
            await asyncio.gather(emitter._in_flight, return_exceptions=True)

    _run(_drive())

    envelopes = [f for f in captured if isinstance(f, OutputTransportMessageFrame)]
    assert len(envelopes) == 1
    assert envelopes[0].message["data"]["_text"] == "third"


# ---------- Helpers ----------


async def _drain(emitter: EmotionEmitter) -> None:
    """Wait for any in-flight classifier task to resolve."""
    task = emitter._in_flight
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)


# ---------- Sanity guard: enum subset is the canonical 7 ----------


def test_allowed_emotions_is_seven_value_subset() -> None:
    assert _ALLOWED_EMOTIONS == frozenset(
        {
            "satisfaction",
            "smirk",
            "frustration",
            "impatience",
            "anger",
            "confusion",
            "disgust_hangup",
        }
    )
    # Reserved values for downstream stories MUST stay out.
    for reserved in ("sadness", "boredom", "impressed"):
        assert reserved not in _ALLOWED_EMOTIONS


# ---------- Defense in depth: emit-layer rejection (review patch) ----------


def test_emit_layer_rejects_reserved_emotion_independent_of_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense in depth: even if `_classify` is refactored to bypass
    `_parse_classifier_output` (e.g. structured-output mode where the
    SDK returns a dict directly), the emit layer must independently
    filter reserved emotions.
    """

    async def _bypass_parser(self: EmotionEmitter, text: str) -> Any:
        # Simulate a future code path that returns the dict directly,
        # skipping the parser's allow-list check entirely.
        return {"emotion": "sadness", "intensity": 0.5}

    monkeypatch.setattr(EmotionEmitter, "_classify", _bypass_parser)
    emitter = _make_emitter()
    captured = _capture_pushed(emitter)
    frame = _make_user_frame("hello")

    async def _drive() -> None:
        await emitter.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(emitter)

    _run(_drive())

    envelopes = [f for f in captured if isinstance(f, OutputTransportMessageFrame)]
    assert envelopes == [], (
        "emit layer must reject reserved emotions even if parser is bypassed"
    )


# ---------- Cleanup hook drains in-flight task on shutdown (review patch) ----


def test_cleanup_drains_in_flight_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pipeline shutdown must cancel + drain any pending classifier task,
    otherwise the asyncio loop logs `Task was destroyed but it is pending!`.
    """

    async def _slow_classify(self: EmotionEmitter, text: str) -> Any:
        await asyncio.sleep(1.0)
        return {"emotion": "satisfaction", "intensity": 0.5}

    monkeypatch.setattr(EmotionEmitter, "_classify", _slow_classify)
    emitter = _make_emitter()
    _capture_pushed(emitter)

    async def _drive() -> None:
        await emitter.process_frame(
            _make_user_frame("hello"), FrameDirection.DOWNSTREAM
        )
        # Task is in flight; cleanup must cancel and drain it.
        assert emitter._in_flight is not None
        await emitter.cleanup()
        assert emitter._in_flight is None

    _run(_drive())


# ---------- API key validation at construction (review patch) -------------


def test_constructor_rejects_empty_openrouter_api_key() -> None:
    """An empty API key would silently 401 every classify call. Fail fast."""
    with pytest.raises(ValueError, match="openrouter_api_key"):
        EmotionEmitter(character="waiter", openrouter_api_key="")


# ---------- Markdown fence parsing (review patch) -------------------------


def test_parser_strips_json_markdown_fence() -> None:
    out = _parse_classifier_output(
        '```json\n{"emotion": "smirk", "intensity": 0.4}\n```'
    )
    assert out == {"emotion": "smirk", "intensity": 0.4}


def test_parser_strips_unlabeled_markdown_fence() -> None:
    out = _parse_classifier_output('```\n{"emotion": "anger", "intensity": 0.9}\n```')
    assert out == {"emotion": "anger", "intensity": 0.9}


# ---------- HTTP boundary smoke test (extra, beyond the 6 ACs) ----------


def test_classify_uses_httpx_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The classify call hits the OpenRouter chat-completions endpoint with a
    Bearer token. We mock the transport so no network call is made.
    """
    body = {
        "choices": [
            {"message": {"content": json.dumps({"emotion": "anger", "intensity": 0.9})}}
        ]
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "openrouter.ai"
        assert request.headers["authorization"] == "Bearer test-key"
        # Lock in the Story 6.3 smoke-fix: `reasoning` MUST sit at the
        # top level of the JSON body, NOT nested in `extra_body`.
        # `extra_body` is an OpenAI-Python-SDK convention; the SDK
        # flattens it into the body before sending. Direct httpx calls
        # to OpenRouter's HTTP API don't go through the SDK, so a
        # nested `extra_body` is silently dropped → the model stays in
        # default reasoning mode → 5-15s response → classifier timeout.
        sent = json.loads(request.content)
        assert sent["model"] == "qwen/qwen3.5-flash-02-23"
        assert sent["reasoning"] == {"enabled": False}, (
            "reasoning must be at the top level of the body, not in extra_body"
        )
        assert "extra_body" not in sent, (
            "extra_body is OpenAI-SDK-only; would be dropped by OpenRouter"
        )
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(_handler)

    # Patch httpx.AsyncClient to use our MockTransport.
    real_client = httpx.AsyncClient

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("pipeline.emotion_emitter.httpx.AsyncClient", _factory)

    emitter = _make_emitter()
    out = _run(emitter._classify("hello"))
    assert out == {"emotion": "anger", "intensity": 0.9}
