"""Story 6.3 — EmotionEmitter Pipecat FrameProcessor.

Observes `TranscriptionFrame`s (the user's transcribed speech) and fires an
async OpenRouter classification call. On success, emits an
`OutputTransportMessageFrame` with a `{"type":"emotion","data":{...}}` dict
payload. The LiveKit transport then JSON-encodes the dict and broadcasts it
over the data channel to the Flutter client (verified at
`pipecat/transports/livekit/transport.py:914-931`).

The classifier MUST NEVER block the main pipeline:
  - Each classification runs in a fire-and-forget `asyncio.create_task`.
  - At most ONE in-flight task per emitter instance — a new
    `TranscriptionFrame` cancels the previous task before scheduling a fresh
    one (latest-line-wins semantics: by the time the prior verdict comes
    back, the user has moved on, so its emit would be stale).
  - Every classification is wrapped in `asyncio.wait_for(timeout=2.0)`. On
    timeout the character simply stays in its previous emotional state —
    the user must NEVER see an in-call error UI (UX-DR6 graceful in-persona
    degradation).

The 7-value enum subset is the canonical contract with the Rive `.riv` file
(Story 2.6 §1). Values outside this set are silently rejected — they are
owned by downstream stories (6.4 boredom, 6.6 impressed, 6.4 sadness reserved).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipeline.prompts import EMOTION_CLASSIFIER_PROMPT

# Subset of Story 2.6's `emotion` Rive enum that is runtime-reactive (driven
# by user-line classification). `sadness` / `boredom` / `impressed` are
# reserved for Stories 6.4 / 6.6 and MUST NOT be emitted from here. A
# downstream consumer (`RiveCharacterCanvasState.setEmotion`) writes the
# string straight into the Rive ViewModel enum via `viewModel.enumerator(...)`,
# so a typo here would surface as a no-op on the client (Rive 0.14.x
# null-safe enum write per `rive-flutter-rules.md` §9).
_ALLOWED_EMOTIONS: frozenset[str] = frozenset(
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

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_MODEL = "qwen/qwen3.5-flash-02-23"
# 5.0s gives the model headroom even when OpenRouter is briefly slow.
# Original 2.0s was too tight: smoke gate showed every classification
# timing out, leaving the character locked in its default emotion.
_CLASSIFIER_TIMEOUT_SECONDS = 5.0
# < classifier timeout so httpx aborts first and we surface a clean
# HTTP error log line instead of an opaque asyncio.TimeoutError.
_HTTP_TIMEOUT_SECONDS = 4.5


class EmotionEmitter(FrameProcessor):
    """Async LLM-classifier that emits emotion envelopes onto the data channel.

    Args:
        character: The scenario's `rive_character` slug (e.g. "waiter") used
            to fill the `{character}` placeholder in the classifier prompt.
        openrouter_api_key: API key for OpenRouter. Required — passed in by
            `bot.py` from `Settings.openrouter_api_key`.
    """

    def __init__(
        self,
        *,
        character: str,
        openrouter_api_key: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Fail fast at construction rather than silently 401-ing every
        # classify (which would lock the character in default emotion with
        # no in-call signal — the smoke gate is the only catch).
        if not openrouter_api_key:
            raise ValueError("EmotionEmitter requires a non-empty openrouter_api_key")
        self._character = character
        self._api_key = openrouter_api_key
        self._in_flight: asyncio.Task[None] | None = None
        # Generation guard: bump on every schedule, capture in the task,
        # check before push_frame. Belt-and-braces with `prior.cancel()` —
        # a `push_frame` call may not be a cancellation point in pipecat,
        # so a stale task could otherwise still emit after the next one
        # was scheduled.
        self._generation = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Pass-through is mandatory: the emitter is an *observer*, not a
        # consumer. Any branch that returns without push_frame breaks the
        # downstream pipeline (no LLM, no TTS).
        # `getattr(..., False)` defaults to False so a future pipecat
        # version that drops/renames `finalized` filters interim frames
        # OUT (safer than firing the classifier on every interim word).
        if (
            isinstance(frame, TranscriptionFrame)
            and getattr(frame, "finalized", False)
            and frame.text.strip()
        ):
            await self._schedule_classification(frame.text)

        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        """Drain any in-flight classifier task on pipeline shutdown.

        Without this hook the asyncio task is GC'd while pending →
        `Task was destroyed but it is pending!` log noise + possible
        orphan `httpx.AsyncClient` if cancellation interleaves with
        socket teardown.
        """
        await super().cleanup()
        prior = self._in_flight
        if prior is not None and not prior.done():
            prior.cancel()
            await asyncio.gather(prior, return_exceptions=True)
        self._in_flight = None

    async def _schedule_classification(self, text: str) -> None:
        """Cancel any in-flight task and schedule a fresh one."""
        prior = self._in_flight
        if prior is not None and not prior.done():
            prior.cancel()
            # Await the cancelled task so its push_frame (if any) has resolved
            # before we schedule the replacement — otherwise a stale verdict
            # could land *after* the new one.
            await asyncio.gather(prior, return_exceptions=True)
            logger.info("cancelled stale emotion-classifier task")

        self._generation += 1
        gen = self._generation
        self._in_flight = asyncio.create_task(self._classify_and_emit(text, gen))

    async def _classify_and_emit(self, text: str, generation: int) -> None:
        try:
            result = await asyncio.wait_for(
                self._classify(text),
                timeout=_CLASSIFIER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("emotion classifier timeout")
            return
        except asyncio.CancelledError:
            # Latest-line-wins replacement — let the cancellation propagate.
            raise

        if result is None:
            return

        # Defense in depth: even if a future refactor bypasses
        # `_parse_classifier_output` (e.g. structured-output mode where
        # the SDK returns a dict directly), the emit layer must
        # independently filter reserved emotions.
        if result.get("emotion") not in _ALLOWED_EMOTIONS:
            logger.warning(
                "emit-layer rejected reserved emotion: {!r}", result.get("emotion")
            )
            return

        # Generation check: another `_schedule_classification` may have
        # bumped the generation while we were running. If our generation
        # is stale, the user has moved on — suppress the emit so the
        # newer task's verdict is the only one that lands.
        if generation != self._generation:
            return

        # INFO log on success makes the smoke gate observable from the VPS
        # without needing client-side instrumentation: a tail of journalctl
        # shows each classification verdict in real time.
        logger.info(
            "emotion classifier emit: emotion={} intensity={:.2f}",
            result["emotion"],
            result["intensity"],
        )
        # Emit DOWNSTREAM so the OutputTransportMessageFrame flows toward
        # `transport.output()` (which is downstream of this emitter in the
        # pipeline). UPSTREAM would route the frame back through the LLM
        # aggregator, which doesn't know how to handle it.
        await self.push_frame(
            OutputTransportMessageFrame(message={"type": "emotion", "data": result}),
            FrameDirection.DOWNSTREAM,
        )

    async def _classify(self, text: str) -> dict[str, Any] | None:
        """Call OpenRouter, parse the JSON response, validate the enum value.

        Returns None on any non-recoverable failure (HTTP error, malformed
        JSON, model returned an emotion outside the allowed subset). The
        character then simply stays in its previous Rive emotion state.
        """
        prompt = EMOTION_CLASSIFIER_PROMPT.format(character=self._character, text=text)
        # `reasoning` MUST sit at the top level of the JSON body. `extra_body`
        # is a Python OpenAI-SDK convention that the SDK flattens into the
        # request body before sending; OpenRouter's HTTP API doesn't know the
        # `extra_body` key and silently drops it. Putting `reasoning` there
        # leaves Qwen in default reasoning mode, which takes 5-15 s per call
        # and timed out every classification during the Story 6.3 smoke gate.
        payload = {
            "model": _OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 64,
            "reasoning": {"enabled": False},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    _OPENROUTER_URL, headers=headers, json=payload
                )
        except httpx.HTTPError as exc:
            logger.warning("emotion classifier HTTP error: {}", exc)
            return None

        if response.status_code >= 300:
            logger.warning("emotion classifier non-2xx: {}", response.status_code)
            return None

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("emotion classifier malformed envelope: {}", exc)
            return None

        return _parse_classifier_output(content)


_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _parse_classifier_output(content: str) -> dict[str, Any] | None:
    """Defensively parse the model's response into `{emotion, intensity}`.

    Models occasionally wrap JSON in prose or Markdown fences. We try a
    strict `json.loads` first and fall back to extracting the first
    `{...}` block. Any value outside `_ALLOWED_EMOTIONS` is rejected.
    """
    text = content.strip()
    # Match a properly-paired Markdown fence (with optional `json` tag) and
    # extract the inner content. A regex is safer than `str.strip("`")`,
    # which is set-based and would corrupt JSON containing internal
    # backticks.
    fence_match = _FENCE_RE.match(text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first {...} substring.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning("emotion classifier non-JSON output")
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("emotion classifier non-JSON output")
            return None

    if not isinstance(data, dict):
        logger.warning("emotion classifier output not a dict")
        return None

    emotion = data.get("emotion")
    intensity = data.get("intensity")
    if not isinstance(emotion, str) or emotion not in _ALLOWED_EMOTIONS:
        logger.warning("emotion classifier rejected emotion: {!r}", emotion)
        return None
    try:
        intensity_f = float(intensity) if intensity is not None else 0.5
    except (TypeError, ValueError):
        intensity_f = 0.5
    intensity_f = max(0.0, min(1.0, intensity_f))

    return {"emotion": emotion, "intensity": intensity_f}
