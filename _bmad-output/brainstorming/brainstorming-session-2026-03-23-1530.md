---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'SurviveTheTalk - App amélioration anglais parlé via appels simulés avec personnages animés style Rick & Morty, IA non-bienveillante'
session_goals: 'Définir MVP minimal mais attractif, valider viabilité du concept, feedback franc'
selected_approach: 'ai-recommended'
techniques_used: ['Question Storming', 'Reverse Brainstorming', 'Resource Constraints']
ideas_generated: 31 questions + 14 success factors + MVP definition
session_active: false
workflow_completed: true
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** walid
**Date:** 2026-03-23

## Session Overview

**Topic:** SurviveTheTalk - Application d'amélioration de l'anglais parlé pour niveaux intermédiaires/avancés via des appels simulés avec des personnages animés style Rick & Morty. L'IA n'est PAS bienveillante et réagit comme un vrai interlocuteur.

**Goals:** Définir le MVP le plus léger mais attractif, valider l'intérêt réel du concept, identifier les features essentielles vs superflues, retour franc sur la viabilité.

### Session Setup

- **Niveau cible :** Intermédiaire/avancé (pas débutants)
- **Pain point :** Fossé entre anglais scolaire et anglais réel, coût élevé de la pratique, peur de l'humain
- **Différenciateur :** IA non-bienveillante, format "appel entrant à survivre", style graphique Rick & Morty
- **Approche sélectionnée :** Techniques recommandées par l'IA

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** SurviveTheTalk MVP validation with focus on honest viability assessment

**Recommended Techniques:**

- **Question Storming:** Identify all critical unknowns and assumptions before building
- **Reverse Brainstorming:** Deliberately find ways to make the app fail to reveal hidden risks and success factors
- **Resource Constraints:** Force MVP prioritization through extreme limitation scenarios

**AI Rationale:** User explicitly requested franchise over reassurance. This sequence is designed to stress-test the concept before any code is written, identify fatal flaws early, and distill the minimum viable feature set.

## Technique Execution Results

### Phase 1: Question Storming (31 Critical Questions)

**Focus:** Identify all unknowns and assumptions before building

#### Market & Pain Point Validation
1. Is the problem SurviveTheTalk solves one people already PAY for?
2. Do iTalki users complain their tutors are too nice? Or is kindness what they seek?
3. Does the fear of speaking to a human transfer to an AI character that judges you?
4. Is "getting hung up on" motivating or discouraging for someone already lacking confidence?

#### Technical Feasibility
5. Can an LLM maintain a consistent CHARACTER (personality, emotional reactions) throughout a call?
6. How do we define the boundary between "edgy/trash" and "offensive"? Who decides?
7. Would Apple/Google accept an app where a character can berate the user, even educationally?
8. Is the Rick & Morty tone scriptable by prompt, or will it sound fake and cringe?
9. Does current STT (Whisper, Deepgram) distinguish bad pronunciation from unknown words? Or auto-correct what's said poorly?
10. If the user says "I sink" instead of "I think", does the AI hear "sink" and react, or silently correct to "think"?
11. What's the realistic delay between "user speaks" and "character responds"? If 3 seconds, does it kill the illusion?
12. Is the latency STT + LLM + TTS compatible with fluid conversation?

#### Core Concept Viability
13. If speech recognition can't detect pronunciation errors... does the app concept even hold?
14. Do we need to recognize PRONUNCIATION, or is discourse COHERENCE enough for MVP?
15. Is the real differentiator pronunciation detection... or the stressful emotional context that forces better speech?
16. After 10 scenarios "angry girlfriend / cop / mugger", does the pattern become predictable?
17. What renews the experience? New characters? Situations? Generated content? Who produces it?
18. Does the "single call" format have a shorter lifespan than a "continuing story" format?
19. What's SurviveTheTalk's retention mechanism? Fear of losing? Fun? Progression?
20. Do people RETURN to an app that stresses them, or do they launch it 3 times and uninstall?

#### Feedback & Learning Value
21. If the character hangs up but never says why... how does the user actually progress?
22. Is the app a DIAGNOSTIC tool (show weaknesses) or a TRAINING tool (make you improve)? Different apps.
23. If we add post-call feedback, does it break the immersion and the "not nice" concept?
24. Or is post-call feedback actually the REAL value, and the stressful call is just the hook?
25. Without clear feedback, how is SurviveTheTalk better than just talking to ChatGPT Voice and asking it to be mean?

#### Business & Costs
26. A 5-min call = how many LLM tokens + how many seconds STT + TTS? Cost PER CALL?
27. If a user does 3 calls/day, what's the monthly cost PER user?
28. At what subscription price would people pay? 5€/month? 10? 20? Does it cover infra?
29. Do API costs dropping every 6 months make the app non-viable TODAY but viable in 12 months?
30. Does a "limited calls per day" model (mobile game energy system) solve cost AND create scarcity?

#### Existential Question
31. **Is SurviveTheTalk a GAME that teaches English, or an English TOOL that's gamified?** The answer changes everything: pricing, marketing, retention, competitors, and user expectations.

### Phase 2: Reverse Brainstorming (14 Success Factors)

**Focus:** "How to guarantee SurviveTheTalk fails?" → Invert each sabotage into a success factor

| # | Sabotage (App Dies If...) | Success Factor |
|---|---|---|
| 1 | First call too hard, user humiliated | Calibrated onboarding, first call = near-guaranteed victory |
| 2 | No actionable feedback, confidence lost | Post-call debrief = core of the app |
| 3 | Free content = complete tour, nothing left to pay for | Paywall at the right moment, paid content visibly superior |
| 4 | Latency / tech lag | Conversational fluidity = absolute deal-breaker |
| 5 | Scene on rails, user choices ignored | Reactions specific to what user actually says |
| 6 | No virality, experience dies in the phone | Shareable replays (TikTok/Reels) |
| 7 | Marketed as serious educational tool | Positioned as game/experience, education smuggled in |
| 8 | Boring, slow rhythm | Short calls (2-5 min), user active at all times |
| 9 | Buggy, unfinished | 3 perfect scenarios > 50 broken scenarios |
| 10 | "Disguised ChatGPT" - pay $20 for ChatGPT instead | Features impossible to reproduce with a prompt |
| 11 | Incomprehensible characters | Optional subtitles + difficulty levels |
| 12 | No reason to return tomorrow | Retention hook (notifications, narrative arcs, daily challenge) |
| 13 | No proof of progression | Visible progression dashboard (survival time, success rate) |
| 14a | Abusive characters → Store rejection | Sarcastic/impatient YES, insulting NEVER |
| 14b | Rick & Morty IP copy → lawsuit | Inspired style but 100% original character design |
| 14c | Education category + trash content | Entertainment/Games category, rating 12+/17+ |

### Phase 3: Resource Constraints (MVP Definition)

**Focus:** Extreme constraints to force essential priorities

#### Core Product Decision
> "If you could ship ONE feature, what is it?"
> **Answer: The animated voice call. Everything else flows from it.**

#### MVP Feature Set

**In the MVP:**

- FaceTime-format animated voice call with Rive character
- Rive character with 5-6 emotional states + simplified lip sync (NOT static avatar)
- Single Rive "puppet" file reused across all scenarios, piloted by AI in real-time
- Discourse coherence as main criterion (not pronunciation for MVP)
- Score % shown only on failure ("You made it 70% of the way")
- Optional subtitles + difficulty levels
- Post-call debrief with actionable feedback
- Shareable replay clips (30 sec highlights)

**NOT in the MVP:**

- Pronunciation detection
- Full facial motion capture
- Progression dashboard (beyond simple score)
- Daily challenges / notification hooks
- Narrative arcs between scenarios

## Technical Architecture

**Pipeline:**
```
Script (key points + context)
    → LLM generates dialogue + emotions (GPT-4o-mini / DeepSeek)
        → TTS premium generates voice (ElevenLabs)
            → Lip sync API (Microsoft Azure Viseme)
                → Rive state machine drives single puppet face
```

| Component | Choice | Rationale |
|---|---|---|
| Animation | Rive (1 unique puppet file, emotional states) | Scalable, lightweight, reusable across all scenarios |
| LLM | GPT-4o-mini or DeepSeek | Low cost, scripted scenarios = fewer tokens |
| TTS | Premium (ElevenLabs or equivalent) | Voice IS the experience, non-negotiable |
| STT | Whisper local | Near-zero cost, sufficient quality |
| Lip sync | Microsoft Azure Viseme API | Drives Rive puppet in real-time |

**Key insight:** New scenarios = just new scripts (text), not new dev. The Rive puppet + pipeline are built once. This makes 2 scenarios/week production sustainable long-term.

## Business Model

| Element | Decision |
|---|---|
| Free tier | 3 scenarios (including mugger viral hook) |
| Paid tier | Weekly subscription ~1.99€/week |
| Content at launch | 5 scenarios (3 free + 2 paid) |
| Subscriber limit | 3 new scenarios unlocked/week |
| Production cadence | 2 scenarios/week post-launch |
| 2-month LTV | ~16€ revenue, 12 total scenarios to produce |
| Evolution | Monthly (6.99€) when catalog justifies it |

**Cost control:** Character hangs up on rambling/off-topic = natural call duration limit = controlled API costs per call.

## Breakthrough Concept

**Post-call feedback is potentially the real product.** The stressful call is the emotional hook, but the value that makes people PAY is knowing exactly what to improve. This is what differentiates SurviveTheTalk from "talking to ChatGPT Voice in mean mode."

## Critical Unresolved Questions (Validate Before/During Dev)

1. **Latency:** Is STT + LLM + TTS pipeline compatible with fluid conversation? → Technical prototype FIRST
2. **Compliance:** Does the mugger scenario pass Apple review? → Submit test scenario early
3. **Retention:** Do people return to an app that stresses them? → Measure D1/D7/D30 retention from launch
4. **Unit economics:** Is cost per call viable at scale? → Calculate precisely with chosen APIs

## MVP Action Plan (8 Weeks)

### Week 1-2: Technical Proof of Concept
1. Test the complete pipeline: prompt → LLM → TTS → lip sync → Rive on ONE single exchange (not a full scenario, just the technical loop)
2. Measure latency. If > 2 seconds, entire concept is at risk. Solve this before everything else.

### Week 3-4: First Playable Scenario
3. Create the Rive puppet file with 5-6 emotional states
4. Write and calibrate the mugger scenario (viral hook)
5. Implement win/lose system + score % on failure

### Week 5-6: Content + Monetization
6. Write 4 remaining scenarios (2 free + 2 paid)
7. Integrate weekly subscription via App Store / Play Store
8. Build basic post-call debrief

### Week 7-8: Polish + Launch
9. Shareable replays (short format for TikTok)
10. Optional subtitles
11. Beta test with 20-30 people, iterate on difficulty calibration
12. Launch

## Final Verdict

**The idea is good.** The pain point is real. The "stressful game" positioning is differentiating. **BUT everything hinges on the technical fluidity of the call.** If latency is acceptable, this holds together. If it isn't, the concept doesn't survive. Start there.

## Session Metadata

**Techniques used:** Question Storming, Reverse Brainstorming, Resource Constraints
**Session duration:** ~55 minutes
**Creative approach:** AI-Recommended Techniques with frank, no-reassurance facilitation
**Key facilitation insight:** User demonstrates strong product instinct - pushed back correctly on static avatar (Rive animation is feasible and essential), thought proactively about LTV and content pipeline sustainability, and naturally connected cost optimization to game mechanics (character hanging up = cost control).
