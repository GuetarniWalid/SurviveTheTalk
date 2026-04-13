# Rive Character Puppet — Creation Guide

> **Story:** 2.6 — Create Rive Character Puppet File
> **Deliverable:** `client/assets/rive/character.riv`
> **Tool:** Rive Editor (rive.app)
> **Date:** 2026-04-02

This guide walks through every step of creating the character `.riv` file in the Rive editor. Follow sections in order — each builds on the previous.

---

## Table of Contents

1. [Project Setup](#1-project-setup)
2. [Artboard Configuration](#2-artboard-configuration)
3. [Character Design](#3-character-design)
4. [Hang-Up Button](#4-hang-up-button)
5. [State Machine Setup](#5-state-machine-setup)
6. [Emotional States (10 states)](#6-emotional-states)
7. [Lip Sync Visemes (12 shapes)](#7-lip-sync-visemes)
8. [Hang-Up Animation](#8-hang-up-animation)
9. [Reduced Motion Support](#9-reduced-motion-support)
10. [Input/Output Contract](#10-inputoutput-contract)
11. [Export & File Placement](#11-export--file-placement)
12. [Validation Checklist](#12-validation-checklist)

---

## 1. Project Setup

1. Open Rive editor at [rive.app](https://rive.app)
2. Create a new file named `character`
3. Use a **single artboard** — all states, visemes, and the hang-up button live on one artboard
4. Use a **single state machine** named `MainStateMachine` — Flutter references this by name

> **Why single state machine?** Flutter loads one state machine per `RiveWidgetBuilder`. Multiple state machines would require multiple widgets and complicate the architecture.

---

## 2. Artboard Configuration

| Property | Value | Reason |
|----------|-------|--------|
| **Width** | 1080px | Standard mobile width (3x density) |
| **Height** | 2400px | ~20:9 ratio — covers modern phones |
| **Background** | Transparent | Flutter handles background (scenario image + blur) |
| **Fit mode target** | `Fit.cover` | Full-screen immersive, no black bars |

### Important: Design for `Fit.cover`

`Fit.cover` scales the artboard to fill the entire screen, potentially cropping edges. This means:
- **Center the character** in the artboard — edges may be cropped on different aspect ratios
- **Keep important elements** (face, hang-up button) within the **safe zone**: ~80% center area
- **Test at multiple aspect ratios**: 16:9 (older phones), 19.5:9 (iPhone), 20:9 (Android)
- **Never use `Fit.contain`** — it causes black bars

---

## 3. Character Design

### Style Direction

| Aspect | Guideline |
|--------|-----------|
| **Style** | Minimalist 2D, exaggerated facial features, simple geometric shapes |
| **Inspiration** | Rick & Morty / South Park energy — NOT their IP. 100% original design |
| **Expressiveness** | Enormous emotional range with simple shapes. Wide eyes = shock, half-closed = contempt, open mouth = anger |
| **Tone** | Sarcastic & impatient YES. Insulting or degrading NEVER |
| **Color palette** | Vibrant character against blurred background. Stand out visually |
| **Reusability** | Single .riv file with 5 character skins (mugger, waiter, girlfriend, cop, landlord) via `character` EnumInput. New scenarios = new system prompts + character variant selection, not new .riv files |

### Character Anatomy

Design the character with these separately animatable parts:

| Part | Purpose | Animation Use |
|------|---------|---------------|
| **Eyes** (left + right) | Emotional expression primary driver | Wide open (shock), half-closed (contempt), squinting (confusion), angry (narrowed) |
| **Eyebrows** (left + right) | Emotional modifier | Raised (surprise/smirk), furrowed (anger/frustration), asymmetric (confusion) |
| **Mouth** | Lip sync + emotional expression | 12 viseme shapes + emotional overlays (smile, frown, grimace) |
| **Head** | Tilt, lean, turn | Lean forward (anger), pull back (disgust), tilt (confusion) |
| **Body/Torso** | Posture, gestures | Shrug (confusion), lean in (impatience), dramatic exit (hang-up) |
| **Arms/Hands** (optional) | Gesture emphasis | Watch-checking (impatience), phone-pulling (confusion), slamming (disgust hang-up) |

### Design Constraints

- **No text elements** — zero text on screen during calls
- **No third-party IP** — 100% original character
- **Full-screen focus** — character IS the interface, the face IS the UI
- **Simple geometry** — must animate smoothly at 60fps on mobile

---

## 3b. Character Variants

The `.riv` file must contain **5 distinct visual variants** sharing the same rig, state machine, and inputs. The `character` EnumInput selects which variant is displayed.

### Variant Definitions

| Enum Value | Character | Visual Direction |
|------------|-----------|-----------------|
| `mugger` | The Mugger | Male, menacing. Dark/street clothing, hood or cap. Intimidating build, sharp features |
| `waiter` | The Sarcastic Waiter | Design TBD. Could be male or female. Uniform/apron, tired expression as baseline |
| `girlfriend` | The Furious Girlfriend | Female, expressive. Casual clothing, hair visible. Emotionally animated baseline |
| `cop` | The Cop | Design TBD. Could be male or female. Uniform elements (badge, hat), authoritative posture |
| `landlord` | The Angry Landlord | Male, older. Everyday clothing, slightly disheveled. "I'm done with your excuses" energy |

### Implementation Approach

**Recommended: Rive Swap Components**

1. Create a **base rig** with the shared skeleton (head, body, arms, mouth shapes)
2. For each variant, create **swap components** for: head shape, hair, facial features, clothing, skin tone, body proportions
3. Use the `character` EnumInput to drive a state machine layer that activates the correct set of components
4. The emotion layer and viseme layer operate independently on top of the active character variant

**Key constraint:** All 5 variants MUST support the same 10 emotional states and 12 visemes. The mouth rig and eye rig are shared — only the surrounding visual elements change.

### File Size Consideration

5 variants will increase file size. Keep under 2MB by:
- Reusing vector shapes across variants where possible (shared eyes, shared mouth shapes)
- Keeping variant differences focused on silhouette, hair, and clothing (not completely different characters)
- Using Rive's component instancing to avoid duplication

---

## 4. Hang-Up Button

The hang-up button lives **inside the Rive canvas**, not as a Flutter widget.

### Specs

| Property | Value |
|----------|-------|
| **Shape** | Circle |
| **Size** | 64x64px |
| **Fill color** | `#E74C3C` (red) |
| **Icon** | Phone-down (receiver facing down), 28x28px |
| **Icon color** | `#FFFFFF` (white) |
| **Position** | Centered horizontally, 50px from artboard bottom edge |

### Rive Event Setup

1. Select the hang-up button group
2. Add a **Listener** (click/tap) on the button
3. Configure the listener to **fire a Rive Event** named `onHangUp`
4. This event will be captured by Flutter via `addEventListener` — it's one-way (Rive→Flutter)

> **Do NOT** try to make Flutter trigger the button visually. Flutter listens for the event, that's all. The button tap is handled entirely within Rive.

---

## 5. State Machine Setup

Create a **single state machine** named `MainStateMachine` with these inputs:

### Inputs to Create

| Input Name | Type | Range/Values | Purpose |
|------------|------|--------------|---------|
| `character` | `EnumInput` | 5 values: mugger, waiter, girlfriend, cop, landlord | Select character visual variant — each scenario maps to one variant |
| `emotion` | `EnumInput` | 10 values (see Emotional States) | Select emotional state — enum dropdown in Rive editor |
| `visemeId` | `EnumInput` | 12 values (see Lip Sync Visemes) | Select mouth shape for lip sync — enum dropdown in Rive editor |
| ~~`reduced_motion`~~ | ~~`BooleanInput`~~ | ~~true/false~~ | ~~Disable fluid transitions~~ — **DEFERRED: not needed for MVP. Can be added later without breaking changes.** |
| ~~`hangUp`~~ | ~~`TriggerInput`~~ | ~~(fire once)~~ | ~~Initiate programmatic hang-up animation~~ — **REMOVED: redundant with `emotion = disgust_hangup`. Flutter uses emotion enum directly.** |

### Events to Create

| Event Name | Direction | Trigger |
|------------|-----------|---------|
| `onHangUp` | Rive→Flutter | User taps hang-up button |
| `onHangUpAnimComplete` | Rive→Flutter | Hang-up exit animation finishes playing |

### Naming Rules (Critical)

- Names are **case-sensitive** — Flutter will reference these exact strings
- Use **camelCase** for multi-word inputs: `visemeId`, `reduced_motion`, `hangUp`
- Use **camelCase** for events: `onHangUp`, `onHangUpAnimComplete`
- A typo in any name = Flutter gets `null` silently (no error, just broken functionality)

---

## 6. Emotional States

### State Machine Structure

Use the `emotion` EnumInput to drive a **blend state** or **state transitions**. The enum values in Rive editor are:

| Value | State Name | Visual Description | Animation |
|-------|-----------|-------------------|-----------|
| **0** | `satisfaction` | Neutral-to-satisfied expression | Subtle nod, relaxed eyebrows, slight smile |
| **1** | `smirk` | Brief eyebrow raise, slight smirk | One eyebrow up, asymmetric mouth curl |
| **2** | `frustration` | Eye-roll, exaggerated sigh | Eyes roll up, shoulders drop, exhale |
| **3** | `impatience` | Impatient tapping, looking away | Checking watch, tapping, gaze drift |
| **4** | `anger` | Angry expression, leans toward screen | Narrowed eyes, furrowed brows, lean forward |
| **5** | `confusion` | Confused squint, pulls phone away | Head tilt, squinted eyes, phone pullback gesture |
| **6** | `sadness` | Disappointed, deflated expression | Downcast eyes, slight frown, shoulders sag |
| **7** | `boredom` | Unimpressed, indifferent expression | Half-lidded eyes, flat mouth, gaze drifting sideways, "I couldn't care less" energy |
| **8** | `impressed` | Grudging respect, "ok fine, not bad" | Eyebrow raised, reluctant nod, slight smirk — surprised despite himself |
| **9** | `disgust_hangup` | Disgusted expression → triggers hang-up | Grimace, recoil, then exit animation plays |

### Transition Behavior

- Transitions between states should use **smooth interpolation** (200-500ms)
- Each state has an idle loop animation (subtle breathing, blinking, minor movement)
- Transitioning to a new state blends out the current idle and blends in the new one

### Implementation Approach in Rive

**Recommended: Blend State Tree**

1. Create a **Blend State 1D** driven by the `emotion` enum input
2. Each enum value corresponds to a timeline with the emotional pose
3. The blend state handles smooth interpolation automatically

**Alternative: State Machine States with Transitions**

1. Create 7 named states in the state machine
2. Add transitions between ALL states (bidirectional = 42 transitions)
3. Each transition conditioned on `emotion` enum matching target state

> The Blend State approach is simpler and more maintainable (7 positions vs 42 transitions).

---

## 7. Lip Sync Visemes

### 12 Viseme Mouth Shapes (Rest + Preston Blair Set)

Create 12 distinct mouth shapes driven by the `visemeId` EnumInput:

| Enum Value | Name | Mouth Shape | Phonemes |
|------------|------|-------------|----------|
| `rest` | Rest | Mouth closed, neutral lips — default when not speaking | (silence, pauses) |
| `aei` | Open | Wide open mouth, jaw dropped, teeth visible | a, e, i |
| `cdgknstxyz` | Dental | Slightly open, teeth showing | c, d, g, k, n, s, t, x, y, z |
| `o` | Oh | Small rounded opening | o |
| `ee` | Ee | Wide stretched smile, teeth visible | ee |
| `chjsh` | Post-alveolar | Slightly open, teeth close together | ch, j, sh |
| `bmp` | Closed | Lips pressed together | b, m, p |
| `qwoo` | Oo | Rounded/pursed lips, small circle | q, w, oo |
| `r` | R | Slightly open, relaxed | r |
| `l` | L | Mouth open, tongue visible | l |
| `th` | Th | Tongue between teeth | th |
| `fv` | FV | Lower lip tucked under upper teeth | f, v |

> **`rest` is the default value** — the mouth shape shown when the character is not speaking. Flutter sets `visemeId = 'rest'` during silence/pauses.

### Implementation in Rive

**Recommended: Enum-driven state switching**

1. Create a separate **layer** in the state machine for lip sync (independent of emotions)
2. Use the `visemeId` EnumInput to drive state transitions between 12 mouth shape states
3. Each enum value triggers a timeline showing the corresponding mouth shape
4. Transitions between shapes should be near-instant for real-time speech

### Performance Requirements

| Metric | Target | Hard Floor |
|--------|--------|------------|
| Viseme transition speed | <16ms | <33ms |
| Target frame rate | 60fps | 30fps minimum |

- Viseme changes happen **very rapidly** during speech (every ~50-100ms)
- The Rive blend must be fast enough to keep up with real-time audio
- Keep mouth shape timelines **simple** — fewer keyframes = faster blending
- Test by rapidly cycling through viseme IDs in Rive preview

### Layer Independence

The lip sync layer must be **independent** from the emotion layer:
- Mouth shapes from visemes override the emotion's mouth pose during speech
- When speech stops, the emotion's mouth expression shows through
- This requires careful layer ordering: viseme layer ON TOP of emotion layer

---

## 8. Hang-Up & Call End Behavior

### How Calls End (3 scenarios)

| Scenario | Who ends | What happens in Rive | What Flutter does |
|----------|----------|---------------------|-------------------|
| **User taps hang-up button** | User | `onHangUp` event fires → nothing else | Flutter cuts immediately to "Call Ended" screen (like FaceTime) |
| **Character patience = 0** | Character | `emotion` set to `disgust_hangup` → grimace expression (~500ms) → `onHangUpAnimComplete` fires | Flutter waits for event, then cuts to "Call Ended" |
| **Natural end (user did well)** | Character | `emotion` set to `impressed` → reluctant nod (~500ms) → `onHangUpAnimComplete` fires | Flutter cuts to "Call Ended" |

### disgust_hangup Animation (emotion index 9)

The only exit animation needed. Facial expression only (no body movement):

1. **Grimace expression** (~500ms): sourcils froncés, bouche en grimace, yeux plissés — "I'm done with you"
2. **Fire `onHangUpAnimComplete`** at end of timeline — Flutter cuts the screen immediately after (coupure sèche, like FaceTime)

### Events Summary

- **`onHangUp`** — user tapped the red button → Flutter handles everything, Rive does nothing more
- **`onHangUpAnimComplete`** — character's disgust or impressed expression is done → Flutter cuts to next screen

---

## 9. Reduced Motion Support

> **DEFERRED FOR MVP** — This input is NOT created in the current `.riv` file. Full animations only for now. Reduced motion support can be added in a future iteration by adding a `reduced_motion` BooleanInput that sets all transition durations to 0. No breaking changes needed — it's purely additive.

---

## 10. Input/Output Contract

### Complete Reference Table

| Direction | Mechanism | Name | Type | Values | Purpose |
|-----------|-----------|------|------|--------|---------|
| Flutter→Rive | ViewModel property | `character` | EnumInput | 5 enum values: mugger, waiter, girlfriend, cop, landlord | Select character visual variant |
| Flutter→Rive | ViewModel property | `emotion` | EnumInput | 10 enum values | Set emotional state |
| Flutter→Rive | ViewModel property | `visemeId` | EnumInput | 12 enum values | Set mouth shape |
| ~~Flutter→Rive~~ | ~~ViewModel property~~ | ~~`reduced_motion`~~ | ~~BooleanInput~~ | ~~true/false~~ | ~~Toggle animation fluidity~~ — **DEFERRED (post-MVP)** |
| ~~Flutter→Rive~~ | ~~ViewModel property~~ | ~~`hangUp`~~ | ~~TriggerInput~~ | ~~(fire)~~ | ~~Start exit animation~~ — **REMOVED (redundant)** |
| Rive→Flutter | Event listener | `onHangUp` | Event | — | User tapped hang-up button |
| Rive→Flutter | Event listener | `onHangUpAnimComplete` | Event | — | Exit animation finished |

### How Flutter Will Access These

```
// Flutter code (Epic 6 — NOT part of this story, just context)
final character = viewModel.enum_('character');     // EnumInput? (string-based)
final emotion = viewModel.enum_('emotion');         // EnumInput? (index-based)
final viseme = viewModel.enum_('visemeId');         // EnumInput? (string-based)
// final reduced = viewModel.boolean('reduced_motion'); // DEFERRED (post-MVP)
// Setting values:
character?.value = 'girlfriend';  // Set character variant for this scenario
emotion?.value = 3;               // Set to impatience (enum index 3)
viseme?.value = 'rest';           // Set to mouth closed (silence/pause)
viseme?.value = 'ee';             // Set to wide vowel mouth shape (enum string)
// reduced?.value = true;         // DEFERRED (post-MVP)

// Listening for events:
viewModel.addEventListener((event) {
  if (event.name == 'onHangUp') { /* user tapped button */ }
  if (event.name == 'onHangUpAnimComplete') { /* animation done */ }
});
```

> All these references return `null` if the name doesn't match. **Exact spelling matters.**

---

## 11. Export & File Placement

### Export Steps

1. In Rive editor: File → Export → `.riv` format
2. Name the exported file `character.riv`
3. Place at: `client/assets/rive/character.riv`

> **Source file:** The editable project lives in your Rive cloud account — no need to export a local copy.

### File Structure

```
client/assets/rive/
└── character.riv          ← Exported binary (committed to git)
```

### File Size Target

| Metric | Target | Notes |
|--------|--------|-------|
| `.riv` file size | <2MB | Will be served via hot-update in production |
| Recommended | <1MB | Faster downloads, less memory on device |

Keep file size down by:
- Using simple vector shapes (no raster images)
- Minimizing keyframe count where possible
- Avoiding duplicate shapes — reuse components

---

## 12. Validation Checklist

Run through this checklist before marking the story complete:

### Artboard & Setup
- [x] Single artboard, transparent background
- [x] Single state machine named `MainStateMachine`
- [x] Designed for `Fit.cover` (important content in center safe zone)

### Inputs (5 total)
- [x] `character` — EnumInput with 5 values: mugger, waiter, girlfriend, cop, landlord
- [x] `emotion` — EnumInput with 10 values: satisfaction, smirk, frustration, impatience, anger, confusion, sadness, boredom, impressed, disgust_hangup
- [x] `visemeId` — EnumInput with 12 values: rest, aei, cdgknstxyz, o, ee, chjsh, bmp, qwoo, r, l, th, fv
- [ ] ~~`reduced_motion` — BooleanInput, toggles animation fluidity~~ **DEFERRED (post-MVP)**
- [ ] ~~`hangUp` — TriggerInput, initiates exit animation~~ **REMOVED (redundant with emotion = disgust_hangup)**

### Events (2 total)
- [x] `onHangUp` — fires when hang-up button is tapped
- [X] `onHangUpAnimComplete` — fires when exit animation completes

### Emotional States (10 total)
- [x] 0: satisfaction — subtle nod, neutral-to-satisfied
- [x] 1: smirk — eyebrow raise, slight smirk
- [x] 2: frustration — eye-roll, exaggerated sigh
- [x] 3: impatience — tapping, looking away
- [x] 4: anger — narrowed eyes, lean forward
- [x] 5: confusion — squint, phone pullback
- [x] 6: sadness — downcast eyes, slight frown, shoulders sag
- [x] 7: boredom — half-lidded eyes, flat mouth, gaze drifting
- [x] 8: impressed — reluctant nod, eyebrow raised, "ok fine, not bad"
- [x] 9: disgust_hangup — grimace → exit animation

### Lip Sync Visemes (12 total — Rest + Preston Blair)
- [x] `rest` — mouth closed, neutral (silence/pauses) — **default value**
- [x] `aei` — wide open mouth (a, e, i)
- [x] `cdgknstxyz` — slightly open, teeth showing (dental consonants)
- [x] `o` — small rounded opening
- [x] `ee` — wide stretched smile
- [x] `chjsh` — slightly open, teeth close (post-alveolar)
- [x] `bmp` — lips pressed together (bilabial)
- [x] `qwoo` — rounded/pursed lips
- [x] `r` — slightly open, relaxed
- [x] `l` — mouth open, tongue visible
- [x] `th` — tongue between teeth
- [x] `fv` — lower lip under upper teeth

### Hang-Up Button
- [x] 64x64px circle, fill `#E74C3C`
- [x] Phone-down icon 28px, `#FOFOFO`
- [x] Centered horizontally, 50px from bottom
- [x] Click fires `onHangUp` event

### Animations
- [x] Smooth transitions between emotional states (200-500ms)
- [x] Disgust hang-up expression (~500ms grimace, facial only)
- [x] `onHangUpAnimComplete` fires after disgust expression completes
- [x] Viseme transitions fast enough for real-time lip sync (<16ms target)

### Reduced Motion — DEFERRED (post-MVP)
- [ ] ~~`reduced_motion` input~~ — skipped for MVP, additive later

### Export
- [x] `.riv` exported to `client/assets/rive/character.riv`
- [x] File size <2MB

### Character Design
- [x] 100% original design (no third-party IP)
- [x] "Adult animation energy" style with exaggerated expressions
- [x] Sarcastic/impatient personality, NOT insulting/degrading
- [x] No text elements in the Rive canvas
- [X] Works at multiple aspect ratios (16:9 to 20:9)

### Character Variants (5 total)
- [x] `mugger` — male, menacing, visually distinct
- [x] `waiter` — design TBD, visually distinct
- [x] `girlfriend` — female, expressive, visually distinct
- [x] `cop` — design TBD, visually distinct
- [x] `landlord` — male, older, visually distinct
- [x] All 5 variants support all 10 emotional states
- [x] All 5 variants support all 12 visemes
- [x] Variants share: rig, state machine, hang-up button, inputs, events
- [x] Variants differ: head shape, hair, body, clothing, skin tone
- [x] `character` EnumInput switches cleanly between all 5 variants

---

## Quick Reference Card

Copy this to your desk while working in Rive:

```
STATE MACHINE: MainStateMachine

INPUTS:
  character      (Enum)     mugger | waiter | girlfriend | cop | landlord
  emotion        (Enum)     satisfaction | smirk | frustration | impatience
                            anger | confusion | sadness | boredom
                            impressed | disgust_hangup
  visemeId       (Enum)     rest | aei | cdgknstxyz | o | ee | chjsh
                            bmp | qwoo | r | l | th | fv
  hangUp        (Trigger)  REMOVED — redundant

EVENTS:
  onHangUp              → user tapped button
  onHangUpAnimComplete  → exit animation done

BUTTON: 64x64 #E74C3C, icon 28px #FFFFFF, bottom 50px center

FILE: client/assets/rive/character.riv
```
