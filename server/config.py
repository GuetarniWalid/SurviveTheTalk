"""Server configuration loaded from environment / .env."""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Runtime environment ("development" | "test" | "production").
    # Declared first so the jwt_secret validator can read it from info.data.
    environment: str = "development"

    # Pipeline (Pipecat / LiveKit / AI services)
    soniox_api_key: str
    # `openrouter_api_key` — LEGACY, no longer read by the prod runtime
    # since the 2026-05-29 "all-Groq" migration. The main character LLM +
    # EmotionEmitter + classifier now ALL run on Groq (Qwen via OpenRouter
    # was unreliable: Alibaba rate-limited OpenRouter's shared pool with
    # 429s even on single slow calls — `is_byok: False`). Kept as an
    # OPTIONAL field (empty default) so old `.env` files don't break boot;
    # the dev-only bench scripts still read `OPENROUTER_API_KEY` straight
    # from the env. Safe to delete from `/opt/survive-the-talk/.env`.
    openrouter_api_key: str = ""
    # Story 6.13 review (2026-05-27) — optional at parse time (empty
    # default) so an ElevenLabs-only deploy keeps booting after the
    # operator removes CARTESIA_API_KEY from .env. Mirrors the
    # `elevenlabs_*` fields below: runtime validation in
    # `tts_factory._build_cartesia` raises at process start if
    # `tts_provider="cartesia"` but this is empty — fail-loud at boot,
    # not silently mid-call.
    cartesia_api_key: str = ""
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Story 6.13 Phase 4b (2026-05-26) → Story 6.14 (2026-05-30) — TTS
    # provider switch. We keep BOTH providers in the codebase and let an
    # operator switch via env var without a code release.
    #
    # 2026-05-30 DIRECTION REVERSAL — default is now **Cartesia** (was
    # ElevenLabs since 2026-05-26). Two findings flipped it:
    #   1. Cartesia support confirmed the 2026-05-26 multi-frame freeze
    #      (calls 156/157) was a RESOLVED platform incident, not a
    #      fundamental bug — both our reproductions landed inside the
    #      incident window (status.cartesia.ai/incidents/1j04yfp4048k).
    #   2. Walid's on-device A/B (2026-05-30): Cartesia's smaller audio
    #      frames play FAR smoother under network jitter — they don't
    #      time-stretch ("voix rallongée") the way ElevenLabs' larger
    #      frames do. ElevenLabs Flash v2.5 still wins on raw TTFA
    #      (~75 ms vs ~300 ms) but loses on jitter smoothness, which is
    #      the launch-blocker. ElevenLabs is now the LAST-RESORT fallback
    #      until the Story 6.14 jitter buffer (`min_playout_delay` below)
    #      makes it viable again.
    #
    # Switching providers requires both:
    #   - `TTS_PROVIDER=cartesia` (or `elevenlabs`)
    #   - the matching API key + voice id env vars below
    #
    # `pipeline/tts_factory.py::build_tts_service` is the single
    # branching point; bot.py never names a provider directly.
    tts_provider: Literal["cartesia", "elevenlabs"] = "cartesia"

    # Story 6.14 AC2 (2026-05-30) — client-side jitter buffer / playout
    # delay, set SERVER-SIDE. The recurring "voix rallongée" is the
    # receiver's WebRTC NetEq time-stretching audio to fill bursty-packet
    # gaps (network jitter). The fix is a bigger playout delay so the
    # jitter buffer doesn't run dry. `flutter_webrtc` 1.3.0 exposes NO
    # client-side per-receiver knob, so the lever is LiveKit's room
    # config `min_playout_delay` (ms), attached to BOTH access tokens via
    # `pipeline/livekit_tokens.py` — the SFU then sends the `playout-delay`
    # RTP header extension that tells the receiver to buffer at least this
    # long. Trades a small fixed latency for smooth playback; keep it the
    # SMALLEST value that kills the stretching (PRD ceiling = 2 s perceived,
    # so ≤ ~400 ms is well within budget). 0 disables the knob (no room
    # config attached). Empirically tuned on the Pixel 9 smoke gate.
    livekit_min_playout_delay_ms: int = 200  # LIVEKIT_MIN_PLAYOUT_DELAY_MS

    # ElevenLabs Flash v2.5 — fields optional at Settings parse time
    # (empty defaults) so a Cartesia-only deploy keeps booting; runtime
    # validation in `tts_factory.build_tts_service` raises at process
    # start if `tts_provider="elevenlabs"` but these are missing.
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    # Default model = lowest TTFA model in the ElevenLabs catalog (75 ms
    # advertised). Operator may pin to a specific model for testing via
    # `ELEVENLABS_MODEL` env override; see the Settings.extra="ignore"
    # rationale below — typo'd env vars surface as missing required
    # field at boot, not as silent-extras at parse time.
    elevenlabs_model: str = "eleven_flash_v2_5"

    # Story 6.9b — Classifier provider migration (2026-05-22). Post-bench
    # verdict landed on Groq Llama 3.3 70B over Qwen via OpenRouter on the
    # 75-sample corpus: p50 121 ms vs 587 ms (4.8× faster), p95 320 ms vs
    # 859 ms (2.7× faster), 98.7 % vs 94.7 % accuracy, 0 false positives
    # vs 3. Full report at `_bmad-output/implementation-artifacts/
    # calibration-tests/classifier_benchmark_2026-05-22T09-29-19Z.json`.
    # `openrouter_api_key` above stays in use by EmotionEmitter (still on
    # Qwen — emotion latency has zero UX cost when slow, so the migration
    # was scoped to the exchange classifier only).
    groq_api_key: str

    # Auth
    jwt_secret: str = ""
    resend_api_key: str = ""
    resend_from_email: str = "noreply@survivethetalk.com"
    resend_from_name: str = "surviveTheTalk"

    # Database
    database_path: str = "/opt/survive-the-talk/data/db.sqlite"

    # Classifier (checkpoint judge) model id, env-overridable to pin a
    # snapshot at deploy time without a code release. Retires
    # `deferred-work.md` line 450 (Story 6.9 Defer #3, hardcoded model id).
    #
    # 2026-05-29 — switched off `llama-3.3-70b-versatile` onto Llama 4 Scout
    # because the multi-goal judge (`classify_multi`) now uses Groq STRICT
    # structured outputs (`response_format=json_schema`), and 70B does NOT
    # support that response format (HTTP 400 "model does not support
    # json_schema"). Scout does — it returns a schema-pinned
    # `{goal_id: met|unmet|unsure}` object Groq validates server-side, which
    # eliminated the format-instability bug where 70B intermittently echoed
    # `goal_id="greet"` (broke our id matching → silent all-None → no
    # checkpoint flipped). Scout is also ~4-5x cheaper ($0.11/$0.34 per 1M
    # vs $0.59/$0.79) and same latency (~220 ms from VPS).
    #
    # MUST stay a Groq model that supports `json_schema` structured outputs
    # (see console.groq.com/docs/structured-outputs#supported-models).
    # Pinning a model that lacks it (e.g. back to `llama-3.3-70b-versatile`)
    # makes every `classify_multi` POST 400. The character + emotion paths
    # keep 70B (they don't use structured outputs).
    classifier_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # Story 7.1 — post-call debrief generator model id (env DEBRIEF_MODEL).
    # The debrief is a standalone Groq call that requests STRICT structured
    # outputs (`response_format=json_schema`), so — exactly like
    # `classifier_model` above — this MUST stay a Groq model that supports
    # `json_schema` (Scout / Llama-4 / gpt-oss / kimi; NOT 70B, which HTTP
    # 400s on json_schema). Project law: server/CLAUDE.md §4. Defaults to
    # Scout, the same structured-output model the checkpoint judge trusts.
    debrief_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # 2026-05-29 "all-Groq" migration — the main character LLM and the
    # EmotionEmitter moved off Qwen-via-OpenRouter (429-prone shared pool)
    # onto Groq (first-party dedicated key = our own quota, controllable).
    # Both default to the same model we already trust in prod (the
    # classifier runs on it); split into two env-overridable fields so a
    # future tuning pass can pin a faster/cheaper model for emotion (it's
    # a background, non-critical call) without touching the character.
    character_model: str = "llama-3.3-70b-versatile"  # CHARACTER_MODEL
    emotion_model: str = "llama-3.3-70b-versatile"  # EMOTION_MODEL

    # 2026-05-29 — single OpenAI-compatible LLM provider switch (mirrors the
    # TTS factory). ALL LLM calls (character, emotion, checkpoint judge,
    # warm-up) hit `llm_base_url`. To move off Groq tomorrow, set
    # LLM_BASE_URL + LLM_API_KEY (+ the per-role *_MODEL vars) — ZERO code,
    # because every provider we'd realistically use (Groq / OpenRouter /
    # DashScope / OpenAI / Together / Fireworks…) speaks the same
    # OpenAI-compatible request format. The switch point is
    # `pipeline/llm_provider.py`; no call site hardcodes `api.groq.com`.
    llm_base_url: str = "https://api.groq.com/openai/v1"  # LLM_BASE_URL
    # Optional provider-key override. Empty → falls back to `groq_api_key`
    # (so today's GROQ_API_KEY-only deploys keep working untouched). Resolved
    # via `pipeline.llm_provider.resolve_llm_api_key`.
    llm_api_key: str = ""  # LLM_API_KEY

    # Story 6.18 — dynamic, in-character exit + patience-warning line
    # generation. Default ON. When True, `bot.py` injects a generator into
    # PatienceTracker that regenerates the hang-up / patience-warning line
    # from the ACTUAL transcript + reason (COHERENCE_CHARTER-governed) so the
    # closing words can't fabricate events (cop call_id=212 accused the user
    # of "three versions" via a canned YAML line). The YAML `exit_lines` stay
    # as the fast fallback whenever generation is slow/fails. Set
    # `HANGUP_LINE_GENERATION=0` to flip the WHOLE feature back to the canned
    # lines with no logic redeploy (AC7 kill-switch). Pydantic parses the
    # usual bool forms (`0`/`1`/`true`/`false`).
    hangup_line_generation: bool = True  # HANGUP_LINE_GENERATION

    # Story 6.18 smoke gate (call_id=215, 2026-06-03) — turn-endpoint timeout,
    # now env-configurable. This is how long the pipeline waits (after the VAD
    # flags silence) before declaring the user's turn DONE and letting the
    # character respond. It was hardcoded 0.6 s (Story 6.8 latency tune); call
    # 215 showed that was too short for a B1 learner composing an answer under
    # pressure — a thinking pause finalized a FRAGMENT as its own turn (e.g.
    # "Do you, uh, ooh." was judged a failed turn → unfair patience drain) and
    # the character talked over the user. Raised to 0.8 s + exposed as
    # `USER_SPEECH_TIMEOUT` so the VPS can tune it without a code release.
    # Stacks ADDITIVELY with the VAD `stop_secs` (~0.8 s in bot.py): net
    # silence-to-turn-end ≈ stop_secs + this (0.8 + 0.8 = 1.6 s today, under the
    # PRD 2 s perceived-latency ceiling). Recommended range 0.6-1.0 s.
    user_speech_timeout: float = 0.8  # USER_SPEECH_TIMEOUT

    # Story 6.20 follow-up (smoke call_id=223, 2026-06-05) — EnvironmentMonitor
    # (parasitic background-voice detection, Story 6.11) tunables, now
    # env-configurable so the VPS can adjust sensitivity (or kill it) without a
    # code release. call_id=223 was a FALSE hang-up: Soniox diarization split
    # the lone user's voice across single-speaker turns ('1' then '2'), which
    # the detector mis-read as a second voice. The code fix is the co-occurrence
    # rule (a parasite must overlap the user WITHIN a turn); these knobs are the
    # live safety valve on top of it.
    #   ENV_MONITOR_ENABLED=0           → disable detection entirely (kill-switch)
    #   ENV_MONITOR_TRIGGER_TURNS       → parasitic turns in the window to fire
    #   ENV_MONITOR_MIN_SPEAKER_TOKENS  → min non-primary tokens/turn to count
    env_monitor_enabled: bool = True  # ENV_MONITOR_ENABLED
    env_monitor_trigger_turns: int = 2  # ENV_MONITOR_TRIGGER_TURNS
    env_monitor_min_speaker_tokens: int = 3  # ENV_MONITOR_MIN_SPEAKER_TOKENS

    # FR37 — inappropriate-content (abuse) detection kill-switch. When True
    # (default), the SAME per-turn checkpoint classifier also flags a clearly
    # abusive user turn (no extra LLM call), ending the call in-character with
    # reason=inappropriate_content (→ the Story 7.1 debrief fills
    # inappropriate_behavior). Set ABUSE_DETECTION_ENABLED=0 to disable instantly
    # without a redeploy (the classifier still emits the flag; CheckpointManager
    # just ignores it). Conservative by construction — the prompt flags only
    # genuine abuse, and any non-bool/missing flag is treated as not-abusive.
    abuse_detection_enabled: bool = True  # ABUSE_DETECTION_ENABLED

    # Story 6.24 — TTS connection warm-up kill-switch. When True (default), a
    # fire-and-forget Cartesia /tts/bytes warm-up fires at call start so the
    # opening line doesn't pay the first-synthesis cold-start (call_id=226:
    # opening line stalled → 5 s silence). Set TTS_WARMUP_ENABLED=0 to disable
    # (saves a tiny throwaway synthesis per call). Only fires for the Cartesia
    # provider; never blocks or raises (pipeline/tts_warmup.py).
    tts_warmup_enabled: bool = True  # TTS_WARMUP_ENABLED

    # Story 6.9b — `extra: "ignore"` so unrelated env vars don't trip the
    # default Pydantic-v2 forbid-extras rule at Settings() construction.
    #
    # Threat model: this RELAXES validation — typos like `OPENROUER_API_KEY`
    # (missing T) are now silently ignored instead of raising
    # ValidationError. The mitigation is the test suite:
    # `tests/test_config.py::test_settings_loads_all_pipeline_env_vars`
    # explicitly asserts each declared field is present + correct, so a
    # typo'd env var would surface as a *missing* required field rather
    # than as an unknown-extra error. Net validation surface stays the same
    # (declared fields enforced) — we just stop noisy false positives on
    # adjacent env vars that aren't our concern.
    #
    # Why not declare the extras as `Optional[str] = None` fields instead:
    # would couple unrelated concerns into Settings (DASHSCOPE_API_KEY is
    # only used by the dev-machine benchmark harness; CI/CD vars belong
    # to the deploy layer; future Story 6.9c provider keys shouldn't
    # require touching this file before they can be tested). Keep Settings
    # scoped to fields the prod runtime actively reads.
    #
    # Concrete drivers (env vars currently present on dev machines OR VPS
    # that are NOT declared above): DASHSCOPE_API_KEY (Lever 1 bench),
    # CEREBRAS_API_KEY / ANTHROPIC_API_KEY (Phase A bench slots), CI vars
    # from GitHub Actions, LATENCY_PROBE (smoke gate gate), CLASSIFIER_MODEL
    # (already used here but as override of declared field). Pydantic v1
    # default behavior was "ignore"; v2 flipped to "forbid" — we're
    # restoring v1 semantics intentionally.
    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, value: str, info) -> str:
        """Reject empty secrets in every environment; require >=32 chars in production.

        Generate one with: openssl rand -hex 32
        """
        if not value:
            raise ValueError(
                "JWT_SECRET must be set (generate with: openssl rand -hex 32)"
            )
        environment = (info.data.get("environment") or "development").strip().lower()
        if environment == "production" and len(value) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 chars in production "
                "(generate with: openssl rand -hex 32)"
            )
        return value

    @field_validator("livekit_min_playout_delay_ms")
    @classmethod
    def _validate_min_playout_delay(cls, value: int) -> int:
        """Bound the jitter-buffer knob at boot — fail-loud, not per-call.

        Without this, a typo'd `LIVEKIT_MIN_PLAYOUT_DELAY_MS` would either
        (a) overflow the protobuf `RoomConfiguration.min_playout_delay`
        (int32) → `ValueError` deep in token minting → a generic 502 on
        EVERY `initiate_call`, masking the real cause; or (b) silently ship
        a playout delay past the PRD 2 s perceived-latency kill-criterion.
        The ceiling here is that 2 s PRD ceiling (the buffer trades a little
        latency for smoothness; 0 disables the knob). Reject at process
        start so a misconfig surfaces clearly instead of bricking calls.
        """
        if value < 0:
            raise ValueError(
                "LIVEKIT_MIN_PLAYOUT_DELAY_MS must be >= 0 "
                "(0 disables the jitter buffer)"
            )
        if value > 2000:
            raise ValueError(
                "LIVEKIT_MIN_PLAYOUT_DELAY_MS must be <= 2000 (the PRD 2 s "
                "perceived-latency ceiling); keep it the smallest value that "
                f"kills the stretching, got {value}"
            )
        return value

    @field_validator("user_speech_timeout")
    @classmethod
    def _validate_user_speech_timeout(cls, value: float) -> float:
        """Bound the turn-endpoint timeout at boot — fail-loud on a typo'd env.

        A non-positive value would break turn detection (the user's turn never
        ends, or ends instantly); a too-large value (e.g. `USER_SPEECH_TIMEOUT=8`)
        means the character waits seconds of dead air before replying. Catch
        both at process start rather than degrading every call. The 3.0 s
        ceiling is a generous sanity bound — the recommended range is 0.6-1.0 s
        (it stacks with the VAD `stop_secs`, keep the sum under the PRD 2 s).
        """
        if value <= 0:
            raise ValueError(
                "USER_SPEECH_TIMEOUT must be > 0 (it is the silence wait before "
                f"the user's turn ends), got {value}"
            )
        if value > 3.0:
            raise ValueError(
                "USER_SPEECH_TIMEOUT must be <= 3.0 s — beyond that the character "
                "waits seconds before replying (dead-air UX); keep it in the "
                f"0.6-1.0 s range, got {value}"
            )
        return value

    @field_validator("resend_from_name", "resend_from_email")
    @classmethod
    def _forbid_crlf_in_sender_fields(cls, value: str) -> str:
        """Reject CR/LF in sender fields to prevent email-header injection."""
        if "\r" in value or "\n" in value:
            raise ValueError(
                "CR/LF characters are not allowed in email sender fields "
                "(header-injection risk)"
            )
        return value
