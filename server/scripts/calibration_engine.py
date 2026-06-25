"""Story 6.15 — Scenario validation engine (text-driven, AI-agent-played).

This is the reusable LIBRARY behind `scripts/calibrate_scenario.py`. It validates
a scenario's conversation LOGIC — the checkpoint judge, the persona coherence,
and the difficulty calibration — entirely in TEXT, with AI agents playing the
learner and the character, WITHOUT Soniox / TTS / LiveKit / a phone.

## Why it reuses prod code paths (non-negotiable, AC1)

The whole value of this engine is that a green run means PROD behaves. So it
drives the SAME production code:

  - judge          → `ExchangeClassifier.classify_multi` + the prod
                     `EXCHANGE_CLASSIFIER_MULTI_PROMPT` (Groq strict schema).
  - advance rule   → `checkpoint_manager.advance_goals` (the pure decision the
                     live `CheckpointManager` calls — Story 6.15 Task 10).
  - patience       → `patience_tracker.step_patience` (the pure meter math the
                     live `PatienceTracker.apply_exchange_outcome` calls).
  - system prompt  → `checkpoint_manager.compose_goal_system_instruction` +
                     `prompts.COHERENCE_CHARTER`.
  - scenario data  → `scenarios.{load_scenario_base_prompt,
                     load_scenario_checkpoints, resolve_patience_config,
                     load_scenario_metadata}` (reads the SAME YAML the pipeline
                     reads — the DB copy is never read).

It substitutes ONLY the transport layer — text in/out instead of audio — which
is exactly the layer a text test legitimately stands in for. The character LLM
is driven via the raw `openai` SDK (Deviation #1) because `build_main_llm`
returns a pipeline-only `OpenAILLMService`; it uses the SAME `resolve_llm_*`
helpers + `Settings.character_model` + the shared `CHARACTER_TEMPERATURE` /
`CHARACTER_MAX_TOKENS` constants, so the character is identical to prod's.

## Two test modes (different cost / determinism)

1. **Deterministic golden net** (cheap, regression-grade). Per-checkpoint
   `(user_text → expected verdict)` cases fed straight through `classify_multi`.
   A UNIVERSAL off-topic seed runs against EVERY scenario with zero authoring
   (AC12) — the 2026-05-30 "judge passes everything" bug encoded as a permanent
   assertion. Per-checkpoint cases are LLM-GENERATED from each `success_criteria`
   and reviewed once (AC2 / Deviation #2); they only become gating after a human
   flips `reviewed: true` in the fixture.

2. **Stochastic calibration** (expensive, band-grade). An AI learner-agent plays
   N full conversations; the cooperative completion rate is compared to the
   difficulty band (AC4), and an off_topic learner must NOT complete (the inverse
   guardrail). Rates over N — never a single conversation.

## Cost / determinism (AC6 / Deviation #5)

Live-LLM runs are NOT in the default `pytest` (cost + flake). They require an API
key and run via the CLI, exactly like `benchmark_classifier.py` (gated by file
location + no prod import). The engine's pure LOGIC — band verdict, staleness
hash, ledger, report math, golden gate, learner-prompt building, and the
simulator driven with FAKE LLMs — has unit tests in `tests/test_calibration_engine.py`
that DO run in `pytest`. Classifier calls use temperature 0.1; calibration uses
rates over N. Rough cost: a `calibrate_scenario` run is ~N×2 conversations ×
~K turns × (1 character + 1 learner + 1 classifier) Groq calls ≈ a few US cents
per scenario at N=10 (Groq pricing). The golden net is ~one classify per case.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Protocol

# `server/` on path so the `pipeline.*` prod imports resolve when this module is
# run as a script (mirrors `benchmark_classifier.py`).
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from pipeline import scenarios  # noqa: E402
from pipeline.checkpoint_manager import (  # noqa: E402
    advance_goals,
    compose_goal_system_instruction,
    judgeable_goals,
)
from pipeline.exchange_classifier import ABUSE_KEY, ExchangeClassifier  # noqa: E402
from pipeline.llm_provider import (  # noqa: E402
    CHARACTER_MAX_TOKENS,
    CHARACTER_TEMPERATURE,
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_llm_chat_url,
)
from pipeline.patience_tracker import step_patience  # noqa: E402
from pipeline.prompts import COHERENCE_CHARTER  # noqa: E402
from pipeline.reply_sanitizer import sanitize_reply_text  # noqa: E402

# ============================================================
# Engine version + difficulty bands (AC10 / AC12)
# ============================================================

# Bump this WHENEVER the validation RULES change (a new gate, a stricter
# threshold, a different band, a reworked golden assertion). The smart sweep
# (AC10) revalidates any scenario whose ledger `engine_version` is older than
# this — so tightening the engine forces a global re-check on the next sweep.
# That is the "rigor lives in the engine, constant over time" property Walid
# asked for: scenario authoring never carries the rules.
# Story 6.23 — bumped 1 → 2 so the smart sweep force-revalidates every scenario
# on the next run, surfacing any reactive-but-ungated beat already shipped (a
# reactive beat whose `success_criteria` is a self-contained lexical pattern but
# that carries no `requires` edge). The bump is the global re-check lever.
# Story 6.19 follow-up (2026-06-08) — bumped 2 → 3: all shipped personas were
# rewritten difficulty-NEUTRAL and the easy/medium/hard `_DIFFICULTY_PROMPTS`
# blocks were tightened. `compute_scenario_hash` covers `base_prompt` (so a
# persona edit self-invalidates that scenario), but NOT the code-constant blocks
# — this bump forces the next sweep to revalidate every scenario's difficulty
# band against the new neutral personas + tightened blocks.
# Story 6.27 — bumped 3 → 4: `advance_goals` gained the `implies` superset
# back-fill (a later beat auto-credits the earlier beat it logically subsumes),
# which changes the flip rule for EVERY scenario — the next sweep must
# revalidate all cached PASSes against the new crediting behaviour.
# Story 6.29 (2026-06-10) — bumped 4 → 5: COHERENCE_CHARTER gained three
# system-wide rules (answered-question check, spoken-dialogue-only output,
# example-lines-are-style-not-script) and the character LLM now appends a
# machine-read trailing mood tag (`MOOD_TAG_DIRECTIVE`, stripped before
# TTS/judge/learner by `reply_sanitizer`). Both are code constants OUTSIDE
# `scenario_hash` that change every scenario's character behaviour — the next
# sweep must revalidate all cached PASSes (same precedent as the 6.19
# block-tightening bump).
# Story 6.28 (2026-06-11) — bumped 5 → 6: per-scenario authored difficulty is
# REMOVED (global-only product ruling). Calibration now composes + bands on the
# RUN-level global difficulty (`--difficulty`, default easy) instead of the
# YAML's `metadata.difficulty`, and the loaders' no-difficulty fallback changed
# (authored → server default) — every cached PASS predates that anchor and must
# revalidate on the next sweep.
ENGINE_VERSION = 6

# Difficulty → (low, high) inclusive cooperative-completion band, in percent.
# Source of truth: `difficulty-calibration.md` §4.3 (line 175 —
# "B1 first-attempt survival target | 60-80% | 35-55% | 15-35%"). Rigor-in-
# engine (AC12): the band anchors on the RUN-level global difficulty the
# calibration plays at (Story 6.28 — scenarios carry no authored difficulty;
# the CLI `--difficulty` picks the level, default easy), never written per
# scenario. A scenario MAY add an optional `calibration.target_band:
# [low, high]` to override, but it is not required.
_DIFFICULTY_BANDS: dict[str, tuple[int, int]] = {
    "easy": (60, 80),
    "medium": (35, 55),
    "hard": (15, 35),
}

# A cooperative rate within this many points of a band edge is a ⚠️ warning,
# not a hard fail (Walid 2026-06-01: "±5 pts = warning"). The canonical doc
# uses ±10 for manual calibration; ±5 is the tighter automated gate.
_BAND_WARNING_MARGIN = 5

# Universal off-topic seed (AC12). A clearly off-topic / small-talk turn must
# NOT flip ANY pending goal — it does not ACCOMPLISH a specific objective, so
# every checkpoint must judge it `unmet`. Runs against EVERY scenario with zero
# per-scenario authoring, so a brand-new (un-reviewed) scenario still inherits
# the 2026-05-30 regression guard. These are deliberately generic: none of them
# accomplishes an ordering / confrontation / relationship objective.
_UNIVERSAL_OFFTOPIC_UTTERANCES: tuple[str, ...] = (
    "There are a lot of people here today.",
    "Did you watch the game last night?",
    "My phone battery is almost dead.",
    "It is really cold outside today.",
    "I think the traffic was terrible this morning.",
)

# Learner generation parameters.
_LEARNER_TEMPERATURE = 0.8
_LEARNER_MAX_TOKENS = 80
_LEARNER_STRATEGIES = ("cooperative", "hesitant", "off_topic", "minimal")

# Golden-net positive-case pass threshold (AC9 — "≥ 90 % of messy-POSITIVE
# cases verdict met"). Tolerates the rare low-temperature classifier flip; every
# miss is still logged.
_GOLDEN_POSITIVE_PASS_RATE = 0.90

# Default number of conversations per strategy for calibration (Walid: N=10).
DEFAULT_CALIBRATION_N = 10

_LEDGER_PATH = (
    _HERE.parent.parent
    / "_bmad-output"
    / "implementation-artifacts"
    / "calibration-tests"
    / "validation-ledger.json"
)
_REPORT_DIR = (
    _HERE.parent.parent
    / "_bmad-output"
    / "implementation-artifacts"
    / "calibration-tests"
)
_GOLDEN_FIXTURE_DIR = _HERE.parent / "tests" / "fixtures" / "golden"


# ============================================================
# Injected LLM client (real one wraps openai; tests inject a fake)
# ============================================================


class ChatLLM(Protocol):
    """Minimal async chat interface the engine depends on. The real impl wraps
    `openai.AsyncOpenAI`; unit tests inject a fake with the same signature so no
    network call happens in `pytest` (AC6)."""

    async def chat(
        self,
        messages: list[dict],
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str: ...


class JudgeLLM(Protocol):
    """The judge interface — `ExchangeClassifier.classify_multi`. Tests inject a
    fake returning canned verdict dicts."""

    async def classify_multi(
        self,
        *,
        user_text: str,
        last_character_line: str,
        pending_goals: list[dict],
        scenario_description: str,
    ) -> dict[str, bool | None] | None: ...


class OpenAIChatLLM:
    """Real `ChatLLM` — a thin wrapper over `openai.AsyncOpenAI`.

    Used for BOTH the character and the learner (and golden generation). It
    points at the SAME provider/key the pipeline uses (`resolve_llm_*`) so the
    character matches prod (Story 6.15 Deviation #1). `openai` is already a
    dependency (pipecat's `OpenAILLMService` wraps it).
    """

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def chat(
        self,
        messages: list[dict],
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        full = ([{"role": "system", "content": system}] if system else []) + messages
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=full,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    async def aclose(self) -> None:
        await self._client.close()


@dataclass
class LlmSettings:
    """Minimal LLM config for the dev tools — ONLY the fields `resolve_llm_*` +
    `build_live_clients` read. Defaults mirror `config.Settings` (kept in sync;
    see server/CLAUDE.md §4). Lets `calibrate_scenario` / `build_scenario` run
    with just `GROQ_API_KEY` set, WITHOUT the full prod env (Soniox / LiveKit /
    JWT / Resend), which a text-only harness never touches."""

    groq_api_key: str
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    character_model: str = "llama-3.3-70b-versatile"
    # Story 10.6 — judge migrated off the decommissioned Scout onto gpt-oss-20b
    # (kept in sync with `config.Settings.classifier_model`).
    classifier_model: str = "openai/gpt-oss-20b"
    # Story 6.17 — optional; used by the builder's voice-selection step. Empty
    # locally is fine (it lives on the VPS); voice selection degrades gracefully.
    cartesia_api_key: str = ""


def force_utf8_stdio() -> None:
    """Make stdout/stderr UTF-8 so emoji (✅/❌/⚠️) don't crash on a Windows
    console (default cp1252 raises `UnicodeEncodeError`). Called at CLI start;
    best-effort (a non-reconfigurable stream is left as-is)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001 — best-effort, never fatal
                pass


def load_llm_settings() -> LlmSettings:
    """Read the LLM-only config from the environment (after the CLI has loaded
    `server/.env`). Raises a clear error if no provider key is present — the dev
    tools drive the REAL Groq LLM, so a key is required (but ONLY the key, not
    the rest of the prod env)."""

    def _env(name: str, default: str) -> str:
        return (os.environ.get(name, "") or "").strip() or default

    groq_key = (os.environ.get("GROQ_API_KEY", "") or "").strip()
    llm_key = (os.environ.get("LLM_API_KEY", "") or "").strip()
    if not groq_key and not llm_key:
        raise RuntimeError(
            "No LLM key found. Set GROQ_API_KEY (or LLM_API_KEY) in server/.env "
            "or your shell — this tool drives the real Groq judge + character LLM. "
            "It does NOT need the rest of the prod env (Soniox / LiveKit / JWT)."
        )
    return LlmSettings(
        groq_api_key=groq_key,
        llm_api_key=llm_key,
        llm_base_url=_env("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        character_model=_env("CHARACTER_MODEL", "llama-3.3-70b-versatile"),
        classifier_model=_env("CLASSIFIER_MODEL", "openai/gpt-oss-20b"),
        cartesia_api_key=(os.environ.get("CARTESIA_API_KEY", "") or "").strip(),
    )


def build_live_clients(settings: Any) -> tuple[OpenAIChatLLM, ExchangeClassifier]:
    """Construct the real character/learner LLM + the prod judge from Settings.

    Mirrors `bot.py` wiring: the judge is the prod `ExchangeClassifier`
    (classifier_model, Groq chat URL); the chat LLM is the character model on
    the same provider. Called only by the CLI (live runs); never in `pytest`.
    """
    chat_llm = OpenAIChatLLM(
        api_key=resolve_llm_api_key(settings),
        base_url=resolve_llm_base_url(settings),
        model=settings.character_model,
    )
    judge = ExchangeClassifier(
        api_key=resolve_llm_api_key(settings),
        model=settings.classifier_model,
        base_url=resolve_llm_chat_url(settings),
    )
    return chat_llm, judge


class ResilientJudge:
    """Wraps a `JudgeLLM` to (a) THROTTLE calls (so a batch of hundreds of
    classify calls doesn't trip the provider's requests-per-minute cap) and
    (b) RETRY when the underlying `classify_multi` returns None (infra failure —
    e.g. a 429 rate-limit, which the prod classifier deliberately swallows to
    None and does NOT retry, because a live call must stay fast).

    Dev-tool only: the validation/builder harness fires far more calls, far
    faster, than a real call ever would, so it must back off. A persistent
    non-transient failure (e.g. a 400) still returns None after the retries —
    only a few calls are wasted, and the improved non-2xx body logging surfaces
    the real cause.
    """

    def __init__(
        self,
        inner: JudgeLLM,
        *,
        # Default tuned for Groq's FREE "on_demand" tier = 30 requests/minute
        # (= 1 every 2 s). 2.1 s keeps us just under that so the batch doesn't
        # 429-storm. On a paid Groq tier (much higher RPM) pass a smaller value
        # (e.g. --throttle-ms 200) to run far faster.
        min_interval_s: float = 2.1,
        max_retries: int = 4,
        backoff_s: float = 3.0,
    ) -> None:
        self._inner = inner
        self._min_interval = max(0.0, min_interval_s)
        self._max_retries = max(0, max_retries)
        self._backoff = backoff_s
        self._last_call = 0.0

    async def classify_multi(self, **kwargs) -> dict[str, bool | None] | None:
        for attempt in range(self._max_retries + 1):
            gap = self._min_interval - (time.monotonic() - self._last_call)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last_call = time.monotonic()
            result = await self._inner.classify_multi(**kwargs)
            if result is not None:
                return result
            if attempt < self._max_retries:
                await asyncio.sleep(self._backoff * (attempt + 1))
        return None

    async def close(self) -> None:
        close_fn = getattr(self._inner, "close", None)
        if close_fn is not None:
            await close_fn()


class ResilientChat:
    """Throttle + retry wrapper for a `ChatLLM` (the character + learner LLM).

    The character/learner run on a SEPARATE Groq rate-limit bucket from the judge
    (e.g. 70B vs Scout, each ~30 RPM on the free tier), so the full calibration —
    which makes 2 chat calls per conversation turn — needs the chat path throttled
    too, else it 429s. Unlike the judge (whose 429 is swallowed to None), the chat
    LLM RAISES on a rate-limit, so this catches + backs off + retries, and only
    re-raises if every retry fails. Dev-tool only.
    """

    def __init__(
        self,
        inner: ChatLLM,
        *,
        min_interval_s: float = 2.1,
        max_retries: int = 4,
        backoff_s: float = 3.0,
    ) -> None:
        self._inner = inner
        self._min_interval = max(0.0, min_interval_s)
        self._max_retries = max(0, max_retries)
        self._backoff = backoff_s
        self._last_call = 0.0

    async def chat(
        self,
        messages: list[dict],
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        for attempt in range(self._max_retries + 1):
            gap = self._min_interval - (time.monotonic() - self._last_call)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last_call = time.monotonic()
            try:
                return await self._inner.chat(
                    messages,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception:  # noqa: BLE001 — retry transient errors (e.g. 429)
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(self._backoff * (attempt + 1))
        return ""  # unreachable (loop returns or raises)

    async def aclose(self) -> None:
        aclose_fn = getattr(self._inner, "aclose", None)
        if aclose_fn is not None:
            await aclose_fn()


# ============================================================
# Learner agent (AC3) — plays the USER side
# ============================================================


_STRATEGY_DIRECTIVES: dict[str, str] = {
    "cooperative": (
        "You genuinely try to get through the situation and do what it needs. "
        "Speak naturally in one or two short sentences."
    ),
    "hesitant": (
        "You genuinely try, but you are nervous and your English is messy: "
        "hesitations ('uh', 'um'), false starts, missing articles, short "
        "fragments. Still aim to accomplish what the situation needs, just "
        "clumsily."
    ),
    "off_topic": (
        "You keep making friendly small talk and NEVER actually do what the "
        "other person is asking for. Stay polite and engaged, but never address "
        "the task itself."
    ),
    "minimal": (
        "You answer in as few words as possible — usually one or two words "
        "('yeah', 'ok', 'water', 'sure'). Never elaborate."
    ),
}


def build_learner_system_prompt(
    *, strategy: str, character_title: str, briefing: dict
) -> str:
    """Build the learner-agent system prompt (AC3).

    The learner is given ONLY what a real user plausibly knows — the scenario
    briefing (context / what to expect / vocabulary) and who they are talking to
    — NEVER the `success_criteria` (no cheating to the answer).
    """
    if strategy not in _STRATEGY_DIRECTIVES:
        raise ValueError(
            f"Unknown learner strategy {strategy!r}; expected one of "
            f"{_LEARNER_STRATEGIES}."
        )
    context = (briefing or {}).get("context", "")
    expect = (briefing or {}).get("expect", "")
    vocabulary = (briefing or {}).get("vocabulary", "")
    lines = [
        "You are role-playing the HUMAN side of a spoken English practice "
        "conversation. You are a B1-level English learner (intermediate; you "
        "make mistakes but can communicate).",
        f"You are talking to: {character_title}.",
    ]
    if context:
        lines.append(f"The situation: {context}")
    if expect:
        lines.append(f"What to expect: {expect}")
    if vocabulary:
        lines.append(f"Useful phrases you might use: {vocabulary}")
    lines.append("")
    lines.append(f"How you behave this time: {_STRATEGY_DIRECTIVES[strategy]}")
    lines.append("")
    lines.append(
        "Reply with ONLY your spoken words — no narration, no stage directions, "
        "no quotation marks. Exactly one short turn."
    )
    return "\n".join(lines)


# ============================================================
# Conversation simulator (AC1)
# ============================================================


@dataclass
class TurnRecord:
    user_text: str
    character_reply: str
    verdicts: dict[str, bool | None]
    goals_met: list[str]
    patience: int


@dataclass
class ConversationResult:
    scenario_id: str
    strategy: str
    outcome: str  # "survived" | "character_hung_up" | "in_progress"
    final_patience: int
    goals_met_count: int
    total_goals: int
    turns: list[TurnRecord]

    @property
    def survived(self) -> bool:
        return self.outcome == "survived"


@dataclass
class _ScenarioData:
    """Loaded-once scenario inputs, from the SAME prod loaders the pipeline uses."""

    scenario_id: str
    title: str
    base_prompt: str
    checkpoints: list[dict]
    briefing: dict
    patience: dict


def load_scenario_data(
    scenario_id: str, difficulty: str | None = None
) -> _ScenarioData:
    """Load every input the simulator needs via the prod scenario loaders.

    Story 6.28 — `difficulty` is the RUN-level global difficulty this
    calibration plays at (scenarios carry no authored difficulty anymore); it
    composes the behavior block + patience preset exactly as a live call
    does. None → the prod default (`scenarios.DEFAULT_DIFFICULTY`).
    """
    metadata = scenarios.load_scenario_metadata(scenario_id)
    raw = _load_raw_scenario(scenario_id)
    return _ScenarioData(
        scenario_id=scenario_id,
        title=metadata.get("title", scenario_id),
        base_prompt=scenarios.load_scenario_base_prompt(
            scenario_id, difficulty=difficulty
        ),
        checkpoints=scenarios.load_scenario_checkpoints(scenario_id),
        briefing=(raw.get("briefing") or {}),
        patience=scenarios.resolve_patience_config(scenario_id, difficulty=difficulty),
    )


async def simulate_conversation(
    *,
    scenario_id: str,
    strategy: str,
    character_llm: ChatLLM,
    learner_llm: ChatLLM,
    judge: JudgeLLM,
    data: _ScenarioData | None = None,
    max_turns: int = 12,
) -> ConversationResult:
    """Drive one full text conversation through the PROD code paths (AC1).

    Each round: the character LLM speaks (system instruction recomposed from the
    pending goals exactly as `CheckpointManager` does), the learner replies, the
    prod judge (`classify_multi`) verdicts the turn against all pending goals,
    and the PURE prod decisions (`advance_goals` + `step_patience`) advance the
    state. Ends on `survived` (all goals met), `character_hung_up` (meter hit 0),
    or `in_progress` (hit `max_turns`).
    """
    data = data or load_scenario_data(scenario_id)
    pcfg = data.patience
    meter = int(pcfg["initial_patience"])
    meter_kwargs = {
        "initial_patience": int(pcfg["initial_patience"]),
        "fail_penalty": int(pcfg["fail_penalty"]),
        "recovery_bonus": int(pcfg["recovery_bonus"]),
    }
    goals: dict[str, str] = {cp["id"]: "pending" for cp in data.checkpoints}
    learner_system = build_learner_system_prompt(
        strategy=strategy, character_title=data.title, briefing=data.briefing
    )

    dialogue: list[tuple[str, str]] = []  # ("character" | "user", text)
    turns: list[TurnRecord] = []
    outcome = "in_progress"

    for _ in range(max_turns):
        pending = [cp for cp in data.checkpoints if goals[cp["id"]] == "pending"]
        # Story 6.23 — golden==prod coupling (THE load-bearing one). The judge
        # payload is the GATED set (`judgeable_goals` — the SAME helper prod uses
        # in `_classify_and_flip_goals`), so a reactive beat gated in prod is
        # gated here too; if the harness judged the un-gated `pending` instead,
        # gated beats would be credited in validation but not prod (false-green).
        # The character steering prompt below stays UN-gated (`pending`), exactly
        # like prod's `_update_system_instruction`.
        judgeable = judgeable_goals(data.checkpoints, goals)
        system_instruction = compose_goal_system_instruction(
            base_prompt=data.base_prompt,
            coherence_charter=COHERENCE_CHARTER,
            pending_goals=pending,
        )
        char_messages = [
            {"role": "assistant" if who == "character" else "user", "content": text}
            for who, text in dialogue
        ]
        character_line = await character_llm.chat(
            char_messages,
            system=system_instruction,
            temperature=CHARACTER_TEMPERATURE,
            max_tokens=CHARACTER_MAX_TOKENS,
        )
        # Story 6.29 — golden==prod: `compose_goal_system_instruction` now
        # appends MOOD_TAG_DIRECTIVE (the character co-generates a trailing
        # `<mood:...>` tag) and prod strips it — plus `(...)`/`*...*` spans —
        # in `reply_sanitizer` before the text reaches TTS / transcript /
        # judge. Mirror that here with the SAME pure helper so the learner
        # and the judge see exactly what a prod user would hear. A reply that
        # sanitizes to empty is prod's rare silent turn; keep the raw line as
        # a defensive fallback so the simulated dialogue never goes blank.
        clean_line, _mood = sanitize_reply_text(character_line)
        character_line = clean_line or character_line
        dialogue.append(("character", character_line))

        learner_messages = [
            {"role": "user" if who == "character" else "assistant", "content": text}
            for who, text in dialogue
        ]
        user_text = await learner_llm.chat(
            learner_messages,
            system=learner_system,
            temperature=_LEARNER_TEMPERATURE,
            max_tokens=_LEARNER_MAX_TOKENS,
        )
        dialogue.append(("user", user_text))

        # Story 6.23 — judge only the GATED set (see the `judgeable` derivation
        # above). When every pending beat is reactive-and-gated, there is
        # nothing to judge this turn: record an empty verdict (no flips, no
        # patience change) and let the character keep pursuing the trigger.
        if judgeable:
            verdicts = await judge.classify_multi(
                user_text=user_text,
                last_character_line=character_line,
                pending_goals=[
                    {"id": cp["id"], "success_criteria": cp["success_criteria"]}
                    for cp in judgeable
                ],
                scenario_description=data.title,
            )
            # FR37 — drop the abuse flag (irrelevant to GOAL calibration). It must
            # NOT reach `advance_goals`, where a `False` would read as a goal
            # "unmet" → spurious "fail". golden==prod for the goal logic holds.
            if verdicts is not None:
                verdicts.pop(ABUSE_KEY, None)
        else:
            verdicts = {}
        recorded_verdicts: dict[str, bool | None] = verdicts if verdicts else {}
        if verdicts is not None:
            # Story 6.27 — thread the checkpoints so the harness applies the
            # SAME `implies` back-fill rule prod does (golden==prod).
            adv = advance_goals(goals, verdicts, checkpoints=data.checkpoints)
            goals = adv.new_goals
            if adv.all_met:
                outcome = "survived"
            elif adv.outcome == "fail":
                meter = step_patience(meter, success=False, **meter_kwargs)
                if meter == 0:
                    outcome = "character_hung_up"
            elif adv.outcome == "success":
                meter = step_patience(meter, success=True, **meter_kwargs)
            # "neutral" (all unsure / infra-None) → meter unchanged.

        turns.append(
            TurnRecord(
                user_text=user_text,
                character_reply=character_line,
                verdicts=recorded_verdicts,
                goals_met=[gid for gid, st in goals.items() if st == "met"],
                patience=meter,
            )
        )
        if outcome != "in_progress":
            break

    return ConversationResult(
        scenario_id=scenario_id,
        strategy=strategy,
        outcome=outcome,
        final_patience=meter,
        goals_met_count=sum(1 for st in goals.values() if st == "met"),
        total_goals=len(data.checkpoints),
        turns=turns,
    )


# ============================================================
# Golden net (AC2 / AC9 / AC12)
# ============================================================


@dataclass
class GoldenCase:
    checkpoint_id: str
    kind: str  # "negative" | "positive"
    source: str  # "seed" | "fixture"
    character_line: str
    user_text: str
    note: str = ""


@dataclass
class GoldenCaseResult:
    case: GoldenCase
    verdict: bool | None  # True=met / False=unmet / None=unsure-or-infra
    status: str  # "pass" | "fail" | "warn"


@dataclass
class GoldenResult:
    scenario_id: str
    passed: bool
    reviewed_fixture: bool
    fixture_present: bool
    negative_total: int
    negative_failures: list[GoldenCaseResult]
    negative_warnings: list[GoldenCaseResult]
    positive_total: int
    positive_met: int
    positive_misses: list[GoldenCaseResult]
    all_results: list[GoldenCaseResult]
    # Story 6.23 — human-readable descriptions of any reactive beat that the
    # pure `requires` gate fails to gate correctly (a `requires` beat that is
    # judgeable before its trigger is met, or stays gated after it). Non-empty
    # forces `passed=False`. NON-LLM (a pure function over the gate), so it runs
    # for free even in `--golden-only`.
    requires_gating_failures: list[str] = field(default_factory=list)
    # Story 6.27 — same idea for the `implies` superset back-fill: any beat
    # whose `implies` edge fails to back-fill its earlier target through the
    # REAL shared `advance_goals`. Non-empty forces `passed=False`; non-LLM.
    implies_backfill_failures: list[str] = field(default_factory=list)


def requires_gating_failures(checkpoints: list[dict]) -> list[str]:
    """Pure premature-credit assertion over the Story 6.23 reactive gate (AC6).

    For every beat carrying a ``requires`` edge, assert that the prod gate
    (``checkpoint_manager.judgeable_goals`` — the SAME function prod uses)
    behaves:

      1. with NO beat met, the reactive beat is NOT judgeable (it cannot be
         credited before its trigger) — this is the call_id=222 incident as a
         permanent assertion; and
      2. with ONLY its required beat met, the reactive beat BECOMES judgeable
         (the gate opens once the trigger fires, so the trap can still land).

    Returns a list of human-readable failure descriptions (empty == OK). No LLM,
    no I/O — a pure function over the gate, so it runs even in ``--golden-only``
    and costs nothing. The loader already rejected malformed edges, so on a
    valid scenario this is a cheap belt-and-suspenders proof that the gate wired
    up as intended.
    """
    failures: list[str] = []
    all_pending = {cp["id"]: "pending" for cp in checkpoints}
    for cp in checkpoints:
        required = cp.get("requires")
        if required is None:
            continue
        # (1) gated while the trigger is unmet.
        judgeable_ids = {c["id"] for c in judgeable_goals(checkpoints, all_pending)}
        if cp["id"] in judgeable_ids:
            failures.append(
                f"{cp['id']!r} is judgeable before its required beat {required!r} "
                f"is met (reactive beat would credit out of context)."
            )
        # (2) ungated once the trigger is met.
        trigger_met = dict(all_pending)
        trigger_met[required] = "met"
        opened_ids = {c["id"] for c in judgeable_goals(checkpoints, trigger_met)}
        if cp["id"] not in opened_ids:
            failures.append(
                f"{cp['id']!r} stays gated even after its required beat "
                f"{required!r} is met (the trap could never land)."
            )
    return failures


def implies_backfill_failures(checkpoints: list[dict]) -> list[str]:
    """Pure back-fill assertion over the Story 6.27 `implies` edge.

    For every beat carrying an ``implies`` edge, simulate that beat flipping
    met (all others pending) through the REAL shared
    ``checkpoint_manager.advance_goals`` — NOT a re-implementation — and
    assert the implied earlier beat (1) lands ``met`` in the same turn and
    (2) rides ``flipped_ids`` (so the prod per-flip envelope loop emits a
    `checkpoint_advanced` for it and the HUD ticks both).

    Returns a list of human-readable failure descriptions (empty == OK). No
    LLM, no I/O — sibling of ``requires_gating_failures``, runs even in
    ``--golden-only`` and costs nothing. The loader already rejected
    malformed edges; this is the belt-and-suspenders proof that the engine
    wires the back-fill up as intended.
    """
    failures: list[str] = []
    for cp in checkpoints:
        implied = cp.get("implies")
        if implied is None:
            continue
        all_pending = {c["id"]: "pending" for c in checkpoints}
        adv = advance_goals(all_pending, {cp["id"]: True}, checkpoints=checkpoints)
        if adv.new_goals.get(implied) != "met":
            failures.append(
                f"{cp['id']!r} flipping met does NOT back-fill its implied "
                f"earlier beat {implied!r} (the `implies` edge is wired wrong)."
            )
        elif implied not in adv.flipped_ids:
            failures.append(
                f"{cp['id']!r} back-fills {implied!r} but the back-filled id "
                f"does not ride `flipped_ids` (no `checkpoint_advanced` "
                f"envelope would be emitted — the HUD would never tick it)."
            )
    return failures


def build_seed_cases(checkpoints: list[dict]) -> list[GoldenCase]:
    """Universal off-topic negatives — one per (checkpoint × seed utterance).

    Zero per-scenario authoring; always gating (AC12). `character_line` is empty
    so the judge evaluates the off-topic text purely against the objective's
    `success_criteria` — the hardest, most context-free form of the assertion.
    """
    cases: list[GoldenCase] = []
    for cp in checkpoints:
        for utterance in _UNIVERSAL_OFFTOPIC_UTTERANCES:
            cases.append(
                GoldenCase(
                    checkpoint_id=cp["id"],
                    kind="negative",
                    source="seed",
                    character_line="",
                    user_text=utterance,
                    note="universal off-topic seed (must be unmet)",
                )
            )
    return cases


def load_golden_fixture(
    scenario_id: str, *, fixture_dir: pathlib.Path | None = None
) -> dict | None:
    """Load the per-scenario golden fixture, or None if absent.

    A corrupt fixture fails LOUD (not silently treated as absent) — a gating
    `reviewed: true` fixture that silently vanished would drop its positive
    coverage and manufacture a false PASS.
    """
    fixture_dir = fixture_dir or _GOLDEN_FIXTURE_DIR
    path = fixture_dir / f"{scenario_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Golden fixture {path} is not valid JSON: {exc}") from exc


def _fixture_cases(fixture: dict) -> list[GoldenCase]:
    out: list[GoldenCase] = []
    for i, c in enumerate(fixture.get("cases", [])):
        missing = [k for k in ("checkpoint_id", "kind", "user_text") if k not in c]
        if missing:
            raise ValueError(
                f"Golden fixture case #{i} is missing required field(s) "
                f"{missing}: {c!r}"
            )
        out.append(
            GoldenCase(
                checkpoint_id=c["checkpoint_id"],
                kind=c["kind"],
                source="fixture",
                character_line=c.get("character_line", ""),
                user_text=c["user_text"],
                note=c.get("note", ""),
            )
        )
    return out


def evaluate_golden_results(
    scenario_id: str,
    results: list[GoldenCaseResult],
    *,
    reviewed_fixture: bool,
    fixture_present: bool,
) -> GoldenResult:
    """Pure gate over already-classified golden cases (AC9).

    - NEGATIVE cases (off-topic): `met` (True) is a hard FAIL (an off-topic that
      passes is the exact 2026-05-30 bug). `unmet` (False) passes; `unsure`
      (None) is a ⚠️ warning (safe — does not flip the goal — but logged).
    - POSITIVE cases (only gating when the fixture is reviewed): `met` passes;
      anything else is a miss. The gate requires ≥ 90 % met.

    Seed negatives are ALWAYS gating. Fixture cases gate only when
    `reviewed_fixture` is True (un-reviewed labels are not human-trusted yet).
    """
    negatives = [r for r in results if r.case.kind == "negative"]
    positives = [r for r in results if r.case.kind == "positive"]

    gating_negatives = [
        r for r in negatives if r.case.source == "seed" or reviewed_fixture
    ]
    negative_failures = [r for r in gating_negatives if r.verdict is True]
    negative_warnings = [r for r in gating_negatives if r.verdict is None]

    gating_positives = [r for r in positives if reviewed_fixture]
    positive_met = sum(1 for r in gating_positives if r.verdict is True)
    positive_misses = [r for r in gating_positives if r.verdict is not True]
    positive_total = len(gating_positives)

    negatives_ok = not negative_failures
    positives_ok = (
        positive_total == 0
        or (positive_met / positive_total) >= _GOLDEN_POSITIVE_PASS_RATE
    )
    passed = negatives_ok and positives_ok

    return GoldenResult(
        scenario_id=scenario_id,
        passed=passed,
        reviewed_fixture=reviewed_fixture,
        fixture_present=fixture_present,
        negative_total=len(gating_negatives),
        negative_failures=negative_failures,
        negative_warnings=negative_warnings,
        positive_total=positive_total,
        positive_met=positive_met,
        positive_misses=positive_misses,
        all_results=results,
    )


async def run_golden(
    *,
    scenario_id: str,
    judge: JudgeLLM,
    data: _ScenarioData | None = None,
    fixture_dir: pathlib.Path | None = None,
) -> GoldenResult:
    """Run the golden net: universal seed (always) + reviewed fixture cases.

    Each case is fed through the prod `classify_multi` with a SINGLE pending
    goal (the case's checkpoint) so the verdict is unambiguous.
    """
    data = data or load_scenario_data(scenario_id)
    by_id = {cp["id"]: cp for cp in data.checkpoints}

    cases = build_seed_cases(data.checkpoints)
    fixture = load_golden_fixture(scenario_id, fixture_dir=fixture_dir)
    reviewed_fixture = bool(fixture and fixture.get("reviewed"))
    if fixture:
        cases.extend(_fixture_cases(fixture))

    results: list[GoldenCaseResult] = []
    for case in cases:
        cp = by_id.get(case.checkpoint_id)
        if cp is None:
            # Fixture references a checkpoint that no longer exists — surface it
            # as a failing case so the reviewer fixes the fixture.
            results.append(
                GoldenCaseResult(
                    case=case,
                    verdict=None,
                    status="fail",
                )
            )
            continue
        verdicts = await judge.classify_multi(
            user_text=case.user_text,
            last_character_line=case.character_line,
            pending_goals=[
                {"id": cp["id"], "success_criteria": cp["success_criteria"]}
            ],
            scenario_description=data.title,
        )
        # FR37 — defensive: drop the abuse flag (the golden net only reads the
        # single goal's verdict, but keep the harness clean of the reserved key).
        if verdicts is not None:
            verdicts.pop(ABUSE_KEY, None)
        verdict = None if verdicts is None else verdicts.get(cp["id"])
        results.append(
            GoldenCaseResult(
                case=case, verdict=verdict, status=_golden_status(case, verdict)
            )
        )

    golden = evaluate_golden_results(
        scenario_id,
        results,
        reviewed_fixture=reviewed_fixture,
        fixture_present=fixture is not None,
    )
    # Story 6.23 (AC6) — fold in the pure reactive-gating assertion. A gating
    # failure is a hard FAIL (a reactive beat that could credit out of context
    # is exactly the bug class this story removes), and it runs in --golden-only
    # because it is non-LLM.
    gating_failures = requires_gating_failures(data.checkpoints)
    if gating_failures:
        golden = replace(golden, passed=False, requires_gating_failures=gating_failures)
    # Story 6.27 (AC2) — fold in the pure `implies` back-fill assertion the
    # same way (a broken back-fill re-opens the call_id=266 stranded-beat
    # class). Non-LLM, runs in --golden-only too.
    backfill_failures = implies_backfill_failures(data.checkpoints)
    if backfill_failures:
        golden = replace(
            golden, passed=False, implies_backfill_failures=backfill_failures
        )
    return golden


def golden_inconclusive(golden: GoldenResult) -> bool:
    """True when a golden run was dominated by 'unsure' verdicts (a rate-limited
    judge) so its PASS/FAIL is not trustworthy — callers should report
    INCONCLUSIVE, not PASS. Story 6.17 / review 2026-06-02: the wizard already
    guards this; this shared helper lets the `build_scenario --validate` CLI path
    be honest too (an all-unsure run had 0 negative_failures → golden.passed=True
    → a FALSE pass)."""
    return bool(golden.negative_warnings) and len(golden.negative_warnings) >= max(
        1, golden.negative_total // 2
    )


def _golden_status(case: GoldenCase, verdict: bool | None) -> str:
    if case.kind == "negative":
        if verdict is True:
            return "fail"
        if verdict is None:
            return "warn"
        return "pass"
    # positive
    return "pass" if verdict is True else "fail"


# ============================================================
# Golden generation (AC2 / Deviation #2) — auto-gen + review
# ============================================================

_GOLDEN_GEN_PROMPT = """\
You write test cases for an English-practice scenario's checkpoint judge.

Scenario: {title}
The character the learner talks to is described by this objective:
"{success_criteria}"

Produce realistic SHORT user utterances a B1 English learner might say, in two
groups:

- "positives": 3 utterances that GENUINELY accomplish the objective above, but
  in MESSY, hesitant, informal, or fragmented English (missing articles, "uh",
  short phrases, synonyms / brand names). They must clearly do what the objective
  asks.
- "negatives": 3 utterances that are coherent and polite but DO NOT accomplish
  this specific objective (off-topic, tangential, or addressing something else).

Also give "character_line": one short line the character would plausibly say
right before the learner's turn for this objective.

Respond with STRICT JSON only, no prose, no Markdown fences:
{{"character_line": "...", "positives": ["...", "...", "..."], "negatives": ["...", "...", "..."]}}
"""


async def generate_golden_fixture(
    *,
    scenario_id: str,
    generator_llm: ChatLLM,
    data: _ScenarioData | None = None,
) -> dict:
    """LLM-generate a per-checkpoint golden fixture (reviewed: false).

    Walid's choice (AC2 / Deviation #2): the engine fabricates candidate cases
    from each `success_criteria`; a human (or an agent) reviews ONCE and flips
    `reviewed: true` to make them gating. Until then only the universal seed
    gates, so the scenario still has the 2026-05-30 regression guard.
    """
    data = data or load_scenario_data(scenario_id)
    cases: list[dict] = []
    for cp in data.checkpoints:
        prompt = _GOLDEN_GEN_PROMPT.format(
            title=data.title, success_criteria=cp["success_criteria"].strip()
        )
        raw = await generator_llm.chat(
            [{"role": "user", "content": prompt}],
            system="You generate concise, realistic test data. JSON only.",
            temperature=0.4,
            max_tokens=400,
        )
        parsed = _parse_generator_output(raw)
        character_line = parsed.get("character_line", "") if parsed else ""
        for kind in ("positive", "negative"):
            for utterance in (parsed or {}).get(f"{kind}s", []):
                if isinstance(utterance, str) and utterance.strip():
                    cases.append(
                        {
                            "checkpoint_id": cp["id"],
                            "kind": kind,
                            "character_line": character_line,
                            "user_text": utterance.strip(),
                            "note": "LLM-generated — REVIEW before trusting",
                        }
                    )
    return {
        "scenario_id": scenario_id,
        "engine_version": ENGINE_VERSION,
        "reviewed": False,
        "cases": cases,
    }


def _parse_generator_output(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        # strip a Markdown fence
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_golden_fixture(
    fixture: dict, *, fixture_dir: pathlib.Path | None = None
) -> pathlib.Path:
    fixture_dir = fixture_dir or _GOLDEN_FIXTURE_DIR
    fixture_dir.mkdir(parents=True, exist_ok=True)
    path = fixture_dir / f"{fixture['scenario_id']}.json"
    path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ============================================================
# Calibration (AC4 / AC9) — band check + off_topic guardrail
# ============================================================


@dataclass
class CalibrationResult:
    scenario_id: str
    difficulty: str
    band: tuple[int, int]
    n: int
    cooperative_rate: float
    offtopic_rate: float
    band_verdict: str  # in_band | warning_low | warning_high | too_hard | too_easy
    guardrail_ok: bool
    passed: bool
    cooperative_runs: list[ConversationResult] = field(default_factory=list)
    offtopic_runs: list[ConversationResult] = field(default_factory=list)


def band_for_difficulty(
    difficulty: str, *, override: tuple[int, int] | None = None
) -> tuple[int, int]:
    if override is not None:
        return override
    if difficulty not in _DIFFICULTY_BANDS:
        raise ValueError(
            f"Unknown difficulty {difficulty!r}; expected one of "
            f"{sorted(_DIFFICULTY_BANDS)}."
        )
    return _DIFFICULTY_BANDS[difficulty]


def classify_band(rate: float, band: tuple[int, int]) -> str:
    """Classify a completion rate against a band (AC9). `in_band` / a ±margin
    `warning_*` (still passes) / `too_hard` (below) / `too_easy` (above)."""
    low, high = band
    if low <= rate <= high:
        return "in_band"
    if low - _BAND_WARNING_MARGIN <= rate < low:
        return "warning_low"
    if high < rate <= high + _BAND_WARNING_MARGIN:
        return "warning_high"
    if rate < low:
        return "too_hard"
    return "too_easy"


def evaluate_calibration(
    *,
    scenario_id: str,
    difficulty: str,
    cooperative_runs: list[ConversationResult],
    offtopic_runs: list[ConversationResult],
    band_override: tuple[int, int] | None = None,
) -> CalibrationResult:
    """Pure calibration gate over completed runs (AC4 / AC9).

    `difficulty` is the RUN-level global difficulty the conversations were
    composed at (Story 6.28) — it anchors the band, nothing else.
    """
    band = band_for_difficulty(difficulty, override=band_override)
    n = len(cooperative_runs)
    coop_rate = 100.0 * sum(1 for r in cooperative_runs if r.survived) / n if n else 0.0
    offt_n = len(offtopic_runs)
    offt_rate = (
        100.0 * sum(1 for r in offtopic_runs if r.survived) / offt_n if offt_n else 0.0
    )
    band_verdict = classify_band(coop_rate, band)
    guardrail_ok = offt_rate == 0.0
    passed = band_verdict in ("in_band", "warning_low", "warning_high") and guardrail_ok
    return CalibrationResult(
        scenario_id=scenario_id,
        difficulty=difficulty,
        band=band,
        n=n,
        cooperative_rate=coop_rate,
        offtopic_rate=offt_rate,
        band_verdict=band_verdict,
        guardrail_ok=guardrail_ok,
        passed=passed,
        cooperative_runs=cooperative_runs,
        offtopic_runs=offtopic_runs,
    )


async def run_calibration(
    *,
    scenario_id: str,
    character_llm: ChatLLM,
    learner_llm: ChatLLM,
    judge: JudgeLLM,
    n: int = DEFAULT_CALIBRATION_N,
    data: _ScenarioData | None = None,
    max_turns: int = 12,
    difficulty: str | None = None,
) -> CalibrationResult:
    """Run N cooperative + N off_topic conversations and gate (AC4).

    Story 6.28 — `difficulty` is the RUN-level global difficulty: it anchors
    the band (`band_for_difficulty`) and, when `data` is not pre-loaded,
    composes the scenario at that level. None → the prod default. A caller
    that passes `data=` must have composed it at the SAME difficulty.
    """
    if difficulty is None:
        difficulty = scenarios.DEFAULT_DIFFICULTY
    data = data or load_scenario_data(scenario_id, difficulty=difficulty)

    # A cooperative learner needs at least one turn per checkpoint to be able to
    # complete the scenario AT ALL — plus headroom for off-topic slips. Without
    # this, a 20-checkpoint scenario judged with the default 12 turns could never
    # reach all-met → a false "too_hard" verdict (Story 6.16). Scale up; never
    # shrink an explicit larger override.
    effective_max_turns = max(max_turns, len(data.checkpoints) + 8)

    async def _runs(strategy: str) -> list[ConversationResult]:
        out = []
        for _ in range(n):
            out.append(
                await simulate_conversation(
                    scenario_id=scenario_id,
                    strategy=strategy,
                    character_llm=character_llm,
                    learner_llm=learner_llm,
                    judge=judge,
                    data=data,
                    max_turns=effective_max_turns,
                )
            )
        return out

    cooperative_runs = await _runs("cooperative")
    offtopic_runs = await _runs("off_topic")
    return evaluate_calibration(
        scenario_id=scenario_id,
        difficulty=difficulty,
        cooperative_runs=cooperative_runs,
        offtopic_runs=offtopic_runs,
    )


# ============================================================
# Scenario verdict (AC9) — golden + calibration → PASS/FAIL
# ============================================================


@dataclass
class ScenarioVerdict:
    scenario_id: str
    passed: bool
    golden: GoldenResult | None
    calibration: CalibrationResult | None
    scenario_hash: str
    skipped: bool = False  # cached PASS from the ledger (AC10)
    reason: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "CACHED PASS"
        return "PASS" if self.passed else "FAIL"


def combine_verdict(
    *,
    scenario_id: str,
    scenario_hash: str,
    golden: GoldenResult,
    calibration: CalibrationResult,
) -> ScenarioVerdict:
    return ScenarioVerdict(
        scenario_id=scenario_id,
        passed=golden.passed and calibration.passed,
        golden=golden,
        calibration=calibration,
        scenario_hash=scenario_hash,
    )


# ============================================================
# Staleness hash (AC10)
# ============================================================


def _load_raw_scenario(scenario_id: str) -> dict:
    import yaml

    path = scenarios._SCENARIO_INDEX.get(scenario_id)
    if path is None:
        raise FileNotFoundError(
            f"Unknown scenario_id: {scenario_id!r}. Known ids: "
            f"{sorted(scenarios._SCENARIO_INDEX)}."
        )
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# The YAML metadata keys whose VALUES change runtime judge / patience behaviour.
# Cosmetic keys (tts_voice_id, rive_character, is_free, content_warning,
# language_focus) are deliberately EXCLUDED so a voice swap doesn't burn a re-run.
_BEHAVIOUR_META_KEYS = (
    "patience_start",
    "fail_penalty",
    "silence_penalty",
    "recovery_bonus",
    "silence_prompt_seconds",
    "silence_hangup_seconds",
    "ladder_impatience_seconds",
    "escalation_thresholds",
)


def compute_scenario_hash(scenario_id: str) -> str:
    """SHA-256 over ONLY the behaviour-affecting fields (AC10 / Deviation #4).

    Covers: base_prompt, every checkpoint's id/prompt_segment/success_criteria
    (in order), the 8 patience overrides, briefing, and exit_lines. Excludes
    cosmetic fields (incl. `display_order` — hub ordering changes no runtime
    behaviour) so editing a TTS voice id does NOT force an (expensive)
    revalidation. `--force` is the escape hatch when you want one anyway.
    """
    raw = _load_raw_scenario(scenario_id)
    metadata = raw.get("metadata") or {}
    # Story 6.19 follow-up — the per-difficulty behavior blocks are a CODE constant
    # (`scenarios._DIFFICULTY_PROMPTS`), composed onto the persona at runtime, so
    # they affect EVERY scenario's behaviour but live in no YAML field above. Fold
    # them into the hash so editing a block self-invalidates cached PASSes (same
    # reasoning as the Story 6.23 `requires` inclusion) — no longer relying solely
    # on a manual ENGINE_VERSION bump to catch a difficulty-block edit.
    from pipeline.scenarios import _DIFFICULTY_PROMPTS

    projection = {
        "base_prompt": raw.get("base_prompt", ""),
        "checkpoints": [
            {
                "id": cp.get("id"),
                "prompt_segment": cp.get("prompt_segment"),
                "success_criteria": cp.get("success_criteria"),
                # Story 6.23 — the reactive-gating edge is behaviour-affecting:
                # adding/removing a `requires` changes WHEN a beat is judgeable,
                # so it must invalidate the cached PASS (else editing a gate
                # would not trigger a revalidation).
                "requires": cp.get("requires"),
                # Story 6.27 — the superset back-fill edge is behaviour-
                # affecting too: adding/removing an `implies` changes WHICH
                # beats credit on a turn, so it must invalidate the cached PASS.
                "implies": cp.get("implies"),
            }
            for cp in (raw.get("checkpoints") or [])
        ],
        "metadata": {k: metadata.get(k) for k in _BEHAVIOUR_META_KEYS},
        "briefing": raw.get("briefing") or {},
        "exit_lines": raw.get("exit_lines") or {},
        "difficulty_blocks": _DIFFICULTY_PROMPTS,
    }
    canonical = json.dumps(projection, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ============================================================
# Validation ledger (AC10)
# ============================================================


def load_ledger(*, path: pathlib.Path | None = None) -> dict:
    path = path or _LEDGER_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_ledger(ledger: dict, *, path: pathlib.Path | None = None) -> None:
    path = path or _LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")


def is_cached_pass(ledger: dict, scenario_id: str, current_hash: str) -> bool:
    """A scenario may be skipped on a sweep iff the ledger has a PASS entry whose
    `scenario_hash` matches the current YAML AND whose `engine_version` is the
    current one (AC10): never-validated, content-changed, or rules-changed all
    force a re-run.
    """
    entry = ledger.get(scenario_id)
    if not entry:
        return False
    return (
        entry.get("verdict") == "PASS"
        and entry.get("scenario_hash") == current_hash
        and entry.get("engine_version") == ENGINE_VERSION
    )


def record_verdict(
    ledger: dict, verdict: ScenarioVerdict, *, report_path: str = ""
) -> dict:
    """Write/update the ledger entry for a freshly-computed verdict."""
    ledger = dict(ledger)
    ledger[verdict.scenario_id] = {
        "scenario_id": verdict.scenario_id,
        "scenario_hash": verdict.scenario_hash,
        "engine_version": ENGINE_VERSION,
        "validated_at": _now_iso(),
        "verdict": "PASS" if verdict.passed else "FAIL",
        "report_path": report_path,
        "golden_summary": _golden_summary(verdict.golden),
        "calibration_summary": _calibration_summary(verdict.calibration),
    }
    return ledger


def _golden_summary(golden: GoldenResult | None) -> dict:
    if golden is None:
        return {}
    return {
        "passed": golden.passed,
        "reviewed_fixture": golden.reviewed_fixture,
        "negative_total": golden.negative_total,
        "negative_failures": len(golden.negative_failures),
        "negative_warnings": len(golden.negative_warnings),
        "positive_total": golden.positive_total,
        "positive_met": golden.positive_met,
        # Story 6.23 — reactive-gating assertion failures (AC6).
        "requires_gating_failures": list(golden.requires_gating_failures),
        # Story 6.27 — `implies` back-fill assertion failures (AC2).
        "implies_backfill_failures": list(golden.implies_backfill_failures),
    }


def _calibration_summary(cal: CalibrationResult | None) -> dict:
    if cal is None:
        return {}
    return {
        "passed": cal.passed,
        "difficulty": cal.difficulty,
        "band": list(cal.band),
        "n": cal.n,
        "cooperative_rate": round(cal.cooperative_rate, 1),
        "offtopic_rate": round(cal.offtopic_rate, 1),
        "band_verdict": cal.band_verdict,
        "guardrail_ok": cal.guardrail_ok,
    }


# ============================================================
# Reports + copy-pasteable failure diagnostic (AC11)
# ============================================================


def build_report(verdict: ScenarioVerdict) -> dict:
    """Pure JSON-serializable report for one scenario verdict."""
    return {
        "generated_at": _now_iso(),
        "scenario_id": verdict.scenario_id,
        "engine_version": ENGINE_VERSION,
        "scenario_hash": verdict.scenario_hash,
        "verdict": "PASS" if verdict.passed else "FAIL",
        "golden": _golden_report(verdict.golden),
        "calibration": _calibration_summary(verdict.calibration),
        "calibration_samples": _calibration_samples(verdict.calibration),
    }


def _golden_report(golden: GoldenResult | None) -> dict:
    if golden is None:
        return {}
    summary = _golden_summary(golden)
    summary["negative_failure_cases"] = [
        {
            "checkpoint_id": r.case.checkpoint_id,
            "user_text": r.case.user_text,
            "verdict": _verdict_word(r.verdict),
            "source": r.case.source,
        }
        for r in golden.negative_failures
    ]
    summary["positive_miss_cases"] = [
        {
            "checkpoint_id": r.case.checkpoint_id,
            "user_text": r.case.user_text,
            "verdict": _verdict_word(r.verdict),
        }
        for r in golden.positive_misses
    ]
    return summary


def _calibration_samples(cal: CalibrationResult | None, *, k: int = 2) -> dict:
    """A couple of sampled transcripts per strategy for eyeballing (AC4)."""
    if cal is None:
        return {}

    def _sample(runs: list[ConversationResult]) -> list[dict]:
        return [
            {
                "outcome": r.outcome,
                "goals_met": f"{r.goals_met_count}/{r.total_goals}",
                "final_patience": r.final_patience,
                "transcript": [
                    {"character": t.character_reply, "user": t.user_text}
                    for t in r.turns
                ],
            }
            for r in runs[:k]
        ]

    return {
        "cooperative": _sample(cal.cooperative_runs),
        "off_topic": _sample(cal.offtopic_runs),
    }


def write_report(
    verdict: ScenarioVerdict, *, report_dir: pathlib.Path | None = None
) -> pathlib.Path:
    report_dir = report_dir or _REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = _now_compact()
    path = report_dir / f"calibrate_{verdict.scenario_id}_{ts}.json"
    path.write_text(
        json.dumps(build_report(verdict), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def format_failure_report(verdict: ScenarioVerdict, *, report_path: str = "") -> str:
    """Self-contained Markdown a human OR an AI agent can act on (AC11).

    Names the exact failing cases + the YAML field paths to edit + a likely
    cause / fix per failure class + the reproduction command. Designed to be
    pasted (alone) into an AI agent that will fix the scenario.
    """
    sid = verdict.scenario_id
    lines: list[str] = []
    lines.append(f"# ❌ Scenario validation FAILED: `{sid}`")
    lines.append("")
    lines.append(
        f"Edit `server/pipeline/scenarios/` for `{sid}`, then re-run: "
        f"`python scripts/calibrate_scenario.py {sid} --force`"
    )
    if report_path:
        lines.append(f"Full JSON report: `{report_path}`")
    lines.append("")

    golden = verdict.golden
    if golden and golden.requires_gating_failures:
        lines.append(
            "## Reactive-gating failures (Story 6.23 `requires` edge wired wrong)"
        )
        lines.append("")
        lines.append(
            "A beat carrying `requires: <id>` must be gated (un-judgeable) until "
            "its required beat is met, and become judgeable once it is. These "
            "edges are wired wrong — fix the `requires:` field in "
            f"`server/pipeline/scenarios/` for `{sid}`:"
        )
        lines.append("")
        for msg in golden.requires_gating_failures:
            lines.append(f"- {msg}")
        lines.append("")
    if golden and golden.implies_backfill_failures:
        lines.append("## Back-fill failures (Story 6.27 `implies` edge wired wrong)")
        lines.append("")
        lines.append(
            "A beat carrying `implies: <id>` must auto-credit that earlier "
            "beat (via `advance_goals`) the moment it flips met. These edges "
            "are wired wrong — fix the `implies:` field in "
            f"`server/pipeline/scenarios/` for `{sid}`:"
        )
        lines.append("")
        for msg in golden.implies_backfill_failures:
            lines.append(f"- {msg}")
        lines.append("")
    if golden and not golden.passed:
        lines.append("## Golden net failures (the judge mis-verdicts known cases)")
        lines.append("")
        if golden.negative_failures:
            lines.append(
                "### Off-topic input was accepted (this is the 2026-05-30 "
                "'judge passes everything' class of bug)"
            )
            lines.append("")
            lines.append(
                "These off-topic / tangential lines were judged **met**, but they "
                "do NOT accomplish the objective. The `success_criteria` is too "
                "permissive — tighten it so only a genuine attempt passes."
            )
            lines.append("")
            for r in golden.negative_failures:
                idx = _checkpoint_index(sid, r.case.checkpoint_id)
                field_path = (
                    f"checkpoints[{idx}].success_criteria"
                    if idx is not None
                    else f"checkpoint '{r.case.checkpoint_id}'.success_criteria"
                )
                lines.append(
                    f"- checkpoint **{r.case.checkpoint_id}** "
                    f'(`{field_path}`): user said "{r.case.user_text}" → '
                    f"judged **met** (should be unmet). [{r.case.source}]"
                )
            lines.append("")
        if golden.positive_misses:
            lines.append("### Genuine attempts were rejected (too strict)")
            lines.append("")
            lines.append(
                "These messy-but-genuine attempts were NOT judged met. The "
                "`success_criteria` is too strict for B1 learners — loosen it to "
                "accept hesitant / fragmented / synonym phrasing."
            )
            lines.append("")
            for r in golden.positive_misses:
                idx = _checkpoint_index(sid, r.case.checkpoint_id)
                field_path = (
                    f"checkpoints[{idx}].success_criteria"
                    if idx is not None
                    else f"checkpoint '{r.case.checkpoint_id}'.success_criteria"
                )
                lines.append(
                    f"- checkpoint **{r.case.checkpoint_id}** "
                    f'(`{field_path}`): user said "{r.case.user_text}" → '
                    f"judged **{_verdict_word(r.verdict)}** (should be met)."
                )
            lines.append("")

    cal = verdict.calibration
    if cal and not cal.passed:
        lines.append("## Calibration failure (difficulty out of band)")
        lines.append("")
        low, high = cal.band
        if not cal.guardrail_ok:
            lines.append(
                f"- **Off-topic guardrail breached**: the off_topic learner "
                f"completed {cal.offtopic_rate:.0f}% of conversations (must be "
                f"0%). The scenario lets a user who never does the task still "
                f"'win' — the checkpoints accept off-topic input. Tighten the "
                f"offending `success_criteria` (see golden failures above)."
            )
        if cal.band_verdict == "too_easy":
            lines.append(
                f"- **Too easy**: cooperative completion {cal.cooperative_rate:.0f}% "
                f"is above the {cal.difficulty} band {low}-{high}%. Make the "
                f"character less forgiving — lower `patience_start`, make "
                f"`fail_penalty` more negative, or tighten `success_criteria`."
            )
        elif cal.band_verdict == "too_hard":
            lines.append(
                f"- **Too hard**: cooperative completion {cal.cooperative_rate:.0f}% "
                f"is below the {cal.difficulty} band {low}-{high}%. Make the "
                f"character more forgiving — raise `patience_start`, soften "
                f"`fail_penalty`, raise `recovery_bonus`, or relax "
                f"`success_criteria`."
            )
        lines.append("")
        lines.append(
            f"(Bands anchor on the RUN-level global difficulty — see "
            f"`difficulty-calibration.md` §4.3. This run played at "
            f"`{cal.difficulty}` (Story 6.28: scenarios carry no authored "
            f"difficulty).)"
        )
        lines.append("")

    lines.append("---")
    lines.append(
        "Paste this whole block to an AI agent to propose the YAML edit, then "
        "re-run the command above to confirm."
    )
    return "\n".join(lines)


def _checkpoint_index(scenario_id: str, checkpoint_id: str) -> int | None:
    try:
        checkpoints = scenarios.load_scenario_checkpoints(scenario_id)
    except Exception:
        return None
    for i, cp in enumerate(checkpoints):
        if cp["id"] == checkpoint_id:
            return i
    return None


def _verdict_word(verdict: bool | None) -> str:
    if verdict is True:
        return "met"
    if verdict is False:
        return "unmet"
    return "unsure/infra"


# ============================================================
# Catalogue (AC13)
# ============================================================


def list_scenarios() -> list[str]:
    """All scenario ids, from the SAME index the pipeline uses (AC13)."""
    return sorted(scenarios._SCENARIO_INDEX)


# ============================================================
# Time helpers (kept tiny so report builders stay pure-ish)
# ============================================================


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
