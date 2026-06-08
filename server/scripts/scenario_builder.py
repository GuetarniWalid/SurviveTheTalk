"""Story 6.16 — Scenario Builder: a fuzzy premise → a complete, validated scenario.

The FRONT half of the authoring loop (this builds; Story 6.15 validates). Given a
short free-text premise + a few knobs (id, difficulty, rive character, checkpoint
count), an LLM pipeline invents a believable persona + a TIME-ORDERED conversation
arc long enough for ~5 minutes, drafts one checkpoint per beat, then an adversarial
critique pass de-overlaps the checkpoints (so a single sentence can't satisfy four
at once) and enforces forward time-progression (no looping). The result is a
schema-valid scenario YAML that drops straight into `server/pipeline/scenarios/`
and through the Story 6.15 `calibrate_scenario` validator.

## Pipeline (each step is an LLM call, except the pure assembly/validation)

    expand_brief        — premise → rich brief (persona, setting, canonical facts,
                          win/lose, vocabulary, exit lines, an N-beat time arc).
    draft_checkpoints   — arc → N checkpoints (id/hint/prompt_segment/success_criteria),
                          each criterion specific + beat-bound.
    critique_and_repair — adversarial pass: rewrite overlapping criteria, reorder /
                          de-loop beats, sharpen unjudgeable criteria. 1+ rounds.
    build_base_prompt   — PURE assembly of the character system prompt from the brief
                          (NO speak-first directive — that is composed elsewhere).
    assemble_scenario   — PURE dict in the exact YAML schema.
    validate_structure  — PURE checks mirroring `scenarios.py` (unique ids, required
                          fields, base_prompt has no speak-first, difficulty valid).

## Why authoring-time enforcement of "advance in time" / "no 1-sentence-validates-4"

The runtime checkpoint engine is GOAL-BASED and any-order (Story 6.10) — it does NOT
gate beats temporally. So coherence + discrimination are enforced HERE (the critique
pass makes each `success_criteria` distinct and beat-bound) and EMPIRICALLY by the
Story 6.15 calibration `too_easy` gate (a scenario that collapses into "one sentence
wins" completes in 1-2 turns → flagged too_easy → FAIL). Build → validate closes the
loop.

## Cost / determinism (AC8)

Live generation needs an API key + the CLI (`scripts/build_scenario.py`); this module
is never imported by prod. The pure logic (assembly, structural validation, overlap
heuristic, patience sizing, the pipeline driven with a FAKE LLM) has unit tests in
`tests/test_scenario_builder.py` that run in the default `pytest`.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import textwrap
from dataclasses import dataclass, field

import httpx
import yaml

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# Reuse the Story 6.15 LLM client + validator (no fork).
from scripts.calibration_engine import (  # noqa: E402,F401
    ChatLLM,
    GoldenResult,
    JudgeLLM,
    OpenAIChatLLM,
    _ScenarioData,
    run_golden,
)

# Story 6.19 follow-up — single source of truth for the difficulty-neutral
# persona guard, shared with the loader (`scenarios.load_scenario_base_prompt`)
# so a generated base_prompt can never carry a difficulty-coded phrase the loader
# would reject. Used by `validate_structure`.
from pipeline.scenarios import find_persona_difficulty_leaks  # noqa: E402

# The five Rive puppets the client can render — a new scenario MUST reuse one
# (puppets are expensive to make; you cannot invent a new character). See
# server/CLAUDE.md. Story 6.17: each puppet has a FIXED on-screen physique
# (gender, rough age, look) — the generated persona AND the chosen voice must
# match it, so a new scenario "wears" an existing face coherently. Sourced from
# the shipped scenarios' personas + their voice-selection comments.
CHARACTER_PROFILES: dict[str, dict] = {
    "waiter": {
        "gender": "feminine",
        "look": (
            "a tired young-adult WOMAN working a service job (waitress vibe); "
            "British; flat/weary by default, turns sarcastic when provoked"
        ),
        "voice_hint": "weary British female who can turn sarcastic",
    },
    "mugger": {
        "gender": "masculine",
        "look": (
            "a young-adult MAN; a small-time street thug with a rough "
            "working-class London edge; not very bright, broke, tries to intimidate"
        ),
        "voice_hint": "deep, gravelly young male, working-class London",
    },
    "girlfriend": {
        "gender": "feminine",
        "look": (
            "a WOMAN around 26; expressive and passionate; an emotionally-charged "
            "romantic partner"
        ),
        "voice_hint": "expressive young female",
    },
    "cop": {
        "gender": "masculine",
        "look": (
            "an adult MAN; a sharp, procedural, clipped police officer / "
            "authority figure; cold and deliberate, not warm"
        ),
        "voice_hint": "firm, authoritative adult male",
    },
    "landlord": {
        "gender": "masculine",
        "look": (
            "an OLDER MAN (around 55-60); well-spoken, legalistic, stern; "
            "a British property-owner type used to getting his way"
        ),
        "voice_hint": "older, stern British male",
    },
}

RIVE_CHARACTERS = tuple(CHARACTER_PROFILES.keys())

DEFAULT_CHECKPOINTS = 20
DEFAULT_TARGET_MINUTES = 5

# Generation temperatures: creative for invention, cooler for the audit.
_EXPAND_TEMPERATURE = 0.8
_DRAFT_TEMPERATURE = 0.7
_CRITIQUE_TEMPERATURE = 0.3
_EXPAND_MAX_TOKENS = 2200
_DRAFT_MAX_TOKENS = 3200
_CRITIQUE_MAX_TOKENS = 3600

_SCENARIOS_DIR = _HERE.parent / "pipeline" / "scenarios"

# The exact guard strings `scenarios.load_scenario_base_prompt` rejects — kept in
# sync so the builder never emits a base_prompt the loader would refuse.
_SPEAK_FIRST_GUARD = "You will speak first when the call begins"
# Story 6.19 — the loader composes the per-difficulty behavior block from
# `scenarios._DIFFICULTY_PROMPTS` and REJECTS any base_prompt that still carries
# an inline "Difficulty behavior (…)" block. The builder must NOT weave one in.
_DIFFICULTY_BLOCK_GUARD = "Difficulty behavior ("

_VALID_DIFFICULTIES = ("easy", "medium", "hard")

# Per-difficulty fail penalty (preset, from `scenarios._DIFFICULTY_PRESETS` /
# difficulty-calibration.md §4.3) — used only to size a starting `patience_start`
# so a long scenario is survivable enough to calibrate. Calibration then tunes it.
_PRESET_FAIL_PENALTY = {"easy": 15, "medium": 20, "hard": 25}
# Roughly how many genuine off-topic misses a cooperative user should be able to
# absorb before hang-up, per difficulty (drains are per-miss, not per-checkpoint).
_TARGET_ABSORBED_MISSES = {"easy": 6, "medium": 4, "hard": 3}


# ============================================================
# Prompts (module constants — the live tool AND the worked-example workflow
# use the SAME prompts, so the demo is faithful to the tool)
# ============================================================

EXPAND_PROMPT = """\
You design scenarios for a spoken-English roleplay practice app. A B1 learner will have a \
~{minutes}-minute phone conversation with an AI character. From a SHORT premise, design a rich, \
believable scenario whose conversation PROGRESSES IN TIME over about {n} distinct beats (one beat \
per checkpoint). Be CREATIVE: invent concrete, believable details the premise leaves out (names, \
times, places, specific facts) so the conversation can sustain {minutes} minutes WITHOUT repeating \
itself or stalling.

Premise: {description}
Character role: {character}. Difficulty: {difficulty}.

DIFFICULTY IS NOT A PERSONALITY KNOB. The Difficulty value tells you only how \
demanding the conversation ARC should be — it must NEVER change WHO the character \
is. Do NOT make the persona gentler, warmer, or more helpful for "easy", nor \
sterner, colder, or more demanding for "hard". character_persona, setting, \
opening_line, and every prompt_segment must read IDENTICALLY at easy, medium, and \
hard. How hard the character is on the learner's English (vocabulary, idioms, \
rephrasing, precision) is applied SEPARATELY by the engine at runtime — never \
mention grammar mistakes, repeating/rephrasing, going easy or hard on them, or \
speaking speed anywhere in what you write.

VISUAL CONSTRAINT — the character is shown on screen as: {character_look}.
Your persona MUST match this gender, approximate age, and overall look. You may freely \
invent the name, job, backstory, and situation, but you must NOT change the gender, age \
range, or general appearance — the scenario "wears" this existing on-screen face.

Return STRICT JSON only (no prose, no Markdown fences), with these keys:
{{
  "title": "<short scenario title>",
  "character_name": "<the character's first name>",
  "character_persona": "<2-4 sentences: who they are and their FIXED mood/tone — difficulty-neutral, the SAME persona at every difficulty; do NOT describe how they treat the learner's English>",
  "setting": "<1-2 sentences: where/when this happens>",
  "user_objective": "<what the LEARNER must achieve overall>",
  "win_condition": "<what counts as success>",
  "lose_condition": "<what makes the character end the call>",
  "canonical_facts": ["<concrete facts the character treats as true — for coherence>", "..."],
  "language_focus": "<comma-separated grammar/vocabulary areas>",
  "content_warning": "<string, or null>",
  "vocabulary": "<comma-separated example phrases the learner might use>",
  "context": "<1 sentence shown to the learner before the call>",
  "expect": "<1 sentence setting expectations for the learner>",
  "opening_line": "<the character's FIRST spoken line that OPENS the call, in-character — it is played to the learner BEFORE they say anything (the character always speaks first). Make it fit THIS character, never a generic greeting>",
  "exit_completion": "<the character's in-character line if the learner SUCCEEDS>",
  "exit_hangup": "<the character's in-character line if the learner FAILS/gives up>",
  "exit_patience_warning": "<a 'last chance' in-character line>",
  "arc": ["<beat 1: one sentence — what happens + what the LEARNER must do>", "... EXACTLY {n} beats, in time order, each ADVANCING, never repeating or looping"]
}}
The "arc" array MUST have EXACTLY {n} entries.
"""

CHECKPOINTS_PROMPT = """\
Turn this time-ordered arc into EXACTLY {n} checkpoints for the practice engine. One checkpoint = \
one beat, in the arc's order.

Brief (JSON):
{brief_json}

Return STRICT JSON only (no prose, no fences): a JSON array of EXACTLY {n} objects, each:
{{
  "id": "<short snake_case unique id naming the beat, e.g. state_alibi_time>",
  "hint_text": "<one short imperative line telling the LEARNER what to do at this beat>",
  "prompt_segment": "<1-3 sentences instructing the CHARACTER what to ask/say/probe at THIS beat — difficulty-neutral: describe WHAT they pursue, never HOW hard they are on the learner's English>",
  "success_criteria": "<a SPECIFIC, judgeable description of what the LEARNER's turn must do to pass THIS beat>",
  "requires": "<OPTIONAL — see the REACTIVE rule below. Omit entirely for normal beats.>"
}}

CRITICAL rules:
- Each success_criteria must target a DISTINCT, beat-specific action, referencing the specific \
information addressed at this beat — so that a single sentence CANNOT satisfy several checkpoints \
at once. Being merely on-topic, coherent, or polite must NOT be enough to pass.
- Beats stay in the arc's time order; the conversation must ADVANCE (no two checkpoints that repeat \
the same exchange).
- ids unique. Do NOT include any "speak first" instruction anywhere.
- Keep every prompt_segment DIFFICULTY-NEUTRAL: never bake in a difficulty stance (going easy / \
helping / rephrasing, or being strict / demanding the exact detail / refusing to rephrase). The \
difficulty knob is applied separately by the engine at runtime.
- REACTIVE beats (`requires`): a beat is REACTIVE if it only makes sense as the learner's RESPONSE \
to a specific earlier CHARACTER action — a trap (misquoting them, citing a CCTV timestamp), a \
reveal (naming an associate, a forced-door detail), or a circle-back ("remind me who you said…"). \
A reactive beat literally cannot happen before that trigger. For each reactive beat, set \
"requires" to the `id` of the EARLIER checkpoint that delivers its trigger (a single earlier id). \
A beat the learner can volunteer at any time (PROACTIVE — give your name, state your alibi) must \
OMIT "requires" entirely. When in doubt, omit it. The engine then refuses to credit a reactive \
beat until its trigger is met, so its success_criteria can stay a simple lexical test.
"""

CRITIQUE_PROMPT = """\
You audit {n} checkpoints for a roleplay scenario. Find and FIX four failure modes, then output \
the corrected set.

1. OVERLAP / COLLAPSE: any pair of checkpoints that a single plausible user sentence could satisfy \
at once. Rewrite their success_criteria so each requires a DISTINCT, beat-specific action. This is \
the most important fix — a scenario where one sentence validates several checkpoints is broken.
2. CIRCULARITY: beats that repeat, regress, or could happen in any order. Reorder/rewrite so the \
conversation STRICTLY ADVANCES in time (beat k builds on beat k-1's exchange). \
EXCEPTION — a REACTIVE beat (one carrying a "requires" field) has a LEGITIMATE ordering dependency \
on the earlier trigger it names; do NOT "make it any-order" or strip that dependency. PRESERVE its \
"requires" field verbatim. The engine enforces the ordering, so the reactive beat's success_criteria \
may stay a simple lexical test rather than encoding "PASS only AFTER …" in prose.
3. UNJUDGEABLE: vague success_criteria a classifier could not decide. Make them concrete and \
checkable.
4. DIFFICULTY LEAKAGE: any prompt_segment that bakes in a difficulty stance — going easy/helping/\
rephrasing, or being maximally strict/demanding the exact detail/refusing to rephrase. Rewrite it \
to be difficulty-NEUTRAL: describe only WHAT the character pursues at this beat, never HOW hard they \
are on the learner's English (the difficulty knob is applied separately at runtime).

Brief (JSON):
{brief_json}

Checkpoints (JSON):
{checkpoints_json}

Return STRICT JSON only (no prose, no fences): a JSON array of EXACTLY {n} corrected checkpoint \
objects with the SAME keys (id, hint_text, prompt_segment, success_criteria, plus "requires" on any \
beat that had one), ids unique, in time order. Output ONLY the corrected array.
"""

# Story 6.19 — the per-difficulty "Difficulty behavior (…)" block is NO LONGER
# woven into the generated base_prompt. It moved to
# `pipeline.scenarios._DIFFICULTY_PROMPTS` (single source of truth) and is
# composed at LOAD time by `load_scenario_base_prompt` (which rejects any inline
# block), so a global difficulty pick can actually change how a scenario SPEAKS.
# The builder therefore emits a base_prompt WITHOUT a block (enforced by
# `_DIFFICULTY_BLOCK_GUARD` in `validate_structure`).


# ============================================================
# Data
# ============================================================


@dataclass
class BuildResult:
    scenario: dict
    brief: dict
    checkpoints: list[dict]
    yaml_text: str
    structural_problems: list[str]
    overlap_pairs: list[tuple[str, str, float]]
    # Story 6.20 AC4 — checkpoints whose hint_text ↔ prompt_segment overlap is
    # below threshold (authoring drift). Advisory, never blocks the write.
    hint_prompt_drift: list[tuple[str, float]] = field(default_factory=list)
    voice_id: str | None = None
    voice_reason: str = ""


# ============================================================
# JSON parsing (LLM output, defensive)
# ============================================================


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def parse_json_object(raw: str) -> dict | None:
    """Parse a JSON OBJECT from an LLM response, tolerant of fences/prose."""
    text = _strip_fence(raw)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_json_array(raw: str) -> list | None:
    """Parse a JSON ARRAY (or a {"checkpoints":[...]} wrapper) from an LLM response."""
    text = _strip_fence(raw)
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    obj = parse_json_object(raw)
    if obj:
        for key in ("checkpoints", "items", "list"):
            if isinstance(obj.get(key), list):
                return obj[key]
    return None


# ============================================================
# Pure helpers (unit-tested)
# ============================================================


def slugify(text: str, *, fallback: str = "beat") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or fallback


def sanitize_checkpoints(raw_checkpoints: list[dict]) -> list[dict]:
    """Keep the schema keys, strip strings, and force ids unique + snake_case.

    The LLM occasionally returns extra keys, blank fields, or duplicate ids; this
    makes the list schema-shaped before structural validation.

    Story 6.23 — the OPTIONAL reactive-gating `requires` edge is PRESERVED (it
    used to be silently dropped by this whitelist — the load-bearing builder
    edit). A present `requires` value is slugified the SAME way ids are so it
    matches the target checkpoint's sanitized id; a blank/non-string `requires`
    is omitted (treated as a proactive beat). The loader (and `validate_structure`)
    still validate that the edge points at an existing, earlier beat — a builder
    that mis-slugs the target surfaces there, for the human to fix.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for i, cp in enumerate(raw_checkpoints):
        if not isinstance(cp, dict):
            continue
        cid = slugify(str(cp.get("id") or ""), fallback=f"beat_{i + 1}")
        base = cid
        n = 2
        while cid in seen:
            cid = f"{base}_{n}"
            n += 1
        seen.add(cid)
        entry = {
            "id": cid,
            "hint_text": str(cp.get("hint_text", "")).strip(),
            "prompt_segment": str(cp.get("prompt_segment", "")).strip(),
            "success_criteria": str(cp.get("success_criteria", "")).strip(),
        }
        raw_requires = cp.get("requires")
        if isinstance(raw_requires, str):
            if raw_requires.strip():
                entry["requires"] = slugify(raw_requires)
            # blank/whitespace string → no edge (proactive), as before.
        elif raw_requires not in (None, [], {}, ()):
            # Story 6.23 review (f8) — a PRESENT but non-string `requires`
            # (a list/int/dict the draft LLM emitted instead of a single id)
            # means a reactive edge was INTENDED but malformed. Do NOT silently
            # drop it — that demotes the beat to proactive with no signal, the
            # exact silent-drop class the `requires` preservation above was
            # added to kill. Keep a guaranteed-unmatchable sentinel so the
            # loader / `validate_structure` "unknown id" fail-fast surfaces it
            # for the human to fix instead of shipping a lost gate.
            entry["requires"] = f"__malformed_requires__{slugify(str(raw_requires))}"
        out.append(entry)
    return out


# Salient-token stopword set + tokenizer shared by the lexical heuristics
# (`lexical_overlap_pairs` and the Story 6.20 `hint_prompt_drift_pairs`). Drops
# closed-class / scenario-generic words so the overlap math reflects CONTENT
# tokens, not grammar glue.
_SALIENT_STOPWORDS = {
    "the",
    "a",
    "an",
    "to",
    "of",
    "or",
    "and",
    "in",
    "on",
    "user",
    "learner",
    "they",
    "their",
    "them",
    "that",
    "this",
    "is",
    "are",
    "with",
    "for",
    "any",
    "what",
    "when",
    "where",
    "it",
    "as",
    "about",
    "must",
    "his",
    "her",
    # Story 6.20 — imperative-glue words common to `hint_text` directives
    # ("tell the waiter…", "ask them…") that would otherwise inflate the
    # hint↔prompt overlap and hide genuine topical drift.
    "you",
    "your",
    "tell",
    "ask",
    "say",
    "give",
    "get",
    "let",
    "make",
    "want",
}


def _salient_tokens(text: str) -> set[str]:
    """Lowercase content tokens of `text` (drop stopwords + <=2-char words).
    Pure + deterministic; shared by the lexical-overlap heuristics."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    return {w for w in words if w not in _SALIENT_STOPWORDS and len(w) > 2}


def lexical_overlap_pairs(
    checkpoints: list[dict], *, threshold: float = 0.6
) -> list[tuple[str, str, float]]:
    """Cheap pre-check for the "one sentence validates several" risk: pairs of
    checkpoints whose `success_criteria` token sets are highly similar (Jaccard ≥
    threshold). A fast heuristic surfaced to the operator; the semantic de-overlap
    is the LLM critique, and the empirical backstop is the Story 6.15 `too_easy`
    gate. Pure + deterministic.
    """
    sets = [
        (cp["id"], _salient_tokens(cp.get("success_criteria", "")))
        for cp in checkpoints
    ]
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a_id, a = sets[i]
            b_id, b = sets[j]
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac >= threshold:
                pairs.append((a_id, b_id, round(jac, 2)))
    return pairs


def hint_prompt_drift_pairs(
    checkpoints: list[dict], *, threshold: float = 0.2
) -> list[tuple[str, float]]:
    """Story 6.20 AC4 — authoring-drift lint: flag checkpoints whose `hint_text`
    (shown to the LEARNER) and `prompt_segment` (what the CHARACTER is steered to
    pursue) share too few salient tokens — a sign the two were authored about
    different things, so the on-screen consigne won't match what the character
    actually asks.

    Returns `(checkpoint_id, overlap)` for each checkpoint whose overlap is BELOW
    `threshold`, where `overlap = |hint ∩ prompt| / |hint|` (the fraction of the
    hint's content words that also appear in the prompt segment). The hint is the
    shorter, learner-facing string, so anchoring the ratio on it asks "is the
    instruction the learner reads reflected in what the character pursues?".

    A checkpoint with NO salient hint tokens (e.g. a one-word hint that is all
    stopwords) is skipped — there's nothing to measure, not a drift. Pure +
    deterministic; a WARNING-level heuristic surfaced to the author at build time,
    NEVER a runtime block (AC4: static, per-scenario, no runtime change).
    """
    flagged: list[tuple[str, float]] = []
    for cp in checkpoints:
        hint_toks = _salient_tokens(cp.get("hint_text", ""))
        prompt_toks = _salient_tokens(cp.get("prompt_segment", ""))
        if not hint_toks:
            continue
        overlap = len(hint_toks & prompt_toks) / len(hint_toks)
        if overlap < threshold:
            flagged.append((cp.get("id", "?"), round(overlap, 2)))
    return flagged


def suggest_patience_start(n_checkpoints: int, difficulty: str) -> int:
    """A survivable starting `patience_start` for a scenario of this length.

    Patience drains per OFF-TOPIC miss (not per checkpoint), so this sizes the meter
    to absorb a difficulty-appropriate number of misses, with a small bump for long
    scenarios. A STARTING GUESS — the Story 6.15 calibration sweep tunes it.
    """
    fail = _PRESET_FAIL_PENALTY.get(difficulty, 20)
    misses = _TARGET_ABSORBED_MISSES.get(difficulty, 4)
    base = fail * misses
    if n_checkpoints > 12:
        base += (n_checkpoints - 12) * 2
    return int(round(base / 5.0) * 5)


def build_base_prompt(brief: dict) -> str:
    """PURE assembly of the character system prompt from the brief.

    Includes identity/tone, hard boundaries, and the canonical facts (so the
    runtime COHERENCE_CHARTER has an inventory to be coherent against).
    Deliberately omits BOTH the speak-first directive (composed once elsewhere)
    AND the per-difficulty behavior block (Story 6.19 — composed at load time by
    `scenarios.load_scenario_base_prompt` from `_DIFFICULTY_PROMPTS`, so a global
    difficulty pick can change how the scenario speaks). A base_prompt without
    either is exactly what `scenarios.load_scenario_base_prompt` accepts.
    """
    name = brief.get("character_name", "the character")
    persona = brief.get("character_persona", "").strip()
    setting = brief.get("setting", "").strip()
    facts = [
        str(f).strip() for f in (brief.get("canonical_facts") or []) if str(f).strip()
    ]

    parts = [f"You are {name}. {persona}".strip()]
    if setting:
        parts.append(f"Setting: {setting}")
    opening = (brief.get("opening_line") or "").strip()
    if opening:
        parts.append(
            f'Conversation context: you OPEN the call by saying: "{opening}" — that '
            "line has ALREADY been spoken to them. Do NOT greet again or repeat it; "
            "respond to what they say next."
        )
    parts.append(
        "Rules you MUST follow:\n"
        "- Keep every response to 1-3 short sentences, as if on a real phone call.\n"
        "- Wait for the other person to finish before you respond.\n"
        "- Speak English only. Never break character. Never acknowledge being an AI.\n"
        "- Stay consistent with everything already said in this conversation."
    )
    parts.append(
        "Boundaries you MUST NEVER cross:\n"
        "- Never use slurs, threats, or sexual/violent/discriminatory content.\n"
        "- If the other person is genuinely abusive, deliver your hang-up line and end the call."
    )
    if facts:
        fact_lines = "\n".join(f"- {f}" for f in facts)
        parts.append(
            "Canonical facts (treat these as TRUE and stay consistent with them across the "
            "whole conversation; never contradict or invent alternatives):\n"
            + fact_lines
        )
    return "\n\n".join(p for p in parts if p).strip()


def assemble_scenario(
    *,
    scenario_id: str,
    title: str,
    difficulty: str,
    rive_character: str,
    base_prompt: str,
    checkpoints: list[dict],
    brief: dict,
    patience_start: int | None = None,
    tts_voice_id: str | None = None,
) -> dict:
    """PURE assembly of the full scenario dict in the exact YAML schema."""
    if patience_start is None:
        patience_start = suggest_patience_start(len(checkpoints), difficulty)
    return {
        "metadata": {
            "id": scenario_id,
            "title": title or brief.get("title", scenario_id),
            "difficulty": difficulty,
            "is_free": False,
            "rive_character": rive_character,
            "language_focus": brief.get("language_focus", ""),
            "tts_voice_id": tts_voice_id,
            # Story 6.17 — the canned line the character speaks first (played by
            # bot.py before the learner talks). Per-scenario, never the hardcoded
            # waiter greeting.
            "opening_line": (brief.get("opening_line") or "").strip(),
            "content_warning": brief.get("content_warning") or None,
            # Sized starting guess for a long scenario; calibration tunes it.
            "patience_start": patience_start,
            "fail_penalty": None,
            "silence_penalty": None,
            "recovery_bonus": None,
            "silence_prompt_seconds": None,
            "silence_hangup_seconds": None,
            "ladder_impatience_seconds": None,
            "escalation_thresholds": None,
        },
        "base_prompt": base_prompt,
        "checkpoints": checkpoints,
        "exit_lines": {
            "hangup": brief.get("exit_hangup")
            or "I don't have time for this. Goodbye.",
            "completion": brief.get("exit_completion") or "Alright. We're done here.",
            "patience_warning": brief.get("exit_patience_warning")
            or "Look, I'm losing my patience. Last chance.",
        },
        "briefing": {
            "vocabulary": brief.get("vocabulary", ""),
            "context": brief.get("context", ""),
            "expect": brief.get("expect", ""),
        },
        "calibration": {
            "pass_a": {
                "date": None,
                "transcript_file": None,
                "survival_pct": None,
                "verdict": None,
            },
            "pass_b": {
                "date": None,
                "transcript_file": None,
                "survival_pct": None,
                "verdict": None,
            },
        },
    }


def validate_structure(scenario: dict) -> list[str]:
    """PURE structural checks mirroring `scenarios.py` so a generated scenario can't
    break boot. Returns a list of problems (empty = OK)."""
    problems: list[str] = []
    metadata = scenario.get("metadata") or {}
    if not isinstance(metadata, dict):
        return ["metadata is not a dict"]
    if not metadata.get("id"):
        problems.append("metadata.id missing")
    if metadata.get("difficulty") not in _VALID_DIFFICULTIES:
        problems.append(
            f"metadata.difficulty must be one of {_VALID_DIFFICULTIES}, "
            f"got {metadata.get('difficulty')!r}"
        )
    if metadata.get("rive_character") not in RIVE_CHARACTERS:
        problems.append(
            f"metadata.rive_character must be one of {RIVE_CHARACTERS}, "
            f"got {metadata.get('rive_character')!r}"
        )

    base_prompt = scenario.get("base_prompt")
    if not isinstance(base_prompt, str) or not base_prompt.strip():
        problems.append("base_prompt must be a non-empty string")
    elif _SPEAK_FIRST_GUARD in base_prompt:
        problems.append("base_prompt must NOT contain the speak-first directive")
    elif _DIFFICULTY_BLOCK_GUARD in base_prompt:
        # Story 6.19 — parity with the loader's new guard (the difficulty
        # behavior block is composed at load time from _DIFFICULTY_PROMPTS).
        problems.append(
            "base_prompt must NOT contain an inline 'Difficulty behavior (…)' block"
        )
    if isinstance(base_prompt, str):
        # Story 6.19 follow-up — parity with the loader's difficulty-neutral
        # guard: a persona must not freeze a difficulty stance into its prose
        # (the difficulty knob lives in scenarios._DIFFICULTY_PROMPTS, composed at
        # runtime). Shared single source of truth via `find_persona_difficulty_leaks`.
        leaks = find_persona_difficulty_leaks(base_prompt)
        if leaks:
            problems.append(
                f"base_prompt contains difficulty-coded phrase(s) {leaks} — "
                "personas must be difficulty-NEUTRAL (the difficulty knob lives "
                "in scenarios._DIFFICULTY_PROMPTS, composed at runtime)"
            )

    checkpoints = scenario.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        problems.append("checkpoints must be a non-empty list")
        return problems
    ids: list[str] = []
    required = ("id", "hint_text", "prompt_segment", "success_criteria")
    for i, cp in enumerate(checkpoints):
        if not isinstance(cp, dict):
            problems.append(f"checkpoint[{i}] is not a dict")
            continue
        for fld in required:
            val = cp.get(fld)
            if not isinstance(val, str) or not val.strip():
                problems.append(f"checkpoint[{i}] missing/empty {fld!r}")
        if isinstance(cp.get("id"), str):
            ids.append(cp["id"])
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append(f"duplicate checkpoint ids: {dupes}")
    # Story 6.23 — mirror the loader's `requires` validation (existence +
    # strictly-earlier order) so a generated scenario with a bad reactive edge
    # can't break boot.
    id_to_index = {
        cp["id"]: i
        for i, cp in enumerate(checkpoints)
        if isinstance(cp, dict) and isinstance(cp.get("id"), str)
    }
    for i, cp in enumerate(checkpoints):
        if not isinstance(cp, dict):
            continue
        required = cp.get("requires")
        if required is None:
            continue
        if not isinstance(required, str) or not required.strip():
            problems.append(f"checkpoint[{i}] has a non-string/empty 'requires'")
            continue
        if required not in id_to_index:
            problems.append(
                f"checkpoint[{i}] 'requires' points at unknown id {required!r}"
            )
        elif id_to_index[required] >= i:
            problems.append(
                f"checkpoint[{i}] 'requires' {required!r} must be an EARLIER checkpoint"
            )
    return problems


# ============================================================
# YAML serialization (literal blocks for readability)
# ============================================================


class _BlockDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_BlockDumper.add_representer(str, _str_representer)


def scenario_to_yaml(scenario: dict) -> str:
    return yaml.dump(
        scenario,
        Dumper=_BlockDumper,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
        default_flow_style=False,
    )


# ============================================================
# LLM pipeline steps
# ============================================================


# ============================================================
# Voice selection (Story 6.17) — Cartesia catalog + LLM match
# ============================================================

_CARTESIA_VOICES_URL = "https://api.cartesia.ai/voices"
_CARTESIA_VERSION = "2024-11-13"

VOICE_MATCH_PROMPT = """\
Pick the SINGLE best text-to-speech voice for this character from the catalog below. \
The character speaks ENGLISH in the app. Match, in priority order: gender, then \
nationality/accent (if the persona implies one), then age, then overall vibe/tone.

Character name: {character_name}
Persona: {persona}
Setting: {setting}

Voice catalog (one per line — "id | name | gender | country | description"):
{catalog}

Return STRICT JSON only (no prose, no fences):
{{"voice_id": "<one EXACT id copied from the catalog above>", "reason": "<one short sentence>"}}
The voice_id MUST be exactly one of the ids listed.
"""


async def fetch_cartesia_voices(
    api_key: str,
    *,
    languages: tuple[str, ...] = ("en", "en-US", "en-GB"),
    max_voices: int = 100,
) -> list[dict]:
    """Fetch the Cartesia voice catalog (first page, ~100 voices) and return the
    voices whose `language` is in `languages`, projected to the fields the matcher
    needs. Raises `httpx.HTTPError` on a transport failure (the caller degrades
    gracefully). Story 6.17.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Cartesia-Version": _CARTESIA_VERSION,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _CARTESIA_VOICES_URL, headers=headers, params={"limit": 100}
        )
        resp.raise_for_status()
        body = resp.json()
    page = body if isinstance(body, list) else body.get("data", [])
    out: list[dict] = []
    for v in page:
        if v.get("language") not in languages:
            continue
        out.append(
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "gender": v.get("gender"),
                "language": v.get("language"),
                "country": v.get("country"),
                "description": (v.get("description") or "").replace("\n", " ").strip(),
            }
        )
        if len(out) >= max_voices:
            break
    return out


async def select_voice(
    *,
    brief: dict,
    voices: list[dict],
    llm: ChatLLM,
    required_gender: str | None = None,
) -> tuple[str | None, str]:
    """LLM-pick the best-matching voice id from `voices` for the character in
    `brief`. Returns (voice_id, reason); voice_id is None if the catalog is empty
    or the LLM returns an id not in the catalog (caller falls back to the default
    voice). Story 6.17.

    `required_gender` ("masculine"/"feminine") restricts the catalog to that
    gender FIRST, so the voice matches the puppet's physique (a female puppet
    never gets a male voice). If no voice of that gender exists in the catalog,
    keeps the DEFAULT voice (returns None) rather than risk a wrong-gender voice.
    """
    if not voices:
        return None, "no voices available"
    if required_gender:
        pool = [v for v in voices if v.get("gender") == required_gender]
        if not pool:
            # No catalog voice of the puppet's gender: keep the DEFAULT voice
            # rather than silently widen to the full catalog and risk a
            # wrong-gender voice (AC2 — a female puppet must never get a male
            # voice); AC3 allows voice selection to fall back to the default.
            return None, f"no {required_gender} voice in the catalog — kept default"
        voices = pool
    catalog = "\n".join(
        f"{v['id']} | {v['name']} | gender={v['gender']} | country={v.get('country')} | {v['description']}"
        for v in voices
    )
    prompt = VOICE_MATCH_PROMPT.format(
        character_name=brief.get("character_name", ""),
        persona=brief.get("character_persona", ""),
        setting=brief.get("setting", ""),
        catalog=catalog,
    )
    raw = await llm.chat(
        [{"role": "user", "content": prompt}],
        system="You match characters to TTS voices. Output STRICT JSON only.",
        temperature=0.2,
        max_tokens=200,
    )
    parsed = parse_json_object(raw)
    voice_id = (parsed or {}).get("voice_id")
    valid_ids = {v["id"] for v in voices}
    if isinstance(voice_id, str) and voice_id in valid_ids:
        return voice_id, str((parsed or {}).get("reason", "")).strip()
    return None, f"no valid match (LLM returned {voice_id!r})"


async def expand_brief(
    description: str,
    *,
    character: str,
    difficulty: str,
    n_checkpoints: int,
    target_minutes: int,
    character_look: str = "",
    llm: ChatLLM,
) -> dict:
    prompt = EXPAND_PROMPT.format(
        description=description.strip(),
        character=character,
        character_look=character_look or "(no specific constraint)",
        difficulty=difficulty,
        n=n_checkpoints,
        minutes=target_minutes,
    )
    raw = await llm.chat(
        [{"role": "user", "content": prompt}],
        system="You are a creative, precise scenario designer. Output STRICT JSON only.",
        temperature=_EXPAND_TEMPERATURE,
        max_tokens=_EXPAND_MAX_TOKENS,
    )
    brief = parse_json_object(raw)
    if brief is None:
        raise ValueError("expand_brief: LLM did not return a parseable JSON object")
    return brief


async def draft_checkpoints(brief: dict, *, n: int, llm: ChatLLM) -> list[dict]:
    prompt = CHECKPOINTS_PROMPT.format(
        n=n, brief_json=json.dumps(brief, ensure_ascii=False)
    )
    raw = await llm.chat(
        [{"role": "user", "content": prompt}],
        system="You convert a story arc into precise, distinct checkpoints. STRICT JSON array only.",
        temperature=_DRAFT_TEMPERATURE,
        max_tokens=_DRAFT_MAX_TOKENS,
    )
    arr = parse_json_array(raw)
    if arr is None:
        raise ValueError("draft_checkpoints: LLM did not return a parseable JSON array")
    return sanitize_checkpoints(arr)


async def critique_and_repair(
    checkpoints: list[dict], brief: dict, *, n: int, llm: ChatLLM, rounds: int = 1
) -> list[dict]:
    current = checkpoints
    for _ in range(max(1, rounds)):
        prompt = CRITIQUE_PROMPT.format(
            n=n,
            brief_json=json.dumps(brief, ensure_ascii=False),
            checkpoints_json=json.dumps(current, ensure_ascii=False),
        )
        raw = await llm.chat(
            [{"role": "user", "content": prompt}],
            system="You are a strict scenario auditor. Output ONLY the corrected JSON array.",
            temperature=_CRITIQUE_TEMPERATURE,
            max_tokens=_CRITIQUE_MAX_TOKENS,
        )
        arr = parse_json_array(raw)
        if arr:
            current = sanitize_checkpoints(arr)
    return current


async def build_scenario(
    description: str,
    *,
    scenario_id: str,
    difficulty: str,
    rive_character: str,
    title: str = "",
    n_checkpoints: int = DEFAULT_CHECKPOINTS,
    target_minutes: int = DEFAULT_TARGET_MINUTES,
    critique_rounds: int = 1,
    cartesia_api_key: str | None = None,
    llm: ChatLLM,
) -> BuildResult:
    """Full pipeline: premise → validated scenario dict + YAML, incl. voice
    selection (AC1-AC7 + Story 6.17 voice). If `cartesia_api_key` is provided the
    builder picks a matching voice; otherwise it leaves the voice null (the
    pipeline falls back to the default voice) and the result notes why."""
    if difficulty not in _VALID_DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {_VALID_DIFFICULTIES}")
    if rive_character not in RIVE_CHARACTERS:
        raise ValueError(f"rive_character must be one of {RIVE_CHARACTERS}")
    profile = CHARACTER_PROFILES[rive_character]

    brief = await expand_brief(
        description,
        character=rive_character,
        difficulty=difficulty,
        n_checkpoints=n_checkpoints,
        target_minutes=target_minutes,
        character_look=profile["look"],
        llm=llm,
    )
    checkpoints = await draft_checkpoints(brief, n=n_checkpoints, llm=llm)
    checkpoints = await critique_and_repair(
        checkpoints, brief, n=n_checkpoints, llm=llm, rounds=critique_rounds
    )

    # Story 6.17 — voice selection. Degrades gracefully: if there is no Cartesia
    # key (e.g. running locally where only the LLM key is set), or the catalog
    # fetch fails, leave the voice null + record why; the TTS falls back to the
    # default voice and the operator can pick later.
    voice_id: str | None = None
    voice_reason = (
        "no Cartesia key — left default voice (set CARTESIA_API_KEY to auto-select)"
    )
    if cartesia_api_key:
        try:
            voices = await fetch_cartesia_voices(cartesia_api_key)
            voice_id, voice_reason = await select_voice(
                brief=brief,
                voices=voices,
                llm=llm,
                required_gender=profile["gender"],
            )
        except Exception as exc:  # noqa: BLE001 — voice is best-effort, never fatal
            voice_id, voice_reason = None, f"voice fetch/select failed: {exc}"

    return finalize_build(
        brief=brief,
        checkpoints=checkpoints,
        scenario_id=scenario_id,
        title=title,
        difficulty=difficulty,
        rive_character=rive_character,
        voice_id=voice_id,
        voice_reason=voice_reason,
        expected_checkpoints=n_checkpoints,
    )


def finalize_build(
    *,
    brief: dict,
    checkpoints: list[dict],
    scenario_id: str,
    title: str,
    difficulty: str,
    rive_character: str,
    voice_id: str | None = None,
    voice_reason: str = "",
    expected_checkpoints: int | None = None,
) -> BuildResult:
    """PURE: assemble + validate + serialize (separated from the LLM steps so the
    full assembly is unit-testable without any network).

    When `expected_checkpoints` is given, a count mismatch is recorded as a
    structural problem (AC3 — "exactly N"): the LLM under/over-generating must
    block the write, not ship a wrong-length scenario silently."""
    checkpoints = sanitize_checkpoints(checkpoints)
    base_prompt = build_base_prompt(brief)
    scenario = assemble_scenario(
        scenario_id=scenario_id,
        title=title,
        difficulty=difficulty,
        rive_character=rive_character,
        base_prompt=base_prompt,
        checkpoints=checkpoints,
        brief=brief,
        tts_voice_id=voice_id,
    )
    problems = validate_structure(scenario)
    if expected_checkpoints is not None and len(checkpoints) != expected_checkpoints:
        problems.append(
            f"expected exactly {expected_checkpoints} checkpoints but got "
            f"{len(checkpoints)} — the generator under/over-produced (re-run, raise "
            f"the draft token budget, or set --checkpoints {len(checkpoints)})"
        )
    overlaps = lexical_overlap_pairs(checkpoints)
    drift = hint_prompt_drift_pairs(checkpoints)
    return BuildResult(
        scenario=scenario,
        brief=brief,
        checkpoints=checkpoints,
        yaml_text=scenario_to_yaml(scenario),
        structural_problems=problems,
        overlap_pairs=overlaps,
        hint_prompt_drift=drift,
        voice_id=voice_id,
        voice_reason=voice_reason,
    )


# ============================================================
# Auto build → validate → repair loop (Story 6.17)
# ============================================================

REPAIR_GOLDEN_PROMPT = """\
Some checkpoints in this scenario WRONGLY accept off-topic / small-talk answers as a success — \
their success_criteria are too lenient. TIGHTEN ONLY the success_criteria of the listed \
checkpoints so an off-topic or merely-polite answer is NO LONGER accepted, while a genuine \
on-target attempt still passes. Do NOT change the ids, order, hint_text, prompt_segment, or any \
checkpoint that is not listed.

Brief (JSON):
{brief_json}

All {n} checkpoints (JSON):
{checkpoints_json}

Checkpoints that wrongly accepted off-topic input (id → the off-topic phrases that wrongly passed):
{failures_json}

Return STRICT JSON only (no prose, no fences): the FULL array of {n} corrected checkpoint objects \
(same keys: id, hint_text, prompt_segment, success_criteria), ids unchanged, in the same order.
"""


@dataclass
class ValidatedBuild:
    result: BuildResult
    golden: GoldenResult
    repair_rounds: int

    @property
    def passed(self) -> bool:
        return self.golden.passed


async def repair_checkpoints_from_golden(
    checkpoints: list[dict], golden: GoldenResult, brief: dict, *, llm: ChatLLM
) -> list[dict]:
    """Ask the LLM to TIGHTEN only the success_criteria of the checkpoints that
    wrongly accepted off-topic input (the golden net's negative failures). Returns
    the corrected checkpoint list; unchanged if there's nothing to fix or the LLM
    output is unparseable. Story 6.17 auto-repair."""
    fails: dict[str, list[str]] = {}
    for r in golden.negative_failures:
        fails.setdefault(r.case.checkpoint_id, []).append(r.case.user_text)
    if not fails:
        return checkpoints
    prompt = REPAIR_GOLDEN_PROMPT.format(
        n=len(checkpoints),
        brief_json=json.dumps(brief, ensure_ascii=False),
        checkpoints_json=json.dumps(checkpoints, ensure_ascii=False),
        failures_json=json.dumps(fails, ensure_ascii=False),
    )
    raw = await llm.chat(
        [{"role": "user", "content": prompt}],
        system="You tighten scenario checkpoint criteria. Output ONLY the corrected JSON array.",
        temperature=_CRITIQUE_TEMPERATURE,
        max_tokens=_CRITIQUE_MAX_TOKENS,
    )
    arr = parse_json_array(raw)
    return sanitize_checkpoints(arr) if arr else checkpoints


def _data_from_result(result: BuildResult, difficulty: str) -> _ScenarioData:
    """Build an in-memory `_ScenarioData` from a BuildResult so the golden net can
    validate WITHOUT writing the scenario to disk first (run_golden reads only the
    title + checkpoints)."""
    md = result.scenario["metadata"]
    return _ScenarioData(
        scenario_id=md["id"],
        title=md.get("title", md["id"]),
        difficulty=difficulty,
        base_prompt=result.scenario["base_prompt"],
        checkpoints=result.scenario["checkpoints"],
        briefing=result.scenario.get("briefing") or {},
        patience={},
    )


async def validate_and_repair(
    result: BuildResult,
    *,
    scenario_id: str,
    difficulty: str,
    rive_character: str,
    llm: ChatLLM,
    judge: JudgeLLM,
    max_repair_rounds: int = 10,
) -> ValidatedBuild:
    """Run the golden net on a built scenario; on failure, auto-tighten the
    offending checkpoints and re-validate, up to `max_repair_rounds` times. Returns
    the (possibly repaired) build + the final golden verdict + how many repair
    rounds ran. Story 6.17 — "intelligent back-and-forth until coherent"."""
    title = result.scenario["metadata"].get("title", scenario_id)
    rounds = 0
    golden = await run_golden(
        scenario_id=scenario_id, judge=judge, data=_data_from_result(result, difficulty)
    )
    while not golden.passed and rounds < max_repair_rounds:
        rounds += 1
        repaired = await repair_checkpoints_from_golden(
            result.checkpoints, golden, result.brief, llm=llm
        )
        result = finalize_build(
            brief=result.brief,
            checkpoints=repaired,
            scenario_id=scenario_id,
            title=title,
            difficulty=difficulty,
            rive_character=rive_character,
            voice_id=result.voice_id,
            voice_reason=result.voice_reason,
        )
        golden = await run_golden(
            scenario_id=scenario_id,
            judge=judge,
            data=_data_from_result(result, difficulty),
        )
    return ValidatedBuild(result=result, golden=golden, repair_rounds=rounds)


async def build_and_validate_scenario(
    description: str,
    *,
    scenario_id: str,
    difficulty: str,
    rive_character: str,
    title: str = "",
    n_checkpoints: int = DEFAULT_CHECKPOINTS,
    target_minutes: int = DEFAULT_TARGET_MINUTES,
    critique_rounds: int = 1,
    cartesia_api_key: str | None = None,
    max_repair_rounds: int = 10,
    llm: ChatLLM,
    judge: JudgeLLM,
) -> ValidatedBuild:
    """Full auto pipeline: build (story + voice) → golden validate → auto-repair →
    re-validate, until the off-topic regression net passes (or rounds run out)."""
    result = await build_scenario(
        description,
        scenario_id=scenario_id,
        title=title,
        difficulty=difficulty,
        rive_character=rive_character,
        n_checkpoints=n_checkpoints,
        target_minutes=target_minutes,
        critique_rounds=critique_rounds,
        cartesia_api_key=cartesia_api_key,
        llm=llm,
    )
    return await validate_and_repair(
        result,
        scenario_id=scenario_id,
        difficulty=difficulty,
        rive_character=rive_character,
        llm=llm,
        judge=judge,
        max_repair_rounds=max_repair_rounds,
    )


def default_scenario_path(scenario_id: str) -> pathlib.Path:
    return _SCENARIOS_DIR / f"{scenario_id.replace('_', '-')}.yaml"


def format_build_summary(result: BuildResult, *, width: int = 64) -> str:
    """A pretty, human-readable recap of a generated scenario (Story 6.17) — shown
    in the wizard / CLI so the operator can read the whole thing before closing.
    Pure (no I/O); easy to test."""
    sc = result.scenario
    md = sc["metadata"]
    brief = result.brief
    cps = sc["checkpoints"]
    bar = "═" * width
    sub = "─" * (width - 24)
    text_w = width - 4
    look = CHARACTER_PROFILES.get(md.get("rive_character"), {}).get("look", "")

    out: list[str] = [bar, f"  📋  {md.get('title', '(sans titre)')}", bar]
    out.append(f"  Personnage : {md.get('rive_character')}  ({look})")
    out.append(
        f"  Difficulté : {md.get('difficulty')}    "
        f"Étapes : {len(cps)}    Patience de départ : {md.get('patience_start')}"
    )
    out.append(f"  Voix       : {result.voice_id or '(voix par défaut)'}")
    if result.voice_reason:
        out.append(f"               ↳ {result.voice_reason}")

    def _block(title: str, paragraphs: list[tuple[str, str]]) -> None:
        rows = [(lbl, val.strip()) for lbl, val in paragraphs if val and val.strip()]
        if not rows:
            return
        out.append("")
        out.append(f"  {title}")
        out.append(f"  {sub}")
        for lbl, val in rows:
            wrapped = textwrap.wrap(f"{lbl}{val}" if lbl else val, text_w)
            for j, line in enumerate(wrapped):
                out.append(f"  {line}" if j == 0 else f"     {line}")

    _block(
        "Le personnage",
        [
            ("", brief.get("character_persona", "")),
            ("Cadre : ", brief.get("setting", "")),
        ],
    )
    briefing = sc.get("briefing") or {}
    _block(
        "Briefing (montré au joueur avant l'appel)",
        [
            ("Contexte : ", briefing.get("context", "")),
            ("À prévoir : ", briefing.get("expect", "")),
            ("Vocabulaire : ", briefing.get("vocabulary", "")),
        ],
    )
    exit_lines = sc.get("exit_lines") or {}
    _block(
        "Répliques de fin",
        [
            ("Réussite : ", exit_lines.get("completion", "")),
            ("Échec : ", exit_lines.get("hangup", "")),
        ],
    )

    out.append("")
    out.append(f"  Les {len(cps)} étapes — ce que le joueur doit faire :")
    out.append(f"  {sub}")
    for i, cp in enumerate(cps, 1):
        out.append(f"  {i:>2}. {cp.get('hint_text', '').strip()}")
    out.append(bar)
    return "\n".join(out)
