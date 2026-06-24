"""Server configuration loaded from environment / .env."""

import re
from typing import Literal

from pydantic import field_validator, model_validator
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
    # (2026-05-29: the remaining LLM paths followed — all-Groq migration;
    # Story 6.29 then retired the separate emotion classifier entirely, the
    # face is co-generated by the reply LLM.)
    groq_api_key: str

    # Auth
    jwt_secret: str = ""
    resend_api_key: str = ""
    resend_from_email: str = "noreply@survivethetalk.com"
    resend_from_name: str = "surviveTheTalk"

    # Story 10.3 — Google Play "app access" review bypass. The app is
    # passwordless (email + a RANDOM 6-digit code emailed to the user), so a
    # store reviewer cannot sign in: the code lands in an inbox they don't
    # control, and Google states it will not receive our codes. These two env
    # vars let ONE designated test email sign in with a FIXED 6-digit code,
    # skipping the email round-trip entirely (BOTH `/auth/request-code` and
    # `/auth/verify-code` short-circuit for it — see `api.routes_auth`). OFF by
    # default (both empty); set BOTH in the prod `.env` for the review window,
    # then UNSET once the app is approved. Only this exact email + code
    # bypasses (constant-time compared); every real user keeps the random-code
    # path. The test account is an ordinary free-tier user.
    review_login_email: str = ""  # REVIEW_LOGIN_EMAIL
    review_login_code: str = ""  # REVIEW_LOGIN_CODE

    # Story 8.1 — In-app-purchase / subscription validation (StoreKit 2 +
    # Google Play Billing). All optional (empty / None defaults) so a deploy
    # without store credentials still BOOTS — the validators raise a clean,
    # shaped 503 at request time when their platform's config is absent
    # (fail-loud per-request, never an optimistic tier grant on a misconfig).
    # Secrets live in `/opt/survive-the-talk/.env`, applied via
    # `systemctl restart pipecat.service`. The store products must be created
    # in App Store Connect + Google Play Console (Walid-owned, blocks the
    # on-device smoke gate — D4).
    #
    # Apple: offline StoreKit 2 JWS verification needs only `apple_bundle_id`
    # (+ Apple's root certs, bundled in `billing/apple_roots.py`).
    # `apple_app_apple_id` is the numeric App Store app id, REQUIRED only when
    # verifying a PRODUCTION transaction (Sandbox does not need it); iOS
    # production validation is itself gated until Story 10-4 (no iOS pipeline).
    # The App Store Server API key fields (issuer/key/p8) are reserved for the
    # future online revocation / renewal path (Story 8.3) — unused by 8.1's
    # offline verification.
    apple_bundle_id: str = ""  # APPLE_BUNDLE_ID
    apple_app_apple_id: int | None = None  # APPLE_APP_APPLE_ID (prod only)
    apple_issuer_id: str = ""  # APPLE_ISSUER_ID (App Store Server API, 8.3)
    apple_key_id: str = ""  # APPLE_KEY_ID (App Store Server API, 8.3)
    apple_private_key_p8: str = ""  # APPLE_PRIVATE_KEY_P8 (App Store Server API, 8.3)
    # code-review 8.1 F1 — opt a deploy into granting paid on a GENUINE Apple
    # SANDBOX receipt (signature-valid but free to mint). Default OFF so a
    # production deploy never grants paid on a tester's sandbox purchase; flip
    # `APPLE_ACCEPT_SANDBOX=1` only for the on-device sandbox smoke gate. A
    # forged Xcode/LocalTesting environment is rejected regardless of this flag.
    apple_accept_sandbox: bool = False  # APPLE_ACCEPT_SANDBOX

    # Google: the androidpublisher subscriptionsv2 endpoint is authenticated
    # with a service account. `google_play_package_name` must equal the Android
    # `applicationId`. `google_service_account_json` is the FULL service-account
    # JSON, base64-encoded (a one-line env value; the field_validator below
    # decodes + parses it to fail loud at boot on a malformed value).
    google_play_package_name: str = ""  # GOOGLE_PLAY_PACKAGE_NAME
    google_service_account_json: str = ""  # GOOGLE_SERVICE_ACCOUNT_JSON (base64)

    # Story 8.3 (Task 5/D3) — subscription lifecycle WEBHOOK security.
    #
    # Google RTDN (Pub/Sub push): the INTERIM, store-documented security is a
    # secret query token configured on the push subscription endpoint URL
    # (`.../webhook/google?token=<secret>`). When set, the webhook REQUIRES a
    # matching `?token=`; mismatch/absent → 403; when EMPTY (pre-store-config)
    # the Google webhook returns 503 (not yet wired) rather than accepting an
    # unauthenticated push. `google_pubsub_audience` is RESERVED for the
    # production hardening (full Pub/Sub OIDC bearer-token audience check) and
    # is unused today. Both default-empty so the server boots without them.
    #
    # Apple ASSN V2 needs NO extra secret: the pushed payload is a signed JWS
    # verified OFFLINE with the existing `apple_bundle_id` + bundled roots (D4
    # stays deferred — no App Store Server API key required to RECEIVE+verify).
    google_pubsub_verification_token: str = ""  # GOOGLE_PUBSUB_VERIFICATION_TOKEN
    google_pubsub_audience: str = ""  # GOOGLE_PUBSUB_AUDIENCE (reserved, OIDC)

    # The expected store product id, shared verbatim with the client constant
    # `kIapWeeklyProductId` (D4). A purchase whose productId differs is judged
    # invalid (never flips tier). Lowercase + store-portable.
    iap_product_id: str = "stt_weekly_199"  # IAP_PRODUCT_ID

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

    # 2026-05-29 "all-Groq" migration — the main character LLM moved off
    # Qwen-via-OpenRouter (429-prone shared pool) onto Groq (first-party
    # dedicated key = our own quota, controllable).
    character_model: str = "llama-3.3-70b-versatile"  # CHARACTER_MODEL
    # `emotion_model` — LEGACY since Story 6.29 (2026-06-10): the character's
    # face emotion is now CO-GENERATED by the reply LLM as a trailing mood tag
    # (`prompts.MOOD_TAG_DIRECTIVE`, stripped + re-emitted by
    # `pipeline/reply_sanitizer.py`), and the separate `EmotionEmitter`
    # classifier was retired — no runtime path reads this field anymore. Kept
    # as a defaulted no-op (same posture as `openrouter_api_key` above) purely
    # to DOCUMENT the legacy knob — `extra="ignore"` already keeps a stale
    # EMOTION_MODEL env harmless either way; safe to remove from
    # `/opt/survive-the-talk/.env`.
    emotion_model: str = "llama-3.3-70b-versatile"  # EMOTION_MODEL (legacy)

    # 2026-05-29 — single OpenAI-compatible LLM provider switch (mirrors the
    # TTS factory). ALL LLM calls (character — which also co-generates the
    # face mood since 6.29 —, checkpoint judge, warm-up) hit `llm_base_url`. To move off Groq tomorrow, set
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

    # Story 6.29 (D1 = bounded wait, fail-open) — how long CheckpointManager
    # holds a judged user turn for the checkpoint verdict's side effects (goal
    # flips, steering recompose, HUD envelope, patience outcome) to land
    # BEFORE the turn is forwarded to the character LLM. Captures the typical
    # verdict (p50 ~120-220 ms, p95 ~320 ms from the VPS) so the reply is
    # steered by THIS turn's verdict instead of lagging one turn behind (the
    # call-274 P3 verbatim-re-recitation bug); on budget miss the turn
    # forwards with stale steering and the verdict applies late (exactly the
    # pre-6.29 parallel behavior — the character can never be muted by a slow
    # or failed judge). `VERDICT_WAIT_BUDGET_MS=0` disables the wait entirely
    # (pure parallel = pre-6.29 rollback without a redeploy).
    verdict_wait_budget_ms: int = 800  # VERDICT_WAIT_BUDGET_MS

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

    # Story 6.26 — warm bot-process pool size. Each call normally spawns a
    # brand-new bot subprocess that pays a ~4.7 s cold import boot on the call's
    # critical path (torch/pipecat/livekit/soniox/onnx) before it can speak —
    # the opening blank. The pool keeps `bot_pool_size` already-booted "parked"
    # bots idle (blocked on a stdin job line, zero CPU) and hands one its job at
    # call start, skipping the boot. A parked bot serves exactly ONE call then
    # exits (clean isolation, identical lifecycle to a cold spawn). `0` disables
    # the pool entirely → every call cold-spawns exactly as before this story
    # (clean kill-switch / code-free rollback). Default 1: ~1 concurrent call
    # today, so one stand-by covers ~100 % of calls; raise via BOT_POOL_SIZE
    # when concurrency grows (each parked bot holds the import stack in RAM —
    # the fallback cold-spawn handles any overflow, no call is ever blocked).
    bot_pool_size: int = 1  # BOT_POOL_SIZE

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

    @field_validator("google_pubsub_verification_token")
    @classmethod
    def _validate_pubsub_token(cls, value: str, info) -> str:
        """Reject a weak Google RTDN webhook secret in production (Story 8.3 F13).

        This token is the ENTIRE authz boundary for `POST /subscription/webhook/
        google` (and it travels in the URL query string), so a short/guessable
        value is a real footgun — mirror `jwt_secret`'s production length floor.
        Only enforced when NON-EMPTY: an empty value is the pre-store-config
        posture (the webhook returns 503, accepting no unauthenticated push), so
        the server must still boot without it. Generate with: openssl rand -hex 32
        """
        if not value:
            return value  # unset = pre-store-config; webhook 503s, no boot block
        environment = (info.data.get("environment") or "development").strip().lower()
        if environment == "production" and len(value) < 24:
            raise ValueError(
                "GOOGLE_PUBSUB_VERIFICATION_TOKEN must be at least 24 chars in "
                "production (generate with: openssl rand -hex 32)"
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

    @field_validator("verdict_wait_budget_ms")
    @classmethod
    def _validate_verdict_wait_budget(cls, value: int) -> int:
        """Bound the verdict-wait budget at boot — fail-loud on a typo'd env.

        Negative is meaningless (0 is the sanctioned wait-disable). The 2000 ms
        ceiling is the classifier's own outer timeout (`exchange_classifier.
        _CLASSIFIER_TIMEOUT_SECONDS` = 2.0 s): past it the wait degenerates to
        unbounded wait-for-verdict and the added latency threatens the PRD 2 s
        perceived-reply ceiling. Keep it well below — default 800 ms.
        """
        if value < 0:
            raise ValueError(
                "VERDICT_WAIT_BUDGET_MS must be >= 0 (0 disables the wait)"
            )
        if value > 2000:
            raise ValueError(
                "VERDICT_WAIT_BUDGET_MS must be <= 2000 (the classifier's own "
                "2.0 s outer timeout — a larger budget only adds dead air), "
                f"got {value}"
            )
        return value

    @field_validator("bot_pool_size")
    @classmethod
    def _validate_bot_pool_size(cls, value: int) -> int:
        """Bound the warm-pool size at boot — fail-loud on a typo'd env.

        Negative is meaningless; an absurdly large value (`BOT_POOL_SIZE=100`)
        would try to spawn 100 heavy bot processes at startup and OOM the 2-core
        VPS. `0` is the sanctioned kill-switch (pool disabled → every call
        cold-spawns, exactly as before Story 6.26). The ceiling of 8 is a
        generous sanity bound — each parked bot holds the full import stack in
        RAM, and the cold-spawn fallback already covers any concurrency overflow.
        """
        if value < 0:
            raise ValueError("BOT_POOL_SIZE must be >= 0 (0 disables the warm pool)")
        if value > 8:
            raise ValueError(
                "BOT_POOL_SIZE must be <= 8 — each parked bot holds the full "
                "import stack in RAM; a larger pool would OOM the VPS and the "
                f"cold-spawn fallback already handles overflow, got {value}"
            )
        return value

    @field_validator("google_service_account_json")
    @classmethod
    def _validate_google_service_account_json(cls, value: str) -> str:
        """Fail loud at boot on a malformed base64 / JSON service-account blob.

        Only validates when non-empty (empty = no Google credentials yet, a
        valid pre-D4 deploy state). A typo'd or truncated `GOOGLE_SERVICE_
        ACCOUNT_JSON` is far better caught at process start than mid-purchase,
        where it would surface as a 503 to a paying user. We decode the base64
        then `json.loads`; the value itself is kept as-is (the validator only
        decodes + parses for the consumer in `billing/google_validator.py`).
        """
        if not value:
            return value
        import base64
        import binascii
        import json

        try:
            decoded = base64.b64decode(value, validate=True)
            json.loads(decoded)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_JSON must be a base64-encoded JSON "
                f"service-account key ({type(exc).__name__})"
            ) from exc
        return value

    @model_validator(mode="after")
    def _validate_google_billing_config_paired(self) -> "Settings":
        """Fail loud at boot on a HALF-configured Google billing deploy (8.1 F10).

        `validate_google` needs BOTH `google_play_package_name` AND
        `google_service_account_json`; with only one set, the server boots clean
        but every Android `/subscription/verify` raises `BillingConfigError` →
        503 to a real buyer. Catch the asymmetric `.env` at `systemctl restart`
        instead of mid-purchase. Neither set (pre-D4) is a valid state.
        """
        if bool(self.google_play_package_name) != bool(
            self.google_service_account_json
        ):
            raise ValueError(
                "GOOGLE_PLAY_PACKAGE_NAME and GOOGLE_SERVICE_ACCOUNT_JSON must be "
                "set together — Android subscription validation needs both (or "
                "neither, pre-store-setup)."
            )
        return self

    @model_validator(mode="after")
    def _validate_review_login(self) -> "Settings":
        r"""Fail loud at boot on a half/invalid review-login bypass (Story 10.3).

        The bypass is OFF when both fields are empty (the normal posture). When
        REVIEW_LOGIN_EMAIL is set it must be a non-blank, email-shaped value AND
        REVIEW_LOGIN_CODE must be exactly 6 digits. `/auth/verify-code`
        constrains the submitted code to `^\d{6}$` and matches on the NORMALISED
        email, so a blank-after-strip email (truthy but `"   "`) or a non-6-digit
        code would silently lock the reviewer out — the exact footgun this
        validator exists to prevent. Catch the misconfig at `systemctl restart`,
        not when the reviewer fails to sign in.
        """
        if self.review_login_email:
            email = self.review_login_email.strip()
            if not email or "@" not in email:
                raise ValueError(
                    "REVIEW_LOGIN_EMAIL must be a non-blank email address when "
                    "the review-login bypass is enabled"
                )
            if not re.fullmatch(r"\d{6}", self.review_login_code):
                raise ValueError(
                    "REVIEW_LOGIN_CODE must be exactly 6 digits when "
                    r"REVIEW_LOGIN_EMAIL is set (verify-code matches ^\d{6}$)"
                )
        return self

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
