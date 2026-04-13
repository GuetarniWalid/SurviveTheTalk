---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-02b-vision
  - step-02c-executive-summary
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
  - step-12-complete
inputDocuments:
  - product-brief-surviveTheTalk2-2026-03-25.md
  - market-survivethetalk-research-2026-03-23.md
  - domain-appstore-virality-research-2026-03-24.md
  - technical-conversational-ai-pipeline-research-2026-03-24.md
  - brainstorming-session-2026-03-23-1530.md
documentCounts:
  briefs: 1
  research: 3
  brainstorming: 1
  projectDocs: 0
workflowType: 'prd'
classification:
  projectType: mobile_app
  domain: edtech
  complexity: medium
  projectContext: greenfield
---

# Product Requirements Document - surviveTheTalk2

**Author:** walid
**Date:** 2026-03-25

## Executive Summary

SurviveTheTalk is a mobile app (iOS + Android, Flutter) that crash-tests intermediate English learners through high-stakes animated phone calls with adversarial 2D characters. Users receive incoming calls from sarcastic, impatient characters — a mugger demanding their wallet, a furious girlfriend threatening to leave, a suspicious cop — and must talk their way out in English. Characters react in real-time (grimacing, eye-rolling, hanging up) via Rive animation driven by a conversational AI pipeline (Soniox STT + Qwen3.5 Flash LLM + Cartesia Sonic 3 TTS, sub-800ms perceived latency). The app is positioned as adversarial entertainment — a game you survive, not a tool you study with — targeting the massive gap between "I understand podcasts" and "I can't hold a real conversation."

The call is the test. The post-call debrief is the real value: a brutally honest breakdown of what went wrong, what was said well, and exactly what to improve. No praise without merit. This feedback loop — fail, understand why, retry, validate progress — is what users pay for and what no competitor delivers.

SurviveTheTalk enters a $7.36B language learning app market (16% CAGR) where the AI speaking sub-segment alone generates $165M+/year across the top 5 players. It targets the intermediate plateau — 29% of app-based learners stall here with zero dedicated solution. Zero competitors occupy the "adversarial entertainment + English practice" positioning. Built by a solo developer leveraging Rive animation, vibe coding, and API-based AI infrastructure, the product requires ~60 subscribers to break even and reaches ~$3,000/month net profit at 500 subscribers — with 78-82% margins on a ~$2/week subscription.

### What Makes This Special

**Adversarial entertainment positioning.** Every competitor is supportive, kind, and patient. SurviveTheTalk is sarcastic, impatient, and reactive — like a real person who doesn't care that you're learning. The tone is trash, décalé, inspired by adult animation energy (Rick & Morty vibe, not IP — 100% original character designs). This isn't incremental differentiation; it's a different product category. The closest analog is mobile gaming, not language learning.

**The test-then-truth loop.** The stressful call creates emotional engagement and validates the user's real level under pressure. The debrief delivers the honest, actionable feedback that justifies payment — specific errors flagged, correct alternatives provided, pattern tracking across sessions. Together, they form an experience impossible to replicate with "ChatGPT in mean mode."

**Built-in virality.** Every call is a potential shareable moment. "I tried to survive a mugging in English and got hung up on" is content people want to share. Organic UGC screen recordings replace paid acquisition as the primary growth engine, yielding LTV:CAC ratios of 15-46x with organic channels.

**Solo developer viability.** Three converging enablers — sub-800ms conversational AI APIs, Rive real-time 2D animation, and vibe coding — allow a single developer to build and ship a product that would have required a funded team 2 years ago. This dramatically lowers the revenue threshold for profitability: break-even at 60 subscribers, no employees, no investors, no office.

## Project Classification

- **Project Type:** Mobile App (cross-platform Flutter, iOS + Android)
- **Domain:** EdTech (language learning) — positioned as Entertainment/Gaming
- **Complexity:** Medium — App Store compliance, AI content moderation, COPPA considerations, EU AI Act Article 50 transparency obligations (deadline August 2026), BIPA voice data considerations
- **Project Context:** Greenfield — new product from scratch

## Success Criteria

### User Success

**North Star User Outcome: Validated Confidence.** SurviveTheTalk is a mirror — it reflects the user's real English level back at them under pressure. Success means the user thinks: "If I can survive this virtual crash test, I can handle it for real."

**Primary indicator:** Retry rate after failure. If users retry failed scenarios, the stress mechanic motivates rather than discourages — this is the existential validation for the entire product concept.

| Metric | Target | Why It Matters |
|--------|--------|----------------|
| Retry rate on failed scenarios | >50% within 48h | Confirms failure is motivating, not discouraging — the #1 existential question |
| Scenario progression rate | Further on retry than previous attempt | Proves the test→debrief→retry loop works |
| Post-call debrief engagement | >70% read full debrief | Validates that honest feedback is the real value, not skipped |
| Daily return rate | Returns next day for retry or new scenario | Shows compelling "one more try" loop |
| Share rate | >5% of completed calls shared | Indicates the experience is entertainment-worthy |

### Business Success

**North Star: Revenue growth trend.** Revenue reflects everything — user count, retention, perceived value, willingness to pay. The question is: are revenues growing week over week?

| Timeframe | Objective | Target |
|-----------|-----------|--------|
| Month 1-3 | Validate product-market fit | Revenue trending upward WoW. Minimum 60 paying subscribers (~$500/month net) |
| Month 6 | Sustainable solo operation | 250+ paying subscribers. ~$2,000/month net after API costs and App Store commission |
| Month 12 | Proven business | 500+ paying subscribers. ~$3,000-4,000/month net. Content flywheel producing 2 scenarios/week |

### Technical Success

| Metric | Target | Rationale |
|--------|--------|-----------|
| Perceived response latency | <800ms (sub-2s hard ceiling) | Below 800ms feels like natural conversation. Above 2s, the illusion breaks — concept is dead |
| API cost per 5-min call | $0.044-0.054 | Soniox + Qwen3.5 Flash + Cartesia Sonic 3 stack. Must stay under $0.08 for margin safety |
| Subscriber margin (normal user) | 78-82% | At $7.36/month net revenue, ~$1.50/month API cost |
| App Store approval | First submission accepted | With 8 content modifications from domain research. Lighter scenarios first, mugging in post-launch update |
| Rive lip sync | Functional phoneme-to-viseme mapping | 8 grouped mouth shapes driven by Cartesia phoneme timestamps via LiveKit data channel |

### Measurable Outcomes

**Go/No-Go Gates (kill thresholds backed by industry data):**

| Gate | Metric | Kill Threshold | Data Basis |
|------|--------|---------------|------------|
| Technical validation | STT→LLM→TTS latency | >2s in prototype → concept is dead | Human perception: >1.5s rapidly degrades experience |
| Product-market fit | D7 retention in first 100 users | <5% → pivot or kill | Industry D7 benchmarks: education 17.8%, gaming 18.1%, iOS floor 6.9%. Below 5% = 3-4x worse than any category average |
| Monetization validation | Free-to-paid conversion | <2% → rework paywall or debrief quality | Industry median hard paywall: 12.1%. Below 2% = fundamental value proposition failure |
| Revenue trajectory | Week-over-week revenue growth | Flat or declining after 8 weeks → reassess | Sustained growth indicates organic traction |
| Viral validation | K-factor with organic UGC | <0.1 → experience not compelling enough to share | Median K-factor for apps with sharing: 0.45. Target: 0.3-0.5 |

**Engagement KPIs:**

| KPI | Target | Measurement |
|-----|--------|-------------|
| DAU/MAU ratio | >20% | Habit formation indicator |
| Calls per user per day | 1-2 average | Core engagement. Too low = boring, too high = unsustainable costs |
| D1 retention | >40% | Industry gaming benchmark: 32%. Education: 27.5%. Target beats both. |
| D7 retention | >15% | Industry education: 17.8%. Gaming: 18.1%. Target is achievable floor. |
| D30 retention | >5% | Industry education: 8%. Gaming: 7.7%. Beating 5% validates entertainment positioning. |
| Free-to-paid conversion | >8% | Industry median: 2-12%. Low weekly price ($2/week) drives higher conversion (47.8% at low prices). |
| Monthly churn | <15% | Duolingo monthly churn: 16%. Target is to match or beat the incumbent. |

## Product Scope & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Experience MVP — validating that the emotional loop (stress → failure → honest feedback → retry) is compelling enough to retain users and justify payment. If the adversarial call doesn't create emotional engagement, no amount of features saves the product.

**Resource:** Solo developer (Walid). No team, no funding. Every feature added is a direct trade-off against launch date. Break-even at 60 subscribers.

### Phase 0 — Proof of Concept (Pre-MVP)

**Goal:** Validate the core technical hypothesis before any product investment. If the conversational AI pipeline can't deliver a fluid, personality-driven voice conversation, the entire concept is dead — no point building anything else.

**Scope:**
- Bare-minimum Flutter app — no login, no Rive animation, no scenario selection, no debrief, no UI beyond a call button
- Full voice pipeline with production tech stack: Soniox v4 (STT) → Qwen3.5 Flash via OpenRouter (LLM) → Cartesia Sonic 3 (TTS), orchestrated by Pipecat, transported via LiveKit WebRTC
- One hardcoded sarcastic character system prompt
- User speaks, AI character responds in real-time with voice

**Validation Targets:**

| Target | Success Threshold | Kill Signal |
|--------|-------------------|-------------|
| End-to-end perceived latency | <800ms target, <2s hard ceiling | >2s consistently → concept is dead |
| Voice quality (Cartesia Sonic 3) | Natural, expressive, supports sarcastic tone | Robotic or flat → wrong TTS provider |
| Character personality via LLM | Maintains sarcastic/impatient persona throughout conversation | Generic or breaks character → prompt rework needed |
| STT accuracy for non-native speakers | Understands intermediate English with accents | Misinterprets >30% of utterances → wrong STT provider |

**Why PoC-first:** Building with the production tech stack means zero throwaway code. The PoC building blocks (Pipecat pipeline, LiveKit transport, API integrations) carry directly into MVP. The PoC IS the foundation layer.

**Kill decision:** If latency >2s cannot be resolved, or voice quality/personality fundamentally fails, the project pivots or stops before further investment.

### Phase 1 — MVP

**Core User Journeys Supported:**
- Karim (Success Path): Download → first call → debrief → retry → progression
- Sofia (Failure Recovery): Failure messaging → immediate retry → gradual improvement
- Tomasz (Real-World Urgency): Diverse scenario selection → practical vocabulary feedback
- Walid (Operator): Scenario authoring → cost monitoring → difficulty tuning

**Must-Have Capabilities:**

| # | Capability | Why It's Non-Negotiable |
|---|-----------|------------------------|
| 1 | Real-time voice call with AI pipeline (PoC foundation + scenario logic) | This IS the product. PoC validates the pipeline; MVP adds scenario structure on top |
| 2 | Animated 2D Rive character with emotional reactions + lip sync | Without animation, it's a voice chatbot. Single Rive puppet file with 5 character skins (mugger, waiter, girlfriend, cop, landlord) switchable via EnumInput — new scenarios = new system prompts + character variant selection, not new .riv files |
| 3 | Post-call debrief with specific error flagging | "The debrief is the real value." No debrief = no learning = no reason to pay |
| 4 | 5 scenarios at launch (3 free + 2 paid) | Minimum content to test retention and conversion. First scenario calibrated for near-guaranteed success. Character hang-up mechanic doubles as natural call duration limit = controlled API costs |
| 5 | Scenario list with completion % + call/report buttons | Three screens total: list, call, report. Minimalist, no mobile nav |
| 6 | Subscription paywall ($1.99/week) | Validates willingness to pay. Triggers after free content exhausted at emotional peak |
| 7 | Minimal onboarding (email → immediate first call) | Zero friction. The call IS the onboarding |
| 8 | Offline access for scenario list + debriefs | Consultable without network. Call attempts show phone-style "No network" screen |
| 9 | App Store compliance (13+, AI disclosure, content warnings) | Gate to distribution. No compliance = no launch |

**Explicitly Excluded from MVP:**
- Push notifications (permission requested, nothing sent)
- Shareable replay clips (organic UGC via screenshots sufficient for viral validation)
- Challenge-a-friend / deep links
- Wordle-style text sharing
- Cumulative cross-session error tracking
- Evolving user avatar
- Dual pricing (weekly only at launch)

### Phase 2 — Growth (Month 3-6)

- Push notifications in character voice (retry nudges, new content alerts)
- Shareable 15-30s replay clips with animated character + subtitles
- Challenge-a-friend deep links (Branch.io, 16.5% conversion benchmark)
- Wordle-style zero-friction text sharing for WhatsApp/Discord
- Weekly content drops (2 new scenarios/week)
- Cumulative error tracking across sessions for personalized improvement
- Dual pricing: weekly ($1.99) + monthly ($7.99) with upsell gate after 3-4 renewals
- Rive Data Binding stat cards (Spotify Wrapped-style) for sharing

### Phase 3 — Vision (Month 6-12+)

- Evolving user avatar reflecting scenario outcomes (suit from job interview, scar from mugger). Avatar as social currency
- Life-path narrative arc — American Dream progression from high school through career and relationships. Branching paths
- Additional target languages (Spanish, French, German)
- Community-created scenarios
- Corporate/B2B tier
- Self-hosted TTS (Chatterbox) to eliminate API costs at scale

### Risk Mitigation Strategy

**Technical Risks:**

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Sub-800ms latency not achievable | Product concept dead | Phase 0 PoC validates before any product investment. Filler animations buy 500ms+ in MVP |
| STT accuracy insufficient for non-native speakers | Core mechanic broken | Soniox v4 selected for accent robustness. Fallback: Deepgram Nova-3 |
| LiveKit WebRTC integration unstable on Flutter | Calls unreliable | LiveKit has official Flutter SDK. Fallback: direct WebSocket |

**Market Risks:**

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Adversarial tone discourages rather than motivates | Users don't retry = product fails | Retry rate is kill metric. Character "meanness" dial adjustable in system prompt without code changes |
| Users don't find debrief valuable enough to pay | No conversion | Debrief engagement rate tracked. Can enrich feedback depth without pipeline changes |
| App Store rejects for content | No distribution | Lighter scenarios first (waiter, interviewer). Mugger added post-approval. 8 content modifications pre-planned |

**Resource Risks:**

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Solo developer burnout or time constraints | Delayed launch | MVP is 9 capabilities, not 20. Scenario creation = 3h for 2 scenarios (system prompt only, no art) |
| API costs exceed projections | Margin erosion | $0.044-0.054 per call with 30% headroom. Cost cap alerting. Free tier throttling as safety valve |
| Single point of failure | No redundancy | All managed services (LiveKit Cloud, API providers). No self-hosted infrastructure |

## User Journeys

### Journey 1: Karim — The Desk Worker Leveling Up (Primary User, Success Path)

**Who:** Karim, 26, backend developer at a mid-size company in Lyon. Reads Stack Overflow daily, watches YouTube tutorials in English, understands 90% of what he hears. But last week, his manager asked him to present a feature to the London team on a video call — and he froze. Stuttered through 3 sentences, switched to French, and felt humiliated. He knows his English is "good enough on paper." It's not good enough in his mouth.

**Opening Scene:** It's 10pm, Karim is scrolling TikTok after work. A clip shows someone staring at their phone screen with a defeated look — an animated character just hung up on them. The caption: "I tried to talk my way out of a mugging in English... 💀". Karim laughs, thinks "I could do better than that," and taps the App Store link.

**Rising Action:** He downloads SurviveTheTalk, enters his email. No tutorial, no settings, no onboarding quiz. His phone rings — an animated character appears on screen. A nervous-looking guy in a dark alley says: "Hey. Don't move. Give me your wallet. Now." Karim's heart rate spikes. He stammers: "I... I don't have... wallet... please, I am not want problem." The character rolls his eyes: "You 'am not want'? What does that even mean? Try again." Karim tries harder. He makes it 73% through the scenario before the mugger hangs up, frustrated.

**Climax:** The debrief screen appears. No "great job!" — instead: "You said 'I am not want problem' — the correct form is 'I don't want any trouble.' You used 'I am agree' twice — drop the 'am.' Your longest silence was 4.2 seconds after the threat escalated — this is where you froze." Karim stares at the screen. For the first time, someone told him *exactly* what he's doing wrong. Not a grade. Not a score. Specific sentences, specific corrections.

**Resolution:** Karim retries the scenario the next evening. He makes it to 89%. The mugger still hangs up, but later. The debrief shows fewer errors. He screenshots his progress — "Day 1: 73%. Day 3: 89%" — and sends it to his WhatsApp group with a laughing emoji. Two friends download the app. The following week, his manager schedules another call with London. Karim is still nervous — but he's done 5 calls with characters far meaner than his British colleagues. He survives the meeting. No French this time.

**Requirements revealed:** Onboarding-free first call flow, real-time character emotional reactions, discourse coherence evaluation (not pronunciation), post-call debrief with specific error flagging, retry with progression tracking, scenario dashboard, share mechanic (screenshot/replay).

### Journey 2: Sofia — The Pre-Exchange Student (Edge Case: Failure Recovery)

**Who:** Sofia, 21, studying business in Madrid. She's leaving for ERASMUS in Manchester in 5 months. Her written English got her a B2 certificate. But yesterday she tried ordering food in English at a tourist restaurant — pointed at the menu instead of speaking. She's terrified of living in English.

**Opening Scene:** Sofia sees an Instagram Reel from a classmate who's already abroad: a SurviveTheTalk stat card reading "Survival rate: 34% — Roast level: 🔥🔥🔥🔥💀". She thinks it looks fun and low-stakes — it's a game, not a lesson. She downloads it.

**Rising Action:** First scenario: the sarcastic waiter. "Welcome to the worst restaurant in town. What do you want?" Sofia panics. She says "I want... the... food... the chicken?" The waiter sighs dramatically, rolls his eyes: "The chicken. Which chicken? We have six. Use your words." Sofia tries harder but mixes Spanish syntax with English. At 45%, the waiter says "I'm done waiting" and the call ends.

**Failure Moment:** Sofia feels a sting. But then the debrief appears: "You defaulted to noun-only responses ('the chicken') instead of complete sentences. Try: 'I'd like the grilled chicken, please.' Your hesitation average was 3.8 seconds — the waiter's patience threshold is 5 seconds. You're close." The tone is frank but not cruel. She sees she was 45% — close to halfway. The app says: "The waiter is still hungry. Try again?"

**Recovery:** Sofia retries immediately. She makes it to 62%. Then 78% the next day. By the end of the week, she survives the waiter and unlocks the cop scenario. She starts a WhatsApp group with her ERASMUS cohort: "Training for Manchester 💪" — 4 of them subscribe. When she arrives in Manchester, ordering food still makes her nervous. But she's done it 15 times with a character far ruder than any real waiter.

**Requirements revealed:** Graduated difficulty (waiter easier than mugger), failure messaging that motivates rather than discourages ("You're close"), immediate retry option post-debrief, scenario unlock progression, pre-scenario situational briefing to reduce anxiety on first attempt, social sharing triggers at emotional peaks, energy system allowing multiple retries on Day 1.

### Journey 3: Tomasz — The Fresh Expat (Alternative Goal: Urgent Real-World Situations)

**Who:** Tomasz, 31, Polish DevOps engineer who relocated to Dublin 3 months ago. His technical English is flawless — he thinks in English when coding. But his landlord just called about a broken heater, spoke fast Irish-accented English, and Tomasz understood maybe 40%. He said "yes, okay" to everything and still doesn't know if someone's coming to fix it. He needs to handle real confrontations, not textbook dialogues.

**Opening Scene:** Tomasz googles "practice difficult conversations in English." Nothing useful — Duolingo teaches him how to say "the cat is on the table." He finds SurviveTheTalk on the App Store. The description says "Survive. Don't get hung up on." He downloads it because it sounds like what he actually needs.

**Rising Action:** He skips the mugger and goes straight to the "angry landlord" scenario (paid). The character is impatient, speaks fast, uses idioms: "The boiler's been acting up for weeks, and you're only NOW telling me? Pull the other one." Tomasz doesn't know "pull the other one" means "I don't believe you." He responds logically: "The boiler stopped working on Tuesday. I am calling to report." The landlord escalates: "Right, so you let it run for a week? That's coming out of your deposit, mate."

**Climax:** Tomasz makes it to 67% before the landlord hangs up. The debrief flags: "'Pull the other one' = British idiom meaning 'I don't believe you.' You missed the accusation and responded with facts instead of defending yourself. Try: 'That's not fair — I reported it as soon as I noticed.'" Tomasz realizes: the app isn't testing his grammar. It's testing whether he can hold his ground in a real dispute.

**Resolution:** Over the next 2 weeks, Tomasz replays the landlord scenario 4 times and tries the job interview scenario. His actual landlord calls again about the deposit deduction. This time, Tomasz pushes back: "I reported the issue within 24 hours. The delay was on your end, not mine." The landlord backs down. Tomasz thinks: "That $2/week paid for itself in one phone call."

**Requirements revealed:** Scenario variety covering real-world situations (not just entertainment), idiom/slang detection and explanation in debrief, fast-speech comprehension as a challenge dimension, practical vocabulary focus, immediate real-world ROI.

### Journey 4: Walid — The Solo Operator

**Who:** Walid, solo developer and creator of SurviveTheTalk. Builds, deploys, monitors, creates content, handles support, and tracks financials. Needs to keep the product running, costs under control, and content pipeline flowing — all alone.

**Opening Scene:** Monday morning. Walid checks the dashboard: 312 active subscribers, 847 calls yesterday, average latency 620ms, API costs $58.30 for the day. One Soniox spike at 3am (latency hit 1.8s for 12 minutes) — LiveKit auto-reconnected, no user complaints logged. Revenue trend: +4.2% week-over-week. Everything's green.

**Rising Action:** Walid opens the scenario editor. This week's content: a "drunk friend calling at 2am asking for a ride" scenario and a "passive-aggressive coworker" scenario. He writes the system prompts — character personality, key vocabulary challenges, escalation triggers, fail conditions, debrief templates. Tests each scenario himself: latency acceptable, character stays in personality, difficulty feels right. Pushes to production. Total time: 3 hours for 2 scenarios.

**Operational Moment:** An App Store review comes in: 2 stars — "The mugger scenario is too scary for my 11-year-old." Walid checks: the app is rated 13+, the user shouldn't have access. He responds with the age rating explanation and flags internally that the content warning before intense scenarios could be more prominent. He adjusts the pre-scenario warning UI.

**Monitoring Cycle:** End of week, Walid reviews: cost per call trending at $0.051 (within budget), D7 retention at 16.8% (above 15% target), retry rate 54% (above 50% threshold). One concern: the cop scenario has a 22% completion rate — too hard. He adjusts the escalation pacing in the system prompt. Churn: 13.4% monthly — below 15% target. No action needed.

**Requirements revealed:** Operational dashboard (latency, costs, retention, revenue), scenario creation workflow (system prompt editor + testing), content moderation tooling, App Store review monitoring, cost tracking per user/per call, scenario difficulty tuning, alerting for latency spikes and cost anomalies.

### Journey Requirements Summary

| Journey | Key Capabilities Revealed |
|---------|--------------------------|
| **Karim (Success Path)** | Zero-friction onboarding, real-time character reactions, discourse coherence evaluation, specific-error debrief, retry with progression tracking, social sharing |
| **Sofia (Failure Recovery)** | Graduated difficulty, motivational failure messaging, immediate retry, scenario unlock progression, Day 1 multi-call allowance, social group dynamics |
| **Tomasz (Real-World Urgency)** | Diverse real-world scenarios, idiom/slang explanation, fast-speech challenge, practical vocabulary focus, immediate real-world ROI |
| **Walid (Solo Operator)** | Ops dashboard, scenario authoring workflow, cost monitoring, difficulty tuning, content moderation, App Store review management, alerting |

## Domain-Specific Requirements

### Compliance & Regulatory

- **Age Rating:** 13+ (Apple) / PEGI 12 (Google). No additional age gate beyond App Store enforcement for MVP
- **EU AI Act Article 50** (deadline August 2026): Mandatory disclosure that the user is interacting with AI-generated characters and voices. Must be visible before first call — integrated into consent flow at onboarding
- **GDPR Article 9 / Voice Data:** Voice is processed in real-time for STT transcription but not stored as raw audio. Consent screen at onboarding covers data processing. Privacy policy must explicitly describe voice processing pipeline
- **BIPA (Illinois):** If voice biometric data is stored (voiceprints, etc.), written consent required. MVP mitigation: do not store raw voice recordings or derive biometric identifiers — process and discard. Document this in privacy policy
- **App Store Content:** Education as primary category. Content warnings before intense scenarios (mugger, cop). 8 content modifications from domain research already planned

### Content Safety

- **LLM Guardrails:** System prompt boundaries define character behavior limits. Characters stay in-persona — no out-of-character harmful content generation
- **User Abuse Handling:** If user inputs inappropriate/off-topic content, the character reacts in-persona (gets angry, hangs up). Post-call debrief explains what happened. The adversarial mechanic is the moderation layer — no separate content filter needed for MVP
- **Scenario Review:** Each scenario manually tested by operator (Walid) before production push. System prompt defines escalation triggers, fail conditions, and behavioral boundaries
- **Character IP:** All character designs are 100% original. Tone inspired by adult animation energy but no third-party IP referenced or reproduced. Sarcastic and impatient YES, insulting or degrading NEVER

### Accessibility (MVP Scope)

- **UI Navigation:** Three screens only — scenario list, call screen, debrief/report. Minimalist layout (scenario title + success %, green call button, report button). No mobile nav. VoiceOver/TalkBack compatibility for these static UI elements
- **Core Experience:** Voice-first by design. The call itself is inherently accessible to visually impaired users. Debrief text must support dynamic font sizing and screen reader
- **Post-MVP:** Subtitles/captions during calls, high-contrast mode, expanded accessibility features as user base grows

### Risk Mitigations

| Risk | Mitigation | Trigger |
|------|-----------|---------|
| App Store rejection for violent content | Content warnings + Education category + lighter scenarios first (waiter, interviewer). Mugger scenario in post-launch update | Pre-submission |
| EU AI Act non-compliance | AI disclosure in consent flow + "AI-generated" label on character UI | Before August 2026 (MVP launch) |
| BIPA litigation for voice data | No raw voice storage, no biometric derivation. Process-and-discard architecture. Documented in privacy policy | Architecture decision |
| LLM generating harmful content | System prompt guardrails + character persona boundaries + in-persona hang-up as safety valve | Runtime |
| Underage user access | 13+ App Store rating enforced by platform. No additional age gate for MVP. Revisit if flagged | Post-launch monitoring |

## Innovation & Novel Patterns

### Detected Innovation Areas

**1. Category Creation: Adversarial Entertainment for Language Learning**
No existing product occupies the intersection of adversarial gaming mechanics and spoken English practice. Competitors (Speak, ELSA, Praktika) are supportive, patient, and encouraging. SurviveTheTalk inverts this: characters are sarcastic, impatient, and reactive — creating a fundamentally different emotional experience. This is not incremental differentiation; it is a new product category with zero direct competitors.

**2. Inverted Pedagogical Model: Test-Then-Teach**
Traditional language apps teach first, then test (if at all). SurviveTheTalk tests first under stress, then teaches through brutally honest post-call debriefs. The emotional engagement from failure creates a receptivity to feedback that passive lessons cannot match. The call validates the user's real level; the debrief delivers the actual learning value.

**3. Adversarial Mechanic as Multi-Purpose Engine**
The core adversarial loop (character gets frustrated → hangs up if user fails) simultaneously serves as: gameplay mechanic, difficulty scaling, content moderation (character hangs up on abuse), engagement driver (retry motivation), and viral content generator (shareable failure moments). One mechanic, five functions — no additional systems needed.

**4. API Convergence Enabling Solo Development**
Three independent technology trends converging in 2025-2026 make this product viable for a solo developer: sub-800ms conversational AI APIs (Soniox + Qwen + Cartesia), Rive real-time 2D animation with data binding, and vibe coding for cross-domain implementation. This dramatically lowers the profitability threshold (break-even at 60 subscribers) and eliminates the need for external funding.

### Validation Approach

| Innovation Aspect | Validation Method | Success Signal |
|-------------------|-------------------|----------------|
| Adversarial entertainment works for learning | Retry rate after failure >50% within 48h | Failure motivates rather than discourages |
| Test-then-teach loop delivers value | Debrief engagement >70% read full report | Users find honest feedback valuable, not punishing |
| Viral mechanic generates organic growth | K-factor >0.3 from UGC screen recordings | Experience is compelling enough to share without prompting |
| Solo dev model is sustainable | Break-even within 3 months at 60 subscribers | Revenue covers API costs + App Store commission |

### Innovation-Specific Risks

| Innovation Risk | Fallback |
|----------------|----------|
| Voice-first UX too high friction for onboarding | Add optional text-input mode as accessibility fallback (degrades experience but preserves core loop) |

See Risk Mitigation Strategy in Product Scope for technical, market, and resource risks.

## Mobile App Specific Requirements

### Platform Requirements

- **Framework:** Flutter (Dart), single codebase for iOS and Android
- **Minimum OS:** iOS 15+ / Android 10+ (API 29) — covers 95%+ of active devices while ensuring WebRTC and modern audio API support
- **Target devices:** Phones only (no tablet-optimized layout for MVP). Standard portrait orientation
- **Distribution:** Apple App Store + Google Play Store. No sideloading, no web fallback
- **Build pipeline:** Flutter standard — separate release tracks for iOS (TestFlight → App Store) and Android (internal testing → Play Store)

### Device Permissions

| Permission | Required | Timing | Rationale |
|-----------|----------|--------|-----------|
| Microphone | Yes — core feature | Before first call (system prompt) | STT requires live audio input via LiveKit WebRTC |
| Push Notifications | Request at MVP, unused | After first completed call | Permission primed for post-MVP retention features. No notifications sent in MVP |
| Internet/Network | Implicit (no prompt) | Always | STT/LLM/TTS pipeline is cloud-based |
| Camera | No | — | Not used |
| Location | No | — | Not used |

**Microphone denial handling:** If user denies microphone permission, the call cannot proceed. Display in-persona message: character taps the screen impatiently — "I can't hear you. Check your mic." with a system prompt to re-request permission.

### Offline Mode

- **Scenario list:** Cached locally after first load. Available offline with last-known completion percentages
- **Debrief reports:** Stored on-device after generation. All past reports consultable without network
- **Call attempt without network:** Simulated phone-style "No network" screen — maintains the real-phone metaphor. No error dialog, no technical message. The app behaves like a real phone that lost signal
- **Data sync:** Scenario list and new scenarios sync on app launch when network available. Debriefs generated server-side and cached on receipt

### Push Notification Strategy

- **MVP:** Permission requested after first completed call (high-intent moment). No notifications sent — infrastructure only
- **Post-MVP (second pass):** Retention-driven notifications in character voice:
  - Retry nudges: "The mugger is still waiting. You going to let him win?" (48h after failed scenario)
  - New content: "New scenario dropped. Think you can survive a passport check?" (weekly content drops)
  - Streak/engagement: Contextual, not daily spam. Tied to user behavior, not calendar
- **Opt-out respect:** Standard OS-level controls. No dark patterns to re-enable

### In-App Purchase Integration

- **Subscription:** $1.99/week auto-renewable via StoreKit 2 (iOS) / Google Play Billing Library
- **Tier enforcement:** Free: 3 scenarios, 3 calls total (lifetime, no daily recharge). Paid: all scenarios, 3 calls/day
- Store compliance details covered in Domain-Specific Requirements

## Functional Requirements

### Call Experience

- **FR1:** User can initiate a voice call with an AI character from the scenario list
- **FR2:** User can speak in English and receive real-time spoken responses from the AI character
- **FR3:** User can see the AI character's animated emotional reactions during the call (facial expressions, gestures)
- **FR4:** User can see the AI character's mouth movements synchronized with its speech
- **FR5:** AI character reacts emotionally based on the quality and content of the user's speech
- **FR6:** AI character ends the call (hangs up) when user performance drops below scenario thresholds or user behavior is inappropriate
- **FR7:** User can end the call voluntarily at any time
- **FR8:** System displays a phone-style "no network" screen when user attempts a call without internet connectivity

### Post-Call Debrief

- **FR9:** User can view a debrief report after each completed or failed call
- **FR10:** Debrief identifies specific language errors the user made with correct alternatives provided
- **FR11:** Debrief provides a survival/completion percentage for the call
- **FR12:** Debrief highlights longest hesitation moments and their context
- **FR13:** Debrief explains idioms or slang the user encountered but may not have understood
- **FR14:** User can view a short situational briefing (key vocabulary, context, what to expect) before attempting a scenario for the first time
- **FR15:** User can retry a scenario after viewing the debrief by navigating back to the scenario list (no direct retry button — intentional friction for study encouragement and cost control)
- **FR15b:** Debrief presents failure context with encouraging framing when user completion exceeds 40% (e.g., proximity to next threshold, specific improvement since last attempt)

### Scenario Management

- **FR16:** User can browse a list of all available scenarios with title and completion percentage
- **FR17:** User can initiate a call or view the debrief/tips for each scenario from the list
- **FR18:** User can see their best completion percentage per scenario across attempts
- **FR19:** Scenarios are ordered in the scenario list from least to most challenging, with the first scenario calibrated for near-guaranteed user success
- **FR20:** Free users can access 3 scenarios; paid users access all scenarios
- **FR21:** Free users get 3 calls total (lifetime, no daily recharge); paid users get 3 calls per day

### User Onboarding & Authentication

- **FR22:** User can create an account with email only
- **FR23:** User receives their first incoming call immediately after account creation with no tutorial
- **FR24:** User is presented with consent and privacy information before first use
- **FR25:** User is informed that they are interacting with AI-generated characters and voices before first call
- **FR26:** System requests microphone permission before the first call
- **FR27:** System requests push notification permission after the first completed call

### Monetization

- **FR28:** User can subscribe to a weekly paid plan ($1.99/week)
- **FR29:** Paywall is presented immediately after the user completes or fails their 3rd free scenario, on the debrief screen
- **FR30:** User can manage their subscription status (view, cancel)
- **FR31:** System enforces call and scenario limits based on user's free or paid tier

### Offline & Data Sync

- **FR32:** User can view the scenario list offline with last-known completion percentages
- **FR33:** User can view all past debrief reports offline
- **FR34:** Scenario list and debrief data sync automatically when network becomes available

### Content Safety & Compliance

- **FR35:** AI character stays within defined personality and behavioral boundaries during calls
- **FR36:** AI character reacts in-persona (escalates anger, hangs up) when user inputs inappropriate or off-topic content
- **FR37:** Debrief explains what happened when a call ends due to inappropriate user behavior
- **FR38:** Content warnings are displayed before scenarios involving threat, confrontation, or authority pressure (e.g., mugger, cop, angry landlord)
- **FR39:** App displays AI-generated content disclosure visible before first call (EU AI Act Article 50)

### Operator Tools

- **FR40:** Operator can create new scenarios via system prompt configuration (character personality, vocabulary challenges, escalation triggers, fail conditions, debrief templates)
- **FR41:** Operator can test scenarios before publishing to production
- **FR42:** Operator can adjust scenario difficulty parameters without code changes
- **FR43:** Operator can monitor real-time operational metrics (latency, active calls, API costs)
- **FR44:** Operator can view retention, conversion, and engagement KPIs on a dashboard
- **FR45:** Operator receives alerts when average perceived latency exceeds 1.5s over a 5-minute window or when daily API cost exceeds 130% of the 7-day rolling average
- **FR46:** Operator can track per-call and per-user API costs

## Non-Functional Requirements

### Performance

| Metric | Target | Hard Ceiling | Rationale |
|--------|--------|-------------|-----------|
| Perceived response latency (user speech end → character speech start) | <800ms | 2,000ms | Below 800ms feels like natural conversation. Above 2s, illusion of real conversation breaks — product concept is dead |
| STT processing time | <300ms | 500ms | Soniox v4 streaming. Must leave budget for LLM + TTS in the pipeline |
| LLM response generation (first token) | <200ms | 400ms | Qwen3.5 Flash via OpenRouter. Streaming response to TTS |
| TTS audio generation (first audio chunk) | <200ms | 400ms | Cartesia Sonic 3 streaming. Audio must start before full response is generated |
| Rive animation frame rate | 60fps | 30fps minimum | Character reactions must be fluid. Below 30fps, animation looks broken |
| App cold start to scenario list | <3s | 5s | Standard mobile app expectation. Cached data loads first, sync in background |
| Debrief generation time | <5s after call ends | 10s | LLM analysis of transcript. User sees loading animation in character style |

### Security

- **Voice data:** Process-and-discard architecture. Raw audio is streamed to STT and never stored on device or server. No voice biometric derivation (BIPA compliance)
- **Transcript data:** Call transcripts stored server-side for debrief generation. Encrypted at rest (AES-256). Retained for debrief access; user can request deletion (GDPR Article 17)
- **Authentication:** Email-based account. Session tokens with 30-day expiry. No password — passwordless authentication method for MVP simplicity
- **Payment data:** Zero payment data handled directly. Delegated entirely to StoreKit 2 (Apple) and Google Play Billing Library. No PCI-DSS scope
- **API keys:** All AI provider API keys (STT, LLM, and TTS providers) secured server-side via API gateway. Never exposed to client
- **Data in transit:** TLS 1.3 minimum for all client-server communication. WebRTC (LiveKit) encrypted by default (DTLS-SRTP)

### Scalability

| Scenario | Target | Approach |
|----------|--------|----------|
| MVP launch | 60-500 concurrent subscribers, ~50-100 daily calls | Single API gateway instance. All APIs are pay-per-use with no provisioning needed |
| Growth phase | 500-5,000 subscribers, ~500-1,000 daily calls | Horizontal API gateway scaling if needed. API providers handle load. WebRTC transport layer auto-scales |
| Viral spike | 10x normal traffic in 24h | API rate limits are the bottleneck, not infrastructure. Queueing mechanism for call initiation. Free tier throttling as safety valve |

**Cost scaling:** Linear with usage. No fixed infrastructure costs that spike at thresholds. API-based architecture means $0.05/call whether serving 10 or 10,000 users.

### Reliability

| Metric | Target | Rationale |
|--------|--------|-----------|
| Call completion rate (no mid-call drops) | >95% | A dropped call is a destroyed experience. User blames the app, not their network |
| API provider failover | Graceful degradation within 5s | If Soniox fails mid-call, character says "I can't hear you anymore" and ends call naturally (in-persona) |
| App crash rate | <1% of sessions | Standard mobile quality bar. Crashes during calls are catastrophic for trust |
| Data sync reliability | Eventually consistent within 60s | Debrief and progress data must not be lost. Local-first with background sync |
| Uptime (API gateway + pipeline) | 99% monthly | Solo developer reality — 7h of downtime/month is acceptable for MVP. No on-call pager |

### Integration

| External System | Criticality | Failure Mode | Graceful Degradation |
|----------------|------------|-------------|---------------------|
| Soniox v4 (STT) | Critical — no call without it | API timeout or error | Character says "I can't hear you" → call ends in-persona. Retry prompt |
| OpenRouter / Qwen3.5 Flash (LLM) | Critical — no conversation without it | API timeout or error | Character pauses, looks confused → "Something's off. Call me back." → call ends |
| Cartesia Sonic 3 (TTS) | Critical — no voice output without it | API timeout or error | Fallback: text-only response on screen (degrades experience significantly) |
| LiveKit Cloud (WebRTC) | Critical — transport layer | Connection failure | Phone-style "call failed" screen. Automatic retry once |
| Apple StoreKit 2 / Google Play Billing | Important — monetization | Purchase validation delay | Optimistic access: grant paid access immediately, validate async. Revoke if validation fails |
| App Store / Play Store (distribution) | Gate — no app without it | Review rejection | Pre-planned content modifications. Lighter scenarios first strategy |
