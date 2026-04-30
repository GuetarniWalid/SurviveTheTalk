# Story 6.3: Implement Emotional Reactions and Lip Sync via Data Channels

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want the character's face to react in real-time to what I say and its lips to move when it speaks,
so that the character feels alive and genuinely responsive to my performance.

## Background

Story 6.1 lit up the call lifecycle plumbing (`CallBloc`, `Room`, root-Navigator push, foreground service). Story 6.2 layers the **render** (`RiveCharacterCanvas`, blurred scenario background, Rive-native hang-up button). Story 6.3 is the **first story that drives the Rive state machine inputs from server signals**: the character must (a) shift emotional expression in response to what the user is saying, and (b) lip-sync to its own TTS output. Both signals ride LiveKit data channels — a wire that Story 6.1's `CallBloc` does NOT yet subscribe to.

This story works **both halves** of the wire:

- **Server-side** — two NEW Pipecat `FrameProcessor`s (`EmotionEmitter` and `VisemeEmitter`) that observe pipeline frames, run an async LLM classification (emotion only) or a deterministic word→viseme mapping (viseme), and emit `OutputTransportMessageFrame(message=<dict>)`. The `LiveKitTransport` already serializes these into LiveKit data-channel packets (verified: `pipecat/transports/livekit/transport.py:914-931`).
- **Client-side** — a NEW `DataChannelHandler` that subscribes to `room.events.on<DataReceivedEvent>(...)`, decodes the JSON envelope (`{type, data}`), routes by `type`, and (for `emotion` / `viseme`) drives Rive `ViewModelInstanceEnum` setters on `RiveCharacterCanvas`.

**Three spec divergences to reconcile up-front** (all detected during story preparation; surface them in `## Dev Agent Record → Implementation Notes` per the Story 5.4 deviation pattern):

1. **Rive contract is 10 emotions / 12 visemes** (Story 2.6 deliverable §1+§2: `emotion` enum has 10 values — `satisfaction, smirk, frustration, impatience, anger, confusion, sadness, boredom, impressed, disgust_hangup`; `visemeId` enum has 12 — `rest, aei, cdgknstxyz, o, ee, chjsh, bmp, qwoo, r, l, th, fv`). The Epic 6 AC text for 6.3 says "7 emotional states" + "8 grouped viseme mouth shapes" — out of date relative to the actual `.riv` file. **Use the 10/12 truth from Story 2.6.** The 7 driven by 6.3's classifier are a subset (the runtime-reactive ones); `sadness`/`boredom`/`impressed` are reserved for downstream stories (e.g. `boredom` from Story 6.4 PatienceTracker low-energy threshold; `impressed` from Story 6.6 completion path).
2. **Cartesia returns word-level timestamps, not phoneme timestamps.** The architecture line 322 ("Viseme data: LiveKit data channels (Pipecat → Flutter) for lip sync animation") and line 59 ("phoneme timestamps from Cartesia mapped to 8 viseme states") are aspirational — verified at story prep that pipecat's `CartesiaTTSService` only surfaces word timestamps via `add_word_timestamps([(word, timestamp_seconds)])` (`pipecat/services/cartesia/tts.py:617`, `pipecat/services/tts_service.py:1127-1152`). **Word-level mapping is the spec for this story.** Each TTS word becomes 1 viseme transition driven by its strongest vowel (heuristic mapper, no g2p dependency added in this story).
3. **Story 6.2 is in-progress at 6.3 creation time.** The `RiveCharacterCanvas` widget AC3 specifies, the `_characterEnum` cache, the `RiveNative.isInitialized` fallback gate, the test mocking pattern — all pre-conditions for 6.3 — are still being implemented. **Story 6.3 must NOT begin until Story 6.2 is `done`.** The dependency is hard: 6.3 adds two more `viewModel.enumerator(...)` calls to the same widget and needs the working baseline. Confirm `sprint-status.yaml` shows `6-2-... done` before opening dev-story.

**Critical reading before starting:**
- `_bmad-output/implementation-artifacts/2-6-create-rive-character-puppet-file.md` — the **canonical** Rive contract: emotion 10-enum, viseme 12-enum, `onHangUp` event, single state machine, `DataBind.auto()` requirement.
- `_bmad-output/implementation-artifacts/6-1-build-call-initiation-from-scenario-list-with-connection-animation.md` — `CallBloc` ownership of the LiveKit `Room`, the `_disconnectCancel` listener pattern, the `_hangingUp` / `_connected` / `_roomDisconnected` guard flags.
- `_bmad-output/implementation-artifacts/6-2-build-call-screen-with-rive-character-canvas.md` — `RiveCharacterCanvas` widget shape, `_onRiveLoaded` ViewModel-cache pattern, `_riveFallback` test gate, `onFallback` callback contract.
- `_bmad-output/planning-artifacts/architecture.md` lines 184-208 (Rive 0.14.x rules), 320-323 (data channel intent), 606-618 (envelope format), 184-208 (one-way events).
- `_bmad-output/planning-artifacts/ux-design-specification.md` lines 446-475 (the 7 reactive emotional states with their trigger conditions).
- `memory/rive-flutter-rules.md` §5 (DataBind.auto only, listener removal in dispose, null-safe ViewModel reads), §9 (`viewModel.enumerator(...)` returns `ViewModelInstanceEnum?` whose `.value` is the **case-name string**, not an int).
- `client/CLAUDE.md` Gotchas #1 (`FlutterSecureStorage.setMockInitialValues({})`), #2 (`registerFallbackValue` for sealed events), #3 (`pumpAndSettle` hangs on continuous animations), #6 (token-enforcement test), #7 (`tester.binding.setSurfaceSize`).
- `pipecat/transports/livekit/transport.py:914-931` (`send_message` JSON-encodes dicts then `_client.send_data(message.encode())`) — **this is the proven server-side emit path**.
- `livekit_client-2.6.4/lib/src/events.dart:421-435` (`DataReceivedEvent` shape: `data: List<int>` UTF-8 bytes + optional `topic` String).

This is the third story of Epic 6. Story 6.4 owns silence handling + character hang-up trigger (PatienceTracker frame-processor, also emits via the data channel — but the `hang_up_warning` and `call_end` envelope types). Story 6.6 owns ExchangeClassifier (parallel async LLM for checkpoint advancement) — there is a real possibility the EmotionEmitter built in this story is folded into ExchangeClassifier later for cost amortization; **do NOT pre-merge them** (premature abstraction at N=1).

## Acceptance Criteria (BDD)

**AC1 — Server: `EmotionEmitter` FrameProcessor classifies user turns and emits `{"type":"emotion", "data":{...}}`:**
Given Pipecat exposes `OutputTransportMessageFrame(message=<any>)` and the LiveKit transport's `send_message` JSON-encodes dicts (verified at `pipecat/transports/livekit/transport.py:923-925`)
And the existing pipeline (`server/pipeline/bot.py`) is `transport.input() → stt → transcript_user → context_aggregator.user() → llm → transcript_character → tts → transport.output() → context_aggregator.assistant()`
When this story lands
Then a NEW `server/pipeline/emotion_emitter.py` defines `class EmotionEmitter(FrameProcessor)` with this contract:
  - **Observes** `TranscriptionFrame` (the user's transcribed speech) by overriding `process_frame(frame, direction)`. **Pass-through** is mandatory — the emitter MUST `await self.push_frame(frame, direction)` for every frame regardless of branch (frame-stealing breaks the pipeline downstream of the emitter).
  - **On `TranscriptionFrame` arrival** with non-empty text: schedules an async LLM classification call via `asyncio.create_task(...)` so the call NEVER blocks the main pipeline. The classifier task:
    1. Calls OpenRouter with the **same** `qwen/qwen3.5-flash-02-23` model (cost-efficient, low-latency — already paid-for credentials in `Settings.openrouter_api_key`), with a tight prompt: "Given the user's English line in a high-pressure conversation with `<character>`, classify the emotional reaction the character should show. Respond with strict JSON: `{\"emotion\": \"<one of: satisfaction|smirk|frustration|impatience|anger|confusion|disgust_hangup>\", \"intensity\": <float 0.0-1.0>}`. Rules: grammar mistakes → frustration or smirk; off-topic → confusion; aggressive/abusive → disgust_hangup; correct + appropriate → satisfaction." (Full prompt template lives in `pipeline/prompts.py:EMOTION_CLASSIFIER_PROMPT` — author it as a module-level f-string-able constant. The `<character>` placeholder is filled from a constructor arg `character: str` passed in by `bot.py`.)
    2. Parses the JSON output with a **defensive** `json.loads` inside a try/except (LLMs occasionally include prose around JSON). On parse failure or model-returned `emotion` outside the 7-value set, log at `WARNING` and emit nothing.
    3. On success, emits `await self.push_frame(OutputTransportMessageFrame(message={"type":"emotion","data":{"emotion": "<value>", "intensity": <float>}}), FrameDirection.DOWNSTREAM)`. The transport (`output()`) is downstream of the emitter, so DOWNSTREAM direction is correct.
  - **Timeout & fallback:** the classifier task is wrapped in `asyncio.wait_for(..., timeout=2.0)`. On `TimeoutError`, log at `WARNING` and emit nothing. The user MUST NEVER see an in-call error UI for a classifier failure (the character just stays in the previous emotional state; UX-DR6 / "graceful in-persona degradation").
  - **Concurrency cap:** at most **one** in-flight classifier task per emitter instance. New `TranscriptionFrame`s while a task is in-flight cancel-and-replace via `task.cancel()` then schedule fresh — the latest user line is the most relevant. Track via `self._in_flight: asyncio.Task | None`. Cancellation MUST be awaited (`await asyncio.gather(self._in_flight, return_exceptions=True)`) before replacement so the cancelled task does not push a stale frame after the new one.
  - **No state across calls:** the emitter is constructed once per `run_bot` invocation (one per call), so per-call isolation is automatic.
And the 7 enum-case strings emitted MUST be a subset of the Rive `emotion` enum values from Story 2.6 (`satisfaction, smirk, frustration, impatience, anger, confusion, disgust_hangup`). NEVER emit `sadness`, `boredom`, or `impressed` from this emitter — those values are reserved for Stories 6.4 (PatienceTracker boredom on prolonged silence) and 6.6 (ExchangeClassifier impressed on completion). A schema-level guard (a frozen `_ALLOWED_EMOTIONS = frozenset({...})` constant) MUST reject any other case at parse time.

**AC2 — Server: `VisemeEmitter` FrameProcessor maps Cartesia word timestamps to viseme transitions and emits `{"type":"viseme", "data":{...}}`:**
Given pipecat's TTS service surfaces word-level timestamps (NOT phonemes) via `TTSTextFrame` (`pipecat/frames/frames.py:428-435`) which is pushed downstream of the TTS service with `context_id` and `timestamp` (the per-word `timestamp` is in seconds, captured at the `(word, timestamp_seconds)` tuples Cartesia returns)
And the architecture's intended viseme envelope is `{"type": "viseme", "data": {"viseme_id": <int 0-11>, "timestamp_ms": <int>}}`
When this story lands
Then a NEW `server/pipeline/viseme_emitter.py` defines `class VisemeEmitter(FrameProcessor)` with this contract:
  - **Observes** `TTSTextFrame` (per-word frame from Cartesia via `_add_word_timestamps`). **Pass-through** is mandatory.
  - **On `TTSTextFrame` arrival**: extract `(word, timestamp_seconds)`. Convert `timestamp_seconds` → `timestamp_ms = int(round(timestamp_seconds * 1000))`. Map the word → `viseme_id: int` via the heuristic mapper described below. Emit `OutputTransportMessageFrame(message={"type":"viseme","data":{"viseme_id": <id>, "timestamp_ms": <ms>}})`. After every word emit a follow-up `viseme_id=0` (rest) at `timestamp_ms + estimated_word_duration_ms` to close the mouth between words. Estimate `word_duration_ms = max(80, len(word) * 60)` (a deliberately rough heuristic; real word durations are unavailable from pipecat's word-timestamp tuples).
  - **The heuristic word→viseme map** is implemented as a pure function `word_to_viseme_id(word: str) -> int` in `viseme_emitter.py`:
    ```python
    # Maps the dominant vowel (or consonant cluster) of a word to one of the 12
    # Rive visemeId enum cases. Order matches Story 2.6's enum (rest=0, aei=1,
    # cdgknstxyz=2, o=3, ee=4, chjsh=5, bmp=6, qwoo=7, r=8, l=9, th=10, fv=11).
    _VOWEL_GROUPS = (
        ('ee',  4, ('ee','ea','ie','y')),     # "see", "tea", "happy"
        ('aei', 1, ('a','e','i')),            # default vowel cluster
        ('o',   3, ('o','aw','au')),          # "got", "saw"
        ('qwoo',7, ('oo','oo','u','w')),      # "blue", "you"
    )
    _CONSONANT_HINTS = (
        ('th',   10, ('th',)),
        ('chjsh', 5, ('ch','sh','j')),
        ('fv',   11, ('f','v')),
        ('bmp',   6, ('b','m','p')),
        ('l',     9, ('l',)),
        ('r',     8, ('r',)),
        ('cdgknstxyz', 2, ('c','d','g','k','n','s','t','x','y','z')),
    )
    ```
    The function lowercases the input, strips punctuation, then: (1) tries each consonant hint substring — return the first match's id; (2) tries each vowel group — return the first match's id; (3) returns `1` (`aei`) as the default. Unit tests pin the dominant-letter outcome for ~15 representative words (a, the, hello, you, fish, mom, three, this, oil, little, run).
  - **Why a heuristic and not g2p_en or phonemizer**: adding `g2p_en` is ~50MB of NLTK data + a non-trivial cold-start latency. The architecture line 59 ("8 viseme states") was already a reduction from real phoneme mapping; this heuristic is a step further but produces visually-acceptable lip-flap at conversational speed (the user is watching a stylized 2D character, not a photoreal mouth). If post-MVP UX testing flags lip-sync quality as a blocker, the heuristic gets swapped for g2p_en in a dedicated story — the data-channel envelope and Flutter handler do NOT need to change. **Document this trade-off as Deviation #1 in Implementation Notes.**
  - **Pipeline insertion point**: after `tts` and before `transport.output()`. The transport's `send_message` then routes the `OutputTransportMessageFrame` to LiveKit data channel.

**AC3 — Server: pipeline wiring, no breakage of Stories 6.1 / 6.2 path:**
Given `server/pipeline/bot.py` currently builds the pipeline as `[transport.input(), stt, transcript_user, context_aggregator.user(), llm, transcript_character, tts, transport.output(), context_aggregator.assistant()]`
When this story lands
Then the pipeline becomes:
```python
pipeline = Pipeline([
    transport.input(),
    stt,
    transcript_user,
    EmotionEmitter(character=character_name, llm_settings=llm.settings),  # NEW — observes TranscriptionFrame, fires async LLM
    context_aggregator.user(),
    llm,
    transcript_character,
    tts,
    VisemeEmitter(),                                                       # NEW — observes TTSTextFrame, fires per-word viseme
    transport.output(),
    context_aggregator.assistant(),
])
```
And `EmotionEmitter` receives the `character: str` constructor arg derived from the scenario's `rive_character` field — `bot.py` reads it from a NEW env var `SCENARIO_CHARACTER` (set by `routes_calls.py:initiate_call` alongside the existing `SYSTEM_PROMPT` env var; the same `routes_calls.py:177` env-var injection pattern Story 6.1 established). `routes_calls.py` resolves it via `pipeline.scenarios.load_scenario_metadata(scenario_id)` — a NEW helper alongside `load_scenario_prompt` that returns the YAML's `metadata.rive_character` field. **NEVER** add a new top-level CLI flag to `bot.py` for this — the long-prompt-via-env precedent (Story 6.1, see `bot.py:38-41`) explicitly avoids argv length issues and is the established pattern.
And `VisemeEmitter` is constructor-arg-free; instantiate with `VisemeEmitter()`.
And the existing PoC `/connect` endpoint is **not** touched (it uses a different `bot.py` entry path; if its smoke test shows regression, that's a 6.3 bug). Confirm via `git grep -n 'EmotionEmitter\\|VisemeEmitter' server/` only matches the new files + `bot.py`.
And the existing `transcript_user` / `transcript_character` / `TranscriptCollector` flow is **unchanged** — emotion classification is an additive observer, not a replacement.

**AC4 — Client: `DataChannelHandler` subscribes to `DataReceivedEvent` and routes by envelope `type`:**
Given `livekit_client-2.6.4` exposes `class DataReceivedEvent with RoomEvent { final List<int> data; final String? topic; final RemoteParticipant? participant; ... }` (verified at `livekit_client/lib/src/events.dart:421`)
And `Room.events.on<DataReceivedEvent>(callback)` returns a `CancelListenFunc` (the same pattern Story 6.1 already uses for `RoomDisconnectedEvent` at `call_bloc.dart:52`)
When this story lands
Then a NEW `client/lib/features/call/services/data_channel_handler.dart` exposes:
```dart
/// Decodes Pipecat-side data-channel envelopes and forwards them to typed callbacks.
/// One instance per active call (constructed by `CallScreen.State` after the
/// `RiveCharacterCanvas` is mounted, disposed when the canvas is unmounted).
class DataChannelHandler {
  DataChannelHandler({
    required Room room,
    required void Function(String emotion, double intensity) onEmotion,
    required void Function(int visemeId, int timestampMs) onViseme,
  });

  /// Cancels the LiveKit subscription. Call from the owning State's dispose().
  Future<void> dispose();
}
```
And the implementation:
  1. In the constructor, calls `room.events.on<DataReceivedEvent>(_onDataReceived)` and stores the returned `CancelListenFunc` as `_cancel`.
  2. `_onDataReceived(DataReceivedEvent event)`: decode bytes via `utf8.decode(event.data)`, then `jsonDecode(...)` inside a try/catch. On any decode error, log at `debug` and return (an in-call decode error MUST NEVER reach the UI per UX-DR6).
  3. Switch on `payload['type']`:
     - `'emotion'`: extract `payload['data']['emotion']` (String) and `payload['data']['intensity']` (num → double via `?.toDouble() ?? 0.0`); call `onEmotion(emotion, intensity)`.
     - `'viseme'`: extract `payload['data']['viseme_id']` (int) and `payload['data']['timestamp_ms']` (int); call `onViseme(visemeId, timestampMs)`.
     - Anything else (`hang_up_warning`, `call_end`, `checkpoint_advanced`, unknown): swallow silently (log at `debug` for visibility — no `print`, use `dart:developer` `log()`). These envelopes are owned by Stories 6.4 / 6.5 / 6.7 and routed via the same handler when those stories land — the dispatcher MUST be additive.
  4. `dispose()`: `await _cancel?.call()` once, then null the handle.
And the file uses `import 'dart:convert';` for `utf8` + `jsonDecode`, `import 'dart:developer' as dev;` for `dev.log`, `import 'package:livekit_client/livekit_client.dart';`. NO `dart:io`, NO `print(...)`.
And the handler does NOT carry a reference to `RiveCharacterCanvas` or any widget — it only invokes the typed callbacks the owning widget injected. This keeps the handler unit-testable without Rive native.

**AC5 — Client: `RiveCharacterCanvas` exposes typed setters for emotion + viseme; `_emotionEnum` and `_visemeEnum` are cached:**
Given Story 6.2's `RiveCharacterCanvas` already caches `_characterEnum` in `_onRiveLoaded` (per AC5 of Story 6.2)
When this story lands
Then `RiveCharacterCanvas` is **modified** to:
  1. Add two more cached fields in `_RiveCharacterCanvasState`: `rive.ViewModelInstanceEnum? _emotionEnum;` and `rive.ViewModelInstanceEnum? _visemeEnum;`.
  2. Inside `_onRiveLoaded`, after caching `_characterEnum`, add:
     ```dart
     _emotionEnum = viewModel?.enumerator('emotion');
     _visemeEnum  = viewModel?.enumerator('visemeId');
     ```
     The names `'emotion'` and `'visemeId'` MUST match the Rive `.riv` ViewModel property names from Story 2.6 §1+§2. A null return means the property is missing — silent no-op per `rive-flutter-rules.md` §5 (do NOT throw; do NOT log error in prod — a schema mismatch is loud-failed by the smoke test, not by an in-call exception).
  3. Add two PUBLIC setter methods on the `State` class, exposed via a `GlobalKey<RiveCharacterCanvasState>` from the parent (`CallScreen`):
     ```dart
     void setEmotion(String emotion) {
       _emotionEnum?.value = emotion;
     }

     void setVisemeId(int visemeId) {
       const _idToCase = <int, String>{
         0: 'rest', 1: 'aei', 2: 'cdgknstxyz', 3: 'o', 4: 'ee', 5: 'chjsh',
         6: 'bmp', 7: 'qwoo', 8: 'r', 9: 'l', 10: 'th', 11: 'fv',
       };
       final caseName = _idToCase[visemeId];
       if (caseName == null) return;  // unknown id → no-op
       _visemeEnum?.value = caseName;
     }
     ```
     The integer→string id-to-case map mirrors Story 2.6 §3 verbatim. Define it as a private const map at top-of-file (NOT inline in the method body — easier to extract for testing).
  4. Promote the `State` class from `_RiveCharacterCanvasState` (private) to `RiveCharacterCanvasState` (public). The `GlobalKey<RiveCharacterCanvasState>` API is the agreed seam between `CallScreen` and the canvas. Document the promotion in Story 6.2's lineage if 6.2 had it private.
  5. The `dispose()` method of `_RiveCharacterCanvasState` already removes the Rive event listener (Story 6.2 AC3); ZERO change to dispose for this story. The cached enum fields are GC'd with the State.
And `setEmotion`/`setVisemeId` MUST be **idempotent** — calling with the same value twice in a row is a no-op for the Rive renderer (Rive deduplicates ViewModel writes internally). Tests assert via `verifyNever` after a duplicate call.

**AC6 — Client: `CallScreen` wires the handler into the canvas with correct lifecycle:**
Given `CallScreen` is a `StatefulWidget` (per Story 6.1) and currently builds `RiveCharacterCanvas` inside the `BlocBuilder<CallBloc, CallState>`'s `CallConnected` branch (per Story 6.2 AC1)
When this story lands
Then `_CallScreenState` adds:
  1. A `final GlobalKey<RiveCharacterCanvasState> _canvasKey = GlobalKey<RiveCharacterCanvasState>();` — the seam to the canvas.
  2. A `DataChannelHandler? _dataChannelHandler;` field — wired AFTER the LiveKit `Room` is connected (i.e., when the bloc enters `CallConnected`).
  3. Wires the handler in a `BlocListener<CallBloc, CallState>`'s `listenWhen` + `listener` pair (NOT inside `BlocBuilder.builder` — `BlocBuilder` runs on every rebuild and would attach the listener N times):
     ```dart
     BlocListener<CallBloc, CallState>(
       listenWhen: (prev, next) => prev is! CallConnected && next is CallConnected,
       listener: (context, state) {
         _dataChannelHandler ??= DataChannelHandler(
           room: context.read<CallBloc>().room,  // see AC7 — bloc exposes Room read-only
           onEmotion: (emotion, _) => _canvasKey.currentState?.setEmotion(emotion),
           onViseme: (id, _) => _canvasKey.currentState?.setVisemeId(id),
         );
       },
       child: BlocBuilder<CallBloc, CallState>( ... existing tree from 6.2 ... ),
     )
     ```
     The `intensity` parameter and the viseme `timestamp_ms` parameter are **received but unused** in this story — they're future hooks (intensity for emotion blending, timestamp for predictive scheduling); document the deliberate ignore as a comment so the reviewer doesn't flag dead arguments.
  4. The `RiveCharacterCanvas` is constructed with the `_canvasKey`: `RiveCharacterCanvas(key: _canvasKey, character: widget.scenario.riveCharacter, onHangUp: ...)`. **DO NOT** mark the State public class fully — the State class is the type bound, the widget remains as-is.
  5. `_CallScreenState.dispose()` calls `_dataChannelHandler?.dispose()` BEFORE `super.dispose()`. The handler's own `dispose` is idempotent (re-entrant `_cancel = null` after first call) per AC4.
And the `BlocListener` MUST also clean up if the call ends and re-enters (e.g. error → reconnect path) — `listenWhen` ensuring `prev is! CallConnected && next is CallConnected` plus the `??=` null-check together handle the "first connect only" case correctly. Document the choice in Dev Notes.

**AC7 — `CallBloc` exposes the `Room` read-only so `DataChannelHandler` can subscribe without breaking encapsulation:**
Given Story 6.1's `CallBloc._room` is a private field (verified at `client/lib/features/call/bloc/call_bloc.dart:15`) and the bloc owns the room lifecycle (`connect`, `disconnect`, listener-cancel via `_disconnectCancel`)
When this story lands
Then `CallBloc` **adds** a public read-only getter:
```dart
/// Read-only access to the underlying LiveKit Room for non-lifecycle subscriptions
/// (e.g. data-channel events). The bloc remains the single owner of the Room's
/// connect/disconnect lifecycle. DO NOT call `disconnect()` on this Room from
/// outside the bloc — emit a HangUpPressed event instead.
Room get room => _room;
```
And the doc comment is mandatory — it states the contract that the bloc keeps lifecycle ownership. A future maintainer who skims the getter without reading the doc could be tempted to cancel a track or disconnect from outside; the comment is the lint.
And `_room`'s privacy is **kept** (not promoted to public field) — the getter is the only outside surface. This is the established pattern from Story 5.5's `previousState` / `ApiException.statusCode` review patches.
And NO other `CallBloc` API surface changes in this story. `CallEvent`, `CallState`, the constructor, the handlers — all unchanged.

**AC8 — Server smoke test: emotion + viseme envelopes flow end-to-end on real VPS deploy:**
Given the established Smoke Test Gate (Epic 4 retro lesson, Story 5.1 pattern, Story 6.1 enforcement)
And the canonical envelope format `{"type": "<t>", "data": {...}}` (architecture lines 606-616)
When this story lands and is deployed to VPS
Then the dev validates END-TO-END from a real device:
  1. **Server stays up** under load: `systemctl status pipecat.service` shows `active (running)` after the new emitters are wired (the OpenRouter LLM call is a network IO operation that can fail; `EmotionEmitter`'s `asyncio.wait_for` MUST prevent pipeline stall).
  2. **Emotion envelopes appear** at the client: a 30-second test call using The Waiter scenario (English-clean responses) produces ≥ 1 `{"type":"emotion", ...}` data-channel envelope per minute, observed via a temporary `dev.log(...)` injected into `DataChannelHandler._onDataReceived` and read from `flutter logs` on the device. Document the count and the observed emotion values.
  3. **Viseme envelopes track TTS playback**: during character speech, ≥ 1 `{"type":"viseme", ...}` envelope per word arrives at the client. Visible as the Rive `visemeId` enum changing in real time on the canvas (the mouth shape shifts through `aei`, `o`, `ee`, etc.). Verify by visual inspection on the Pixel 9 Pro XL — the dev does NOT need the FPS overlay, but the lip-flap MUST be visible during character speech and stop (rest viseme) between words.
  4. **No traceback in `journalctl -u pipecat.service -n 100 --since "5 min ago"`** during or after the test call. A traceback in the emotion-classifier path is a hard fail (the `asyncio.wait_for` + try/except block is the canonical container).
  5. **Stale-task guarantee:** make 3 user turns within 5 seconds (rapid-fire). Confirm via server logs that older `EmotionEmitter` tasks are cancelled — log the `INFO` line `cancelled stale emotion-classifier task`. The third user turn's classification is the only one that emits; the prior two are suppressed.

**AC9 — Test coverage (server + client):**
Given the project's dual test discipline (`server/tests/` mirroring `server/`, `client/test/` mirroring `client/lib/`) and the Story 5.1 / 6.1 patterns
When this story lands
Then the following NEW / UPDATED tests are green:

**Server (Python, pytest):**
  - **`server/tests/pipeline/test_emotion_emitter.py`** (NEW) — 6 tests:
    1. Pass-through: a `TranscriptionFrame` arrives, `process_frame` calls `push_frame(frame, direction)` regardless of classifier outcome (assert via a fake downstream `FrameProcessor` that records pushed frames).
    2. Happy path: a `TranscriptionFrame("I am ordering food.")` triggers an LLM call (mocked at the OpenRouter HTTP boundary via `httpx.MockTransport`); the parsed response `{"emotion":"satisfaction","intensity":0.7}` becomes a `OutputTransportMessageFrame(message={"type":"emotion","data":{...}})`.
    3. Invalid emotion rejection: mock LLM returns `{"emotion":"sadness","intensity":0.5}` (a value reserved for downstream stories); assert NO `OutputTransportMessageFrame` emitted, log `WARNING` captured via `caplog`.
    4. JSON parse failure: mock LLM returns `"I think frustration"` (prose); assert NO emit, `WARNING` logged.
    5. Timeout: mock LLM `asyncio.sleep(3.0)`; with `timeout=2.0`, assert NO emit, `WARNING` logged with "emotion classifier timeout".
    6. Stale-task cancellation: dispatch 3 `TranscriptionFrame`s in quick succession (`asyncio.sleep(0.01)` between); assert only the third's verdict reaches `push_frame` as a `OutputTransportMessageFrame` (the first two tasks were cancelled).
  - **`server/tests/pipeline/test_viseme_emitter.py`** (NEW) — 4 tests:
    1. `word_to_viseme_id` returns the dominant-letter id for ~15 representative words (table-driven test). Pin: `'a' → 1`, `'the' → 10`, `'hello' → 9`, `'you' → 7`, `'fish' → 11`, `'mom' → 6`, `'three' → 10`, `'this' → 10`, `'oil' → 9`, `'little' → 9`, `'run' → 8`, `'see' → 4`, `'go' → 3`, `'cat' → 2`, `'red' → 8`. Edge cases: empty string → 1, punctuation-only `"..."` → 1.
    2. On `TTSTextFrame("hello", timestamp=1.5)`: emits `{"type":"viseme","data":{"viseme_id": 9, "timestamp_ms": 1500}}` (downstream).
    3. After every word emit: emits a follow-up rest viseme (`viseme_id=0`) at `timestamp_ms + word_duration_ms`. Assert via the recorded-frames helper.
    4. Pass-through: `TTSTextFrame` is forwarded downstream regardless of mapping.
  - **`server/tests/pipeline/test_bot_pipeline_wiring.py`** (NEW or UPDATED — depending on whether 6.1 added one) — 1 test:
    - `run_bot` (smoke-instantiated, `transport.input/output` mocked) builds a pipeline whose ordered processors include `EmotionEmitter` (between `transcript_user` and `context_aggregator.user()`) and `VisemeEmitter` (between `tts` and `transport.output()`). Assert by `isinstance` over the iterated `pipeline._processors` (or whatever the public list-getter is in the installed pipecat version — verify before writing).
  - **`server/tests/api/test_routes_calls.py`** (UPDATED) — 1 new test:
    - `routes_calls.initiate_call` reads `metadata.rive_character` from the loaded YAML and passes it as the `SCENARIO_CHARACTER` env var on `subprocess.Popen`. Assert via `Popen` mock and the `env` kwarg.
  - **`server/tests/pipeline/test_scenarios.py`** (UPDATED if it exists; create if not) — 1 new test:
    - `load_scenario_metadata("the_waiter")` returns a dict whose `rive_character` is `"waiter"` (matches the YAML's `metadata.rive_character` value).

**Client (Dart, flutter test):**
  - **`client/test/features/call/services/data_channel_handler_test.dart`** (NEW) — 8 tests:
    1. Constructor subscribes to `room.events.on<DataReceivedEvent>(...)` exactly once (verified via mock).
    2. `dispose()` calls the cancel function exactly once.
    3. `dispose()` is idempotent (calling twice does not double-cancel).
    4. `{"type":"emotion","data":{"emotion":"satisfaction","intensity":0.7}}` envelope: `onEmotion('satisfaction', 0.7)` is called.
    5. `{"type":"viseme","data":{"viseme_id":4,"timestamp_ms":1500}}` envelope: `onViseme(4, 1500)` is called.
    6. Unknown type `{"type":"checkpoint_advanced",...}`: neither callback is invoked, no exception.
    7. Malformed JSON (`"not-json"` bytes): no callbacks, no exception (caught + logged at debug).
    8. Missing inner field (`{"type":"emotion","data":{}}`): no callbacks, no exception.
  - **`client/test/features/call/views/widgets/rive_character_canvas_test.dart`** (UPDATED from Story 6.2) — 2 new tests added to the existing fallback-only test:
    1. `setEmotion(...)` is callable on `RiveCharacterCanvasState` in fallback mode without throwing (the `_emotionEnum?.value = ...` is a null-safe no-op when the cache is null).
    2. `setVisemeId(4)` and `setVisemeId(99)` (out-of-range) both no-op in fallback mode without throwing.
  - **`client/test/features/call/bloc/call_bloc_test.dart`** (UPDATED) — 1 new test:
    - `CallBloc.room` getter returns the same `Room` instance passed to the constructor. Verify via `expect(identical(bloc.room, room), isTrue)`.
  - **`client/test/features/call/views/call_screen_test.dart`** (UPDATED from Story 6.2) — 2 new tests:
    1. When the bloc emits `CallConnected`, a `DataChannelHandler` is constructed exactly once; subsequent `CallConnected` re-emissions do NOT create a second handler (verified via a constructor-injection seam OR by counting the mock `Room.events.on<DataReceivedEvent>(...)` calls).
    2. `_CallScreenState.dispose()` calls `_dataChannelHandler?.dispose()` (verified by asserting the mock cancel function was invoked).

Coverage rules (from prior epics — non-negotiable):
- `FlutterSecureStorage.setMockInitialValues({})` in every Flutter test setUp that transitively touches `TokenStorage` (Gotcha #1).
- `registerFallbackValue(...)` for sealed `CallEvent` if the bloc test needs new mocktail verifications (Gotcha #2; Story 6.1 already establishes the pattern).
- Use `pumpEventQueue()` (NOT `pumpAndSettle`, NOT `Future.delayed(Duration.zero)`) wherever event-queue flushing is needed (Gotcha #3 + Story 5.5 patch).
- Use `tester.binding.setSurfaceSize(const Size(320, 480))` for any new layout test (Gotcha #7) — the layout itself does not change in 6.3 but if a new test exercises CallScreen, set the size.
- `FlutterError.onError` overflow capture pattern (Story 5.4 / 5.5) is reused if any new layout test runs against `CallScreen` at small viewport.
- pytest server tests use `pytest.asyncio` with `asyncio_mode = "auto"` (already configured); use `httpx.MockTransport` for OpenRouter mocking (the same pattern Story 4.2 / 5.5 use for HTTP-boundary mocks).
- ZERO `print(...)` left in shipping code (the dev's tempo `dev.log(...)` for client smoke debugging is removed before commit).

**AC10 — Pre-commit gates + Smoke Test Gate (Server / Deploy story):**
Given the dual-side discipline (CLAUDE.md root: `flutter analyze` + `flutter test` for client, `ruff check .` + `ruff format --check .` + `pytest` for server)
And this story changes both `server/` AND `client/` — therefore the Smoke Test Gate below is **mandatory** and not omitted.
When the story lands
Then ALL of the following pass before flipping the story to `review`:
  - `cd server && python -m ruff check .` → zero issues.
  - `cd server && python -m ruff format --check .` → zero issues.
  - `cd server && .venv/Scripts/python -m pytest` → all green; expect ~10 new test cases on top of the ~145 baseline (Story 5.5 final count) → target ≥ 155 passing.
  - `cd client && flutter analyze` → "No issues found!".
  - `cd client && flutter test` → "All tests passed!" — full suite. Expect ~13 net new tests on top of Story 6.2's baseline.
  - The token-enforcement test (`test/core/theme/theme_tokens_test.dart`) passes — Story 6.3 introduces ZERO new colors.
  - Database migrations are NOT touched (this story is purely pipeline + handlers, no DB). Confirm `git diff --name-only -- server/db/migrations/` is empty. If it isn't, you accidentally regressed something — investigate before committing.
  - `tests/test_migrations.py` (the prod-snapshot replay) is green — same reason.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** Story 6.3 ships server pipeline changes (`EmotionEmitter`, `VisemeEmitter`, `bot.py` wiring, `routes_calls.py` env-var addition) AND requires VPS deploy. Gate is **mandatory**, no exceptions.
>
> **Transition rule:** Every unchecked box below is a stop-ship for the `in-progress → review` transition. Paste the actual command run and its output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->

- [ ] **Happy-path call: end-to-end emotion + viseme envelopes arrive at the client.** A 30-second call from the device on the The Waiter scenario produces ≥ 1 `{"type":"emotion",...}` and ≥ 1 `{"type":"viseme",...}` per second of TTS playback, observed via a temporary `dev.log` in `DataChannelHandler._onDataReceived` and read from `adb logcat` (Android) or `flutter logs` (device).
  - _Command:_ `flutter run --release` on Pixel 9 Pro XL → tap The Waiter → speak 3-4 lines → tap hang-up → review the log buffer.
  - _Expected:_ Multiple `dev.log` lines for both `type: emotion` and `type: viseme`. The `emotion` value is one of the 7 reactive values. The `viseme_id` is in `0..11`.
  - _Actual:_ <!-- paste 5-10 representative lines + summary of counts -->

- [ ] **Emotion classifier respects the 7-value subset.** No `sadness`, `boredom`, or `impressed` reach the client during the test call. (These are reserved for stories 6.4 / 6.6 / 6.7.)
  - _Command:_ `grep -E "type.*emotion" <flutter-log-buffer> | grep -oE "emotion.: ?\"[^\"]+\"" | sort -u`
  - _Expected:_ All values in `{satisfaction, smirk, frustration, impatience, anger, confusion, disgust_hangup}`.
  - _Actual:_ <!-- paste the unique emotion values observed -->

- [ ] **Stale-task cancellation works.** Make 3 user turns within 5 seconds; only the third triggers an emotion envelope.
  - _Command:_ `ssh root@167.235.63.129 "journalctl -u pipecat.service --since '5 min ago' | grep -E 'cancelled stale|emotion classifier'"`
  - _Expected:_ ≥ 2 `cancelled stale emotion-classifier task` log lines per 3-rapid-turn burst.
  - _Actual:_ <!-- paste -->

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 100 --since "10 min ago"` shows no ERROR or Traceback for the test calls.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

- [ ] **DB side-effect is `N/A`.** This story does not write or migrate any DB tables; the only DB write during the test is the existing Story 6.1 INSERT into `call_sessions` (one row per call).
  - _Command:_ `ssh root@167.235.63.129 "/opt/survive-the-talk/repo/server/.venv/bin/python -c 'import sqlite3; c=sqlite3.connect(\"/opt/survive-the-talk/data/db.sqlite\"); print(c.execute(\"SELECT COUNT(*) FROM call_sessions\").fetchone())'"`
  - _Expected:_ count went up by 1 per smoke-test call; no other table changed.
  - _Actual:_ <!-- paste -->

- [ ] **DB backup taken BEFORE deploy.** `N/A` — this story has zero schema changes. Mark with one-line rationale: "No migration; no backup required."
  - _Proof:_ N/A — non-migration story.

- [ ] **Error envelope still works for `/calls/initiate` (regression net for Story 6.1).** Hit the endpoint with an expired JWT; confirm the canonical `{error}` envelope is unchanged.
  - _Command:_ `curl -sS -H "Authorization: Bearer expired-jwt" -H "Content-Type: application/json" -d '{"scenario_id":"the_waiter"}' http://167.235.63.129/calls/initiate`
  - _Expected:_ `401` + `{"error": "AUTH_UNAUTHORIZED", ...}`.
  - _Actual:_ <!-- paste -->

## Tasks / Subtasks

- [ ] **Task 1 — Author `EmotionEmitter` Pipecat FrameProcessor** (AC: #1)
  - [ ] 1.1 — Create `server/pipeline/emotion_emitter.py` with the `EmotionEmitter(FrameProcessor)` class. Inherit from `pipecat.processors.frame_processor.FrameProcessor`.
  - [ ] 1.2 — Add `_ALLOWED_EMOTIONS = frozenset({'satisfaction','smirk','frustration','impatience','anger','confusion','disgust_hangup'})` at module level.
  - [ ] 1.3 — Override `process_frame(self, frame, direction)`: pass-through with `await self.push_frame(frame, direction)`; on `TranscriptionFrame` with non-empty `text`, schedule classification via `asyncio.create_task` after cancelling any in-flight task.
  - [ ] 1.4 — Implement `_classify(text: str) -> dict | None` as a coroutine. Builds the prompt using `EMOTION_CLASSIFIER_PROMPT` (added to `pipeline/prompts.py` in Task 4); calls OpenRouter via `httpx.AsyncClient` (one ephemeral client per call OR shared with `bot.py`'s `OpenRouterLLMService` — the simpler path is a fresh client; document the choice). Returns `{"emotion","intensity"}` on success, `None` on JSON parse fail, model-returned-out-of-set, or HTTP error.
  - [ ] 1.5 — `asyncio.wait_for(self._classify(text), timeout=2.0)` wraps the call; on `TimeoutError` log `WARNING` and return None.
  - [ ] 1.6 — On non-None result, `await self.push_frame(OutputTransportMessageFrame(message={"type":"emotion","data": result}), FrameDirection.DOWNSTREAM)`.
  - [ ] 1.7 — Track in-flight task on `self._in_flight: asyncio.Task | None = None`. New transcription cancels old via `task.cancel()` + `await asyncio.gather(task, return_exceptions=True)`; log `INFO "cancelled stale emotion-classifier task"`.
  - [ ] 1.8 — Add tests at `server/tests/pipeline/test_emotion_emitter.py` covering AC9 server-side cases 1-6.

- [ ] **Task 2 — Author `VisemeEmitter` Pipecat FrameProcessor** (AC: #2)
  - [ ] 2.1 — Create `server/pipeline/viseme_emitter.py` with the `VisemeEmitter(FrameProcessor)` class.
  - [ ] 2.2 — Implement `word_to_viseme_id(word: str) -> int` as a pure module-level function with the `_VOWEL_GROUPS` and `_CONSONANT_HINTS` tuples from AC2.
  - [ ] 2.3 — Override `process_frame`: pass-through `TTSTextFrame` always; on `TTSTextFrame` extract `(word, timestamp_seconds)` (verify the actual attribute names from `TTSTextFrame` at implementation time — they may differ from the `_WordTimestampEntry` shape); compute `viseme_id` + `timestamp_ms`; emit primary viseme; emit follow-up rest viseme at `timestamp_ms + word_duration_ms` where `word_duration_ms = max(80, len(word) * 60)`.
  - [ ] 2.4 — Add tests at `server/tests/pipeline/test_viseme_emitter.py` covering AC9 server-side cases 1-4.

- [ ] **Task 3 — Add `load_scenario_metadata` helper + plumb `SCENARIO_CHARACTER` env var** (AC: #3)
  - [ ] 3.1 — In `server/pipeline/scenarios.py`, add a NEW helper `load_scenario_metadata(scenario_id: str) -> dict` that reads the same YAML file `load_scenario_prompt` reads but returns the entire `metadata` block (or at least `metadata.rive_character`). Ensure the existing `load_scenario_prompt` still works unchanged (its return type/signature is the spec for Story 6.1's path).
  - [ ] 3.2 — In `server/api/routes_calls.py`, after calling `load_scenario_prompt`, also call `load_scenario_metadata` and extract `metadata['rive_character']`. Add it to the `bot_env` dict alongside `SYSTEM_PROMPT`: `bot_env = {**os.environ, "SYSTEM_PROMPT": system_prompt, "SCENARIO_CHARACTER": rive_character}`.
  - [ ] 3.3 — Update tests in `server/tests/api/test_routes_calls.py` to verify the new env var is set on the spawned subprocess.

- [ ] **Task 4 — Wire `EmotionEmitter` + `VisemeEmitter` into `bot.py`** (AC: #3)
  - [ ] 4.1 — In `server/pipeline/prompts.py`, add `EMOTION_CLASSIFIER_PROMPT` as a module-level f-string-able constant (the prompt template from AC1).
  - [ ] 4.2 — In `server/pipeline/bot.py`, read `os.environ.get("SCENARIO_CHARACTER", "waiter")` (default to waiter for the legacy `/connect` path).
  - [ ] 4.3 — Instantiate `EmotionEmitter(character=character_name, openrouter_api_key=settings.openrouter_api_key)` and `VisemeEmitter()`.
  - [ ] 4.4 — Insert into the pipeline list at the positions specified in AC3.
  - [ ] 4.5 — Smoke-run locally with `uv run python -m pipeline.bot --url ... --room ... --token ...` against a dev LiveKit room (or document why local smoke is skipped — probably needs the full FastAPI scaffolding to mint a token).
  - [ ] 4.6 — Add `server/tests/pipeline/test_bot_pipeline_wiring.py` (or update existing) per AC9 server case 7.

- [ ] **Task 5 — Author `DataChannelHandler` service** (AC: #4)
  - [ ] 5.1 — Create `client/lib/features/call/services/data_channel_handler.dart`. Constructor takes `Room`, `onEmotion`, `onViseme`. Internal: `CancelListenFunc? _cancel;`.
  - [ ] 5.2 — In constructor, call `room.events.on<DataReceivedEvent>(_onDataReceived)`; store the cancel handle.
  - [ ] 5.3 — `_onDataReceived` decodes `utf8.decode(event.data)` → `jsonDecode(...)`; switches on `payload['type']`; calls the typed callbacks. Errors (decode, missing fields) are caught and logged via `dev.log` at level `Level.FINE` (700) — never thrown.
  - [ ] 5.4 — `dispose()` is idempotent: `await _cancel?.call(); _cancel = null;`.
  - [ ] 5.5 — Add tests at `client/test/features/call/services/data_channel_handler_test.dart` covering AC9 client-side cases 1-8. Use `mocktail` for `Room` and `RemoteParticipant`. Mock `room.events.on<DataReceivedEvent>(...)` to return a `CancelListenFunc` recorded in the test for assertions.

- [ ] **Task 6 — Extend `RiveCharacterCanvas` with `setEmotion` / `setVisemeId`** (AC: #5)
  - [ ] 6.1 — In `client/lib/features/call/views/widgets/rive_character_canvas.dart`, promote `_RiveCharacterCanvasState` → `RiveCharacterCanvasState` (drop the leading underscore on the class name; keep the constructor `_RiveCharacterCanvasState()` form unchanged at the framework boundary).
  - [ ] 6.2 — Add `rive.ViewModelInstanceEnum? _emotionEnum;` and `rive.ViewModelInstanceEnum? _visemeEnum;` fields.
  - [ ] 6.3 — In `_onRiveLoaded`, after caching `_characterEnum`, cache `_emotionEnum` and `_visemeEnum` via `viewModel?.enumerator('emotion')` and `viewModel?.enumerator('visemeId')`.
  - [ ] 6.4 — Add public `setEmotion(String emotion)` and `setVisemeId(int visemeId)` methods per AC5.
  - [ ] 6.5 — Add the `_idToCase` private const map at top-of-file.
  - [ ] 6.6 — Update `client/test/features/call/views/widgets/rive_character_canvas_test.dart` per AC9 client case 2 (2 new tests).

- [ ] **Task 7 — Expose `Room` from `CallBloc`** (AC: #7)
  - [ ] 7.1 — In `client/lib/features/call/bloc/call_bloc.dart`, add the `Room get room => _room;` getter with the documented contract from AC7.
  - [ ] 7.2 — Update `client/test/features/call/bloc/call_bloc_test.dart` per AC9 client case 3.

- [ ] **Task 8 — Wire `DataChannelHandler` into `CallScreen`** (AC: #6)
  - [ ] 8.1 — In `client/lib/features/call/views/call_screen.dart`, add `_canvasKey: GlobalKey<RiveCharacterCanvasState>` and `_dataChannelHandler: DataChannelHandler?` fields.
  - [ ] 8.2 — Wrap the existing `BlocBuilder` (Story 6.2's tree) inside a `BlocListener<CallBloc, CallState>` with `listenWhen` filter per AC6.
  - [ ] 8.3 — In the `listener` callback, construct the `DataChannelHandler` once with closures into `_canvasKey.currentState`.
  - [ ] 8.4 — Pass `key: _canvasKey` into `RiveCharacterCanvas(...)`.
  - [ ] 8.5 — In `dispose()`, `await _dataChannelHandler?.dispose();` BEFORE `super.dispose()`.
  - [ ] 8.6 — Update `client/test/features/call/views/call_screen_test.dart` per AC9 client case 4 (2 new tests).

- [ ] **Task 9 — Pre-commit + Smoke Test gates** (AC: #8, #10)
  - [ ] 9.1 — `cd server && python -m ruff check .` + `python -m ruff format --check .` + `.venv/Scripts/python -m pytest` all green.
  - [ ] 9.2 — `cd client && flutter analyze` "No issues found!"
  - [ ] 9.3 — `cd client && flutter test` "All tests passed!"
  - [ ] 9.4 — Commit (Walid will trigger via `/commit` — DO NOT auto-commit).
  - [ ] 9.5 — Deploy to VPS via SSH: `scp` the changed files, `systemctl restart pipecat.service`, OR (if a CI deploy pipeline is wired) push + watch the workflow.
  - [ ] 9.6 — Execute the Smoke Test Gate above, paste proofs into the unchecked boxes.
  - [ ] 9.7 — Flip `sprint-status.yaml` for `6-3-...` from `in-progress` → `review` (story file frontmatter Status field updated simultaneously per project memory `## Sprint-Status Discipline`).
  - [ ] 9.8 — Wait for explicit `/commit` from Walid (per project memory `## Git Commit Rules`).

## Dev Notes

### Hard prerequisite: Story 6.2 must be `done` before opening dev-story 6.3

`RiveCharacterCanvas` (created by 6.2 Task 3), the `_characterEnum` cache (6.2 AC5), the `RiveNative.isInitialized` fallback gate (6.2 AC7), the `Container(color: AppColors.background)` fallback widget (6.2 AC7), the `Semantics(label:'End call', button: true, child: ...)` wrapper (6.2 AC6), and the `BlocBuilder<CallBloc, CallState>` `CallConnected` branch render contract (6.2 AC1) — **all** are inputs to 6.3. Confirm:

```bash
grep -E "^\s+6-2.*: done" _bmad-output/implementation-artifacts/sprint-status.yaml
```

If 6.2 is still `in-progress` or `review`, halt 6.3 dev-story and ping Walid. Working off an unfinished 6.2 produces merge headaches and conflicts inside the very file (`rive_character_canvas.dart`) that both stories edit.

### Why a heuristic word→viseme mapper instead of g2p_en or phonemizer (AC2 / Deviation #1)

The architecture line 59 ("phoneme timestamps from Cartesia mapped to 8 viseme states") describes a future-state pipeline that does NOT exist today. Cartesia's actual pipecat integration surfaces only word-level timestamps via `add_word_timestamps([(word, timestamp_seconds)])` — confirmed by reading `pipecat/services/cartesia/tts.py:617` and `pipecat/services/tts_service.py:1127-1152`. Two paths to "real" lip sync:

| Path | Cost | Quality | Decision |
|---|---|---|---|
| **A. Heuristic word→viseme** | Free; ~30 lines of code | Approximate but visually-acceptable lip-flap at conversation speed | **CHOSEN for 6.3** |
| **B. g2p_en + phoneme→viseme** | +50 MB NLTK CMUDict download; +50-100 ms cold start; ~5 MB RAM overhead | True per-phoneme lip sync | Deferred to a post-MVP polish story |

Path A's quality at conversational speed is "close enough" — the user is watching a stylized 2D character at 1-2 m viewing distance, not a photoreal mouth at 30 cm. The data-channel envelope is the same; if path B is later chosen the only change is `viseme_emitter.py` (the Flutter side and the envelope are unaffected). **Surface this as Deviation #1 in `## Dev Agent Record → Implementation Notes`.**

### Why a separate `EmotionEmitter` instead of co-locating with `ExchangeClassifier` (Story 6.6)

Story 6.6 will build an `ExchangeClassifier` async LLM that judges each user turn against the current checkpoint's `success_criteria`. There is real overlap with `EmotionEmitter`'s "judge each user turn for emotional reaction" concern. Tempting to pre-merge them. Reasons not to:

1. **Different prompts, different output schemas.** Emotion classifier returns `{emotion, intensity}` (7-value enum + float). Exchange classifier returns `{met: bool}`. Forcing them into one LLM call requires two-output parsing — error-prone.
2. **Different latency budgets.** Emotion can be best-effort lossy (a missed verdict means the character stays in the previous emotion — fine). Exchange checkpoint advancement is binary and event-driving (a missed verdict means the conversation gets stuck — not fine). Combining the two means the slower one drags the faster one.
3. **Different epics.** 6.3 ships emotion now. 6.6 ships exchange later. Pre-merging means 6.3 carries unused exchange-classifier scaffolding.
4. **Premature abstraction at N=1.** Three similar processors would justify a base class; two does not (`feedback_mvp_iteration_strategy.md`).

If post-Story 6.6 cost analysis shows the doubled LLM call is material, a follow-up refactor merges them — at that point the shape is known. **Document this as a Future Coupling Note in Implementation Notes** so the 6.6 author considers it.

### Per-call Pipecat process means per-call emitter state (AC1, AC2)

Story 6.1's `routes_calls.py:179-192` spawns a fresh `python -m pipeline.bot` subprocess per call. Each emitter is constructed fresh inside that process, so per-call state isolation is automatic — no need for `__del__` / `cleanup` hooks beyond what `FrameProcessor` already provides. This also means a corrupt classifier task in call A cannot affect call B.

### LiveKit data-channel routing — same `Room`, no topic filter

The Pipecat side calls `await self._client.send_data(message.encode())` (no `destination_identities` for our use case → broadcast to all participants in the room). On the client, `DataReceivedEvent.topic` is `null` (we don't set a topic from Pipecat). The handler does NOT filter by topic; the JSON `type` field is the discriminator. If a future story needs targeted (per-participant) routing, set the `participant_id` on `LiveKitOutputTransportMessageFrame` and filter by `event.participant?.identity` on the client.

### Emit direction: DOWNSTREAM only, after the LLM output

Both emitters use `FrameDirection.DOWNSTREAM` so the `OutputTransportMessageFrame` flows toward `transport.output()` (which is downstream of both emitters in the pipeline). UPSTREAM emission would route the frame back through `llm` / `stt` (incorrect — the LLM aggregator would error on an unknown frame type). Pipecat's frame-direction discipline is one-way; document this in code comments inside `EmotionEmitter._classify` and `VisemeEmitter.process_frame`.

### Anti-patterns to avoid (LLM-developer disaster prevention)

- ❌ **Do NOT** add `g2p_en`, `phonemizer`, or any other phoneme library to `pyproject.toml` in this story. The heuristic word→viseme mapper is the spec (AC2 + "Why a heuristic" above).
- ❌ **Do NOT** modify `Cartesia` integration internals (`pipecat/services/cartesia/tts.py`) — it's a `.venv` package, edits would be lost on `uv sync`. The `VisemeEmitter` consumes `TTSTextFrame` (the public output of Cartesia) — that's the contract.
- ❌ **Do NOT** broadcast the user's transcribed text to Flutter via the data channel. The transcript stays server-side (`TranscriptCollector` already captures it for debrief generation). Flutter's UI surface during the call is **zero text** (UX-DR6) — see Story 6.2 AC6 for the hard rule.
- ❌ **Do NOT** publish data from Flutter to Pipecat. The data channel is **one-way** for this story (Pipecat → Flutter). Bidirectional data is a different pattern Pipecat supports (`@transport.event_handler("on_data_received")` server-side) but no story drives it before Epic 6.6 (CheckpointManager request/response — and even there the client doesn't publish data; the LLM context aggregator is the inbound channel).
- ❌ **Do NOT** use `print(...)` in Flutter or `print(...)` / `print(file=sys.stderr,...)` in Python. Server side: `from loguru import logger`. Client side: `import 'dart:developer' as dev; dev.log(...)`. Loguru is already configured in `bot.py`. `dev.log` integrates with Flutter DevTools and respects log-level filtering.
- ❌ **Do NOT** subscribe to `DataReceivedEvent` from inside `CallBloc`. The bloc owns connect/disconnect lifecycle, but the data-channel listener belongs to `DataChannelHandler` (single-responsibility). The bloc exposes `room` (AC7); the handler subscribes; the handler is owned by `_CallScreenState`. Story 6.4 may add `hang_up_warning` handling — when it does, that's a SECOND callback on the same handler, NOT a new listener inside the bloc.
- ❌ **Do NOT** attach the `DataReceivedEvent` listener inside `BlocBuilder.builder` — `builder` runs on every rebuild. Use `BlocListener.listener` with `listenWhen` per AC6.
- ❌ **Do NOT** map viseme strings → ints on the client. The wire format is `viseme_id: int` (per the architecture envelope spec); the int → enum-case-name mapping happens INSIDE `RiveCharacterCanvasState.setVisemeId` via the `_idToCase` const map. The server emits ints; the client consumes ints; only the Rive boundary is string-typed.
- ❌ **Do NOT** mock `RiveWidgetBuilder` or any Rive native widget in tests (`rive-flutter-rules.md` §6). Test the fallback path (`RiveNative.isInitialized == false`) only — the new public setters (`setEmotion`, `setVisemeId`) are no-ops in fallback (the cached enum fields are null), and that no-op-without-throw is exactly what the new tests assert.
- ❌ **Do NOT** invoke `_dataChannelHandler!.dispose()` (force-unwrap) in `_CallScreenState.dispose()`. Use `?.dispose()` — the handler is null until the first `CallConnected`, and a CallError-during-connect path would dispose without a handler ever being created.
- ❌ **Do NOT** forget to call `super.dispose()` AFTER `_dataChannelHandler?.dispose()` in `_CallScreenState.dispose()`. The order matters: dispose owned objects first, then call super.
- ❌ **Do NOT** introduce a hex-color literal anywhere in `lib/features/call/`. Token-enforcement test (Gotcha #6) will fail. This story doesn't need new colors — the only visible side effect is Rive state-machine changes inside the existing canvas.

### Files to change

**Server (created):**
- `server/pipeline/emotion_emitter.py` (NEW — `EmotionEmitter(FrameProcessor)`)
- `server/pipeline/viseme_emitter.py` (NEW — `VisemeEmitter(FrameProcessor)` + `word_to_viseme_id`)
- `server/tests/pipeline/test_emotion_emitter.py` (NEW)
- `server/tests/pipeline/test_viseme_emitter.py` (NEW)
- `server/tests/pipeline/test_bot_pipeline_wiring.py` (NEW or UPDATED — depending on Story 6.1's prior state)

**Server (modified):**
- `server/pipeline/bot.py` — read `SCENARIO_CHARACTER` env var; instantiate emitters; insert into pipeline.
- `server/pipeline/prompts.py` — add `EMOTION_CLASSIFIER_PROMPT` constant.
- `server/pipeline/scenarios.py` — add `load_scenario_metadata` helper.
- `server/api/routes_calls.py` — pass `SCENARIO_CHARACTER` env var to spawned bot subprocess.
- `server/tests/api/test_routes_calls.py` — assert env var on `Popen`.

**Client (created):**
- `client/lib/features/call/services/data_channel_handler.dart` (NEW)
- `client/test/features/call/services/data_channel_handler_test.dart` (NEW)

**Client (modified):**
- `client/lib/features/call/views/widgets/rive_character_canvas.dart` — promote State class to public, cache two more enums, add `setEmotion`/`setVisemeId`, add `_idToCase` const map.
- `client/lib/features/call/views/call_screen.dart` — `BlocListener` wrapper, `_canvasKey`, `_dataChannelHandler`, `dispose` cleanup.
- `client/lib/features/call/bloc/call_bloc.dart` — add `Room get room => _room;` getter.
- `client/test/features/call/views/widgets/rive_character_canvas_test.dart` — 2 new fallback tests.
- `client/test/features/call/views/call_screen_test.dart` — 2 new wiring/lifecycle tests.
- `client/test/features/call/bloc/call_bloc_test.dart` — 1 new getter-identity test.

**No changes to:**
- DB schema, migrations, `tests/fixtures/prod_snapshot.sqlite` (zero DB impact).
- `client/lib/app/router.dart` (Story 6.1's plumbing).
- `client/lib/features/call/repositories/call_repository.dart` (no API contract change).
- `client/lib/features/call/bloc/call_event.dart` / `call_state.dart` (no new events / states).
- `pubspec.yaml` (the `livekit_client` and `rive` packages are already present).
- `pyproject.toml` (no new server dependency — heuristic mapper is stdlib-only; OpenRouter is already a dep via pipecat-ai's openai extra).

### Project Structure Notes

- `server/pipeline/` already houses `bot.py`, `prompts.py`, `scenarios.py`, `transcript_logger.py`. Adding `emotion_emitter.py` + `viseme_emitter.py` alongside is consistent with the existing flat layout. No subdirectory needed at N=2 emitters; if Stories 6.4 / 6.6 add a third + fourth, consider promoting to `server/pipeline/processors/` then.
- `client/lib/features/call/services/` exists per the architecture's planned tree (architecture.md line 791-793 mentions `services/livekit_service.dart` and `services/viseme_handler.dart`). Story 6.1 inlined `Room` ownership into `CallBloc` instead of building `livekit_service.dart` (intentional simplification). For 6.3, the `data_channel_handler.dart` is the first real `services/` file. The legacy planned `viseme_handler.dart` is **not** built — its concern is split between `DataChannelHandler` (decode + dispatch) and `RiveCharacterCanvasState.setVisemeId` (apply). Document this divergence as Deviation #2 in Implementation Notes.
- Test mirror: `client/test/features/call/services/` does NOT exist today (verified at story-creation time). The dev creates it for `data_channel_handler_test.dart`.

### References

- [Epic 6 §Story 6.3](../planning-artifacts/epics.md) — original AC source (lines 1067-1094); reconciled with Rive contract per Background §1.
- [Story 6.1 Implementation](6-1-build-call-initiation-from-scenario-list-with-connection-animation.md) — `CallBloc.room` ownership, `_disconnectCancel` listener pattern, `subprocess.Popen` env-var injection, foreground service.
- [Story 6.2 Implementation](6-2-build-call-screen-with-rive-character-canvas.md) — `RiveCharacterCanvas` widget, `_characterEnum` cache, `RiveNative.isInitialized` fallback gate, `Fit.cover` full-screen render.
- [Story 2.6 Rive Character Puppet](2-6-create-rive-character-puppet-file.md) — **canonical** Rive contract: `emotion` 10-enum, `visemeId` 12-enum, `onHangUp` event, `MainStateMachine` shared across artboards.
- [Architecture: Communication Patterns / LiveKit Data Channel Messages](../planning-artifacts/architecture.md) — envelope shape (lines 606-616).
- [Architecture: Real-Time Communication During Calls](../planning-artifacts/architecture.md) — viseme channel intent (lines 320-323) — **note: line 322 says "phoneme timestamps" but Cartesia returns word timestamps; resolved per Deviation #1**.
- [Architecture: Rive 0.14.x Integration Rules](../planning-artifacts/architecture.md) — non-negotiable rules (lines 184-208).
- [UX Design Specification §Phase 3: Character Reaction System](../planning-artifacts/ux-design-specification.md) — the 7 reactive emotional states + their trigger conditions (lines 446-475).
- [UX Design Specification §Silence Handling](../planning-artifacts/ux-design-specification.md) — silence escalation stages (lines 461-475) — **NOT in 6.3 scope; owned by Story 6.4**.
- `memory/rive-flutter-rules.md` §5 (DataBind.auto, listener removal in dispose, null-safe ViewModel reads), §9 (`viewModel.enumerator(...)` returns `ViewModelInstanceEnum?`, `.value` is the case-name string).
- `client/CLAUDE.md` — Flutter gotchas (especially #1, #2, #3, #6, #7, #8, #10).
- LiveKit Flutter SDK 2.6.4 — `livekit_client/lib/src/events.dart:421-435` (`DataReceivedEvent` shape).
- pipecat 0.0.108 — `pipecat/transports/livekit/transport.py:914-931` (`send_message` JSON-encodes dict + dispatches via `_client.send_data`).
- pipecat-ai (Cartesia) — `pipecat/services/cartesia/tts.py:612-617` (the `timestamps` message handling); `pipecat/services/tts_service.py:1127-1152` (`add_word_timestamps`).

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Implementation Notes

<!-- Populated during implementation. Document at minimum:
(a) Deviation #1 — heuristic word→viseme mapper instead of g2p_en/phonemizer (per Dev Notes).
(b) Deviation #2 — `data_channel_handler.dart` replaces the architecture's planned `viseme_handler.dart` + (the missing) `livekit_service.dart` (per Project Structure Notes).
(c) Final pipecat `TTSTextFrame` field names verified at implementation time (the AC2 description says "verify the actual attribute names" — paste the result).
(d) The `EMOTION_CLASSIFIER_PROMPT` final wording (the AC1 example is a starter; tune at implementation time and paste here).
(e) Any in-flight task cancellation edge case observed under load (e.g. `asyncio.CancelledError` propagation patterns).
(f) Future Coupling Note for Story 6.6 author — whether to merge `EmotionEmitter` and `ExchangeClassifier` once both are live.
(g) Any third deviation if encountered. -->

### Debug Log References

### Completion Notes List

### File List

### Notes for Reviewer — conscious choices

<!-- Populated during implementation. -->
