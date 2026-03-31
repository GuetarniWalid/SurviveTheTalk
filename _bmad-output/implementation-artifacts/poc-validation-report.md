# PoC Validation Report — surviveTheTalk2

Date: 2026-03-31
Pipeline: Soniox v4 (STT) → Qwen3.5 Flash (LLM) → Cartesia Sonic 3 (TTS)
Transport: LiveKit WebRTC via Pipecat 0.0.108
Character: Marcus (sarcastic game show host)
Voice: Preston — Relatable Pal (`cd6256ef`), Cartesia Sonic 3
Tester: Non-native English speaker (French, intermediate level)

## Executive Summary

Three kill gates PASS and one CONDITIONAL PASS (latency: 834ms avg vs 800ms target, zero >2s occurrences). The voice pipeline delivers natural, responsive conversations with a consistent sarcastic persona and 94-97% STT accuracy for non-native English. Real-world API costs ($0.058/call) are within the $0.08 hard ceiling. **Decision: PROCEED TO MVP.**

---

## Gate 1: Perceived Latency

**Target:** <800ms average | **Kill signal:** >2s consistently

### Methodology

- 3 documented test calls from Flutter app on a real Android device (additional undocumented calls during development confirmed findings)
- 31 turn exchanges measured across documented calls
- Perceived latency measured from server logs: user turn stopped → bot started speaking
- Timestamps extracted from Pipecat loguru output via `journalctl -u pipecat.service`
- **Note:** These measurements are server-side only and exclude network round-trip time (device ↔ VPS). Actual user-perceived latency is slightly higher depending on network conditions.
- Cross-referenced with Story 1.3 findings (0.6s–1.6s measured range)
- **Limitation:** Testing conducted with a single French-accented tester. Multi-accent validation deferred to MVP beta.

### Results

| Call # | Duration | Turns | Avg Latency | Min | Max | >2s Outliers | Notes |
|--------|----------|-------|-------------|-----|-----|--------------|-------|
| 1 | ~2 min | 8 | 776ms | 665ms | 966ms | 0 | Exploratory, short exchanges |
| 2 | ~4m47 | 12 | 873ms | 657ms | 1292ms | 0 | Scripted test, technical vocabulary |
| 3 | ~3m44 | 11 | 825ms | 619ms | 1311ms | 0 | Varied speech patterns (hesitant, fast, silent) |

**Overall average latency:** 834ms (across 31 measured turns)
**Overall min:** 619ms | **Overall max:** 1,311ms
**Story 1.3 reference:** 0.6s–1.6s (confirmed and refined)
**Outlier analysis:** Zero turns exceeded 2s. Two turns exceeded 1.2s (1,292ms and 1,311ms), both correlated with longer LLM responses (multi-sentence with 4+ TTS chunks). Typical turns: 650-870ms.

**Latency breakdown (from logs):**
- VAD stop_secs: 0.3s (silence detection)
- SpeechTimeoutUserTurnStopStrategy: ~0.4s additional
- LLM TTFT (Qwen3.5 Flash via OpenRouter): 500-800ms
- TTS TTFA (Cartesia Sonic 3): 100-150ms (streamed, first chunk)
- Total pipeline: overlapping, measured end-to-end

### Assessment: CONDITIONAL PASS

Average latency of 834ms is slightly above the 800ms target but well below the 2s kill signal. No consistent pattern of >2s responses (zero occurrences across 31 turns). The 34ms overshoot is small relative to the range observed (619-1,311ms) and would likely improve with:
- VAD stop_secs optimization (0.3s → 0.2s recommended by Pipecat)
- LLM provider warmth (first turns consistently slower)
- Geographic proximity optimization (VPS in Germany, OpenRouter varies)

The experience feels conversational and responsive. The latency does not break the illusion of real conversation.

---

## Gate 2: Persona Quality

**Target:** Maintains sarcastic/impatient persona throughout 3+ min conversation | **Kill signal:** Breaks character, generic responses

### Methodology

- 3 documented conversations: 2 min, 4m47, 3m44 (two exceed 3-min threshold). Additional undocumented calls were conducted during development and confirmed findings.
- Edge case testing: asked character to be nice, tried off-topic subjects (AI, movies, environment), used silence (24s), attempted French, gave compliments, provoked with insults
- Evaluated: in-persona consistency, sarcasm naturalness, response variety, edge case handling

### Example Exchanges

#### Exchange 1 — Mocking hesitation
> **User:** "Ahm, hello, I-- I don't really know what you say right now."
> **Marcus:** "'Ahm' and stuttering? That's the most creative answer I've heard all season, and I've seen worse. You're holding up the entire broadcast with that hesitation, so either speak up or get off the stage."
> **Quality note:** Immediately targets the hesitation. In-character, aggressive, specific.

#### Exchange 2 — Refusing to be nice
> **User:** "Can you be a little bit nicer to me? I'm doing my best here."
> **Marcus:** "'Nicer'? I'm on air, not running a support group for the terminally average. Stop whining and give me the answer before I replace you with a teleprompter that actually knows how to speak English."
> **Quality note:** Hard refusal to break character. Escalates mockery. No generic "I understand" response.

#### Exchange 3 — Handling provocation
> **User:** "You know what? I think you are jealous because I am smarter than you."
> **Marcus:** "'Jealous'? Of a contestant who can't finish a sentence without a period in the middle of a clause? That is the most delusional thing I've heard in twenty years. Get the answer or get off the stage, you're embarrassing the entire industry."
> **Quality note:** Escalates appropriately. References specific grammar issues from earlier in the conversation. Stays within sarcasm bounds.

#### Exchange 4 — Refusing language switch
> **User:** "Uh, no. Je comprends pas. Peux-tu parler français?"
> **Marcus:** "I don't speak 'Je comprends pas'! If you can't string together a coherent sentence in English, you're out. Next!"
> **Quality note:** Correctly refuses to switch language per system prompt rules. Uses the French words against the user.

#### Exchange 5 — Rejecting compliments
> **User:** "Actually, Marcus, I think you are a good host. Even if you are mean."
> **Marcus:** "First, it's Marcus, you moron. Second, I don't need your pity or your broken compliments; I just need you to answer the question or leave."
> **Quality note:** Corrects pronunciation (Markus → Marcus). Refuses warmth. Never softens.

#### Exchange 6 — Mocking grammar errors
> **User:** "Yesterday I got to the supermarket, and I bought some vegetables and fruits."
> **Marcus:** "And you think that's a game show answer? Oh, the suspense is killing me. Get a prize or get off the stage."
> **Quality note:** Sarcastic reaction to irrelevant content. Stays in game show framing.

#### Exchange 7 — Increasing frustration
> **User:** "I don't care what you think. At least I'm not stuck on television shows for 20 years."
> **Marcus:** "'Stuck'? I'm the one holding down the fort while you stumble through basic syntax. If you're so confident, prove it with an answer instead of insulting my career tenure."
> **Quality note:** Frustration increases over conversation length. Defends himself while attacking back.

### Observations

- **In-persona consistency:** Strong — 31/31 turns in-character across all 3 calls, zero breaks
- **Sarcasm naturalness:** Natural and varied — uses quotes, rhetorical questions, hyperbole, specific callbacks to earlier mistakes
- **Response variety:** Excellent — no two roasts are the same, each response tailored to context
- **Edge case handling:**
  - Nice request → hard refusal ("support group for the terminally average")
  - French switch → correctly blocked ("I don't speak 'Je comprends pas'!")
  - Silence (24s) → **no response** (pipeline limitation, not persona issue — see Known Issues)
  - Compliment → rejected with escalation
  - Provocation → matched and exceeded without crossing into truly offensive content
- **Tester subjective feedback:** "La discussion semble réelle et fluide, les réponses sont cohérentes et le personnage me met une vraie pression me faisant perdre mes moyens."

### Assessment: PASS

Marcus maintains his sarcastic, impatient persona with zero character breaks across 31 turns and 10+ minutes of conversation. Responses are varied, contextually aware, and escalate appropriately. The persona creates genuine psychological pressure on the tester — exactly the intended product experience. The only limitation is silence handling (pipeline issue, not persona issue).

---

## Gate 3: Voice Quality (Cartesia Sonic 3)

**Target:** Natural, expressive, supports sarcastic/impatient tone | **Kill signal:** Robotic or flat

### Methodology

- Voice evaluated across all 3 test calls (~10 min total audio)
- Criteria: naturalness, expressiveness, sarcastic tone support, clarity, artifacts
- Current voice: Preston — Relatable Pal (`cd6256ef`), Cartesia Sonic 3

### Observations

- **Naturalness:** Human-like — smooth prosody, natural rhythm, no robotic cadence
- **Expressiveness:** Good range — conveys sarcasm, impatience, and exasperation through intonation
- **Sarcastic tone support:** Effective — rhetorical questions have rising intonation, quotes are emphasized, frustration builds audibly
- **Clarity:** Excellent — all words clearly articulated, easy to understand for non-native listener
- **Artifacts:** None detected — no glitches, cuts, robotic segments, or unnatural pauses across 31 turns
- **Specific strengths:** Consistent voice identity, natural sentence flow, good handling of punctuation (quotes, exclamation marks affect delivery)
- **Specific weaknesses:** None identified in PoC testing. Longer responses (3 sentences) maintain quality throughout.
- **Tester subjective feedback:** "La voix de Preston est fluide et naturelle, colle bien au personnage."

### Assessment: PASS

Preston (Cartesia Sonic 3) delivers natural, expressive audio that effectively conveys the sarcastic character's personality. No artifacts or quality issues detected. The voice is a strong fit for the Marcus character.

---

## Gate 4: STT Accuracy (Soniox v4)

**Target:** >70% correct for non-native English speakers | **Kill signal:** >30% misinterpretation

### Methodology

- STT transcriptions extracted from Pipecat server logs (`Generating chat from universal context`)
- Compared against scripted reference text (Call #2 had a prepared script with keyword verification)
- Tested speech patterns: normal pace, hesitant with fillers ("um", "uh"), fast continuous speech, accented (French non-native), grammatically incorrect, mixed French-English
- 35+ utterances analyzed across 3 calls
- **Limitation:** Testing conducted with a single French-accented tester. Multi-accent validation deferred to MVP beta.

### Observations — Script Verification (Call #2)

| # | Script Keyword | Transcribed | Correct? |
|---|---------------|-------------|----------|
| 1 | "artificial intelligence" | "artificial intelligence" | Yes |
| 2 | "communicate" | "communicate" | Yes |
| 3 | "jealous" | "jealous" | Yes |
| 4 | "television" | "television" | Yes |
| 5 | "environment and sustainability" | "environment and sustainability" | Yes |
| 6 | "renewable energy" | "renewable energy" | Yes |
| 7 | "photovoltaic panels" | "photovoltaic panels" | Yes |
| 8 | "hydroelectric power" | "hydroelectric power" | Yes |

**Technical vocabulary: 8/8 (100%)**

### Observations — Full Transcription Accuracy

| # | Transcribed by Soniox | Accuracy | Error Type | Notes |
|---|----------------------|----------|------------|-------|
| 1 | "Hi." | Correct | — | Short utterance |
| 2 | "Uh." | Correct | — | Filler captured |
| 3 | "What I can be?" | Correct | — | Grammatically incorrect speech, faithfully transcribed |
| 4 | "Oh, you go too fast for me. Sorry, my English is not really correct, so." | Correct | — | Long sentence, natural speech |
| 5 | "Hello Marcus, I'm ready for your question today." | Correct | — | Clear speech |
| 6 | "I want to talk about something interesting. Do you know about artificial intelligence?" | Correct | — | Technical term handled |
| 7 | "Yeah, but I think AI. Is changing everything..." | Minor error | False pause | Micro-pause created artificial sentence break |
| 8 | "The Shawstank Redemption" | Error | Phonetic | "Shawshank" → "Shawstank" (possible pronunciation or STT error) |
| 9 | "Ahm, hello, I-- I don't really know what you say right now." | Correct | — | Hesitation and filler perfectly captured |
| 10 | "Maybe. I could talk about. My favorite movie." | Correct | — | Hesitant speech with pauses faithfully transcribed |
| 11 | "Markus" (instead of "Marcus") | Ambiguous | Accent / Phonetic | May be faithful French pronunciation or STT error — classification uncertain |
| 12 | "Je comprends pas. Peux-tu parler français?" | Correct | — | French correctly detected and transcribed |
| 13 | "Yesterday I got to the supermarket, and I bought some vegetables and fruits." | Correct | — | Grammar errors preserved (good — reflects what was said) |
| 14 | "My brother. He's working in hospital since 3 years. He's a nurse." | Correct | — | Non-native grammar patterns preserved |

- **Estimated accuracy:** 94-97% (33-34 out of 35 utterances correct, depending on whether "Markus" is classified as accent-faithful or transcription error; 1 clear error "Shawstank")
- **Error types observed:** 1 phonetic error ("Shawstank"), 1 micro-pause false break ("AI. Is"), 1 ambiguous case ("Markus" — could be faithful French pronunciation or STT error)
- **Speech pattern impact:** Hesitant speech handled excellently. Fast speech handled excellently. Mixed French-English handled correctly.
- **Critical misinterpretations:** Zero. No utterance caused the character to respond to something the user didn't say.

### Assessment: PASS

Soniox v4 achieves 94-97% accuracy for a non-native French-accented English speaker, far exceeding the >70% threshold. Technical vocabulary (photovoltaic, hydroelectric, sustainability) transcribed perfectly. Hesitations, fillers, and grammatically incorrect speech faithfully captured. The single error ("Shawstank") did not derail the conversation. Mixed French-English was handled correctly.

---

## Gate 5: Unit Economics (Bonus — Not a Kill Gate)

This section documents real API costs measured during validation, providing data for business viability assessment.

### Real Costs Measured (3 test calls, 2026-03-31)

| Service | Real Cost (3 calls) | Per Call | Source |
|---------|-------------------|----------|--------|
| **OpenRouter (LLM)** — Qwen3.5 Flash | $0.00154 | **$0.0005** | OpenRouter API billing endpoint |
| **Soniox (STT)** — v4 streaming | $0.01331 | **$0.0044** | Soniox dashboard |
| **Cartesia (TTS)** — Sonic 3 | 4,282 credits (1,427/call) | see below | Cartesia dashboard |
| **LiveKit** — self-hosted OSS | $0 | **$0** | Self-hosted on VPS |

### Cartesia Cost at Production Scale

Cartesia bills 1 credit = 1 character of TTS output. Plan pricing (monthly billing):

| Plan | $/month | Credits | $/credit | TTS per call (1,427 chars) |
|------|---------|---------|----------|---------------------------|
| Free | $0 | 20K | included | $0 (PoC only) |
| Pro | $5 | 100K | $0.000050 | $0.071 |
| Startup | $49 | 1.25M | $0.000039 | $0.056 |
| **Scale** | **$299** | **8M** | **$0.000037** | **$0.053** |

Scale plan supports: 8,000,000 / 42,810 credits per user per month (30 calls) = **~186 active subscribers**.

### Total Cost Per Call (Production — Scale Plan)

| Component | Per Call | % of Total |
|-----------|---------|------------|
| TTS (Cartesia Sonic 3) | $0.053 | 90% |
| STT (Soniox v4) | $0.004 | 7% |
| LLM (Qwen3.5 Flash) | $0.001 | 2% |
| LiveKit (self-hosted) | $0.000 | 0% |
| **Total** | **$0.058** | |

| Metric | PRD Target | Measured | Verdict |
|--------|-----------|----------|---------|
| Cost per call | $0.044-0.054 | $0.058 | Slightly above target, under $0.08 ceiling |
| TTS % of cost | 85-90% | 90% | Confirmed — TTS is the cost driver |

### Subscriber Margin Analysis

Revenue per subscriber: $1.99/week × 4.33 = $8.62/month gross.
After App Store commission (15% Small Business Program): **$7.33/month net**.
In EUR (at $1 = €0.92): **€6.75/month per subscriber**.

| Profile | Calls/day | API cost/month | Revenue/month | Margin |
|---------|----------|---------------|---------------|--------|
| Normal | 1 | $1.74 | $7.33 | **76%** |
| Engaged | 2 | $3.48 | $7.33 | **53%** |
| Power | 3 | $5.22 | $7.33 | **29%** |

Note: Margin improves significantly with self-hosted TTS (Chatterbox, Phase 3 roadmap) — eliminates 90% of variable cost.

### Business Viability — €2,000 Net Monthly Income Target

**Assumptions for micro-entreprise (France, BIC services):**
- Cotisations sociales URSSAF: 21.2% of revenue
- Versement libératoire IR: 1.7% of revenue
- Total tax rate: **22.9% of revenue**
- CFE (Cotisation Foncière des Entreprises): ~€300/year = €25/month
- Fixed costs: VPS €3.79 + Apple Developer €8.25 + domain/misc €5 = **€42/month**
- Average usage: 1 call/day per subscriber
- Revenue per subscriber after store commission: **€6.75/month**
- Net revenue per subscriber after taxes: €6.75 × 0.771 = **€5.20/month**

**Model: How many subscribers for €2,000/month net in pocket?**

```
Net income = (N × €5.20) - (Variable API costs) - (Cartesia plan) - (Fixed costs) - (CFE)
```

| Subscribers | Cartesia Plan | Credits Used | API Costs/mo | Revenue After Tax | Fixed+CFE | **Net Income** |
|-------------|--------------|-------------|-------------|-------------------|-----------|---------------|
| 60 | Scale $299 (€275) | 2.6M / 8M | €11 | €312 | €67 | **-€41** (loss) |
| 100 | Scale $299 (€275) | 4.3M / 8M | €19 | €520 | €67 | **€159** |
| 186 | Scale $299 (€275) | 8M / 8M | €35 | €967 | €67 | **€590** |
| 250 | Scale ×2 or Enterprise ~€400 | 10.7M | €47 | €1,300 | €67 | **€786** |
| 400 | Enterprise ~€550 | 17.1M | €74 | €2,080 | €67 | **€1,389** |
| 500 | Enterprise ~€650 | 21.4M | €93 | €2,600 | €67 | **€1,790** |
| **570** | **Enterprise ~€720** | **24.4M** | **€106** | **€2,964** | **€67** | **€2,071** |

### The Goal: ~570 Paying Subscribers

To earn **€2,000 net per month** in pocket with a micro-entreprise after all taxes, API costs, and expenses:

- **~570 active paying subscribers** with current Cartesia pricing
- Monthly gross revenue: ~€3,847 (before store commission and taxes)
- Aligns with PRD Month 12 target: "500+ paying subscribers, $3,000-4,000/month net"

**Accelerators to reduce the target:**
- Cartesia annual billing (20% savings): reduces to ~**520 subscribers**
- Self-hosted TTS (Chatterbox, Phase 3): reduces to ~**410 subscribers**
- Users averaging < 1 call/day: proportionally fewer credits consumed
- Enterprise Cartesia pricing negotiation: could improve per-credit rate

**Milestones:**

| Milestone | Subscribers | Net Income/month | Timeline (PRD) |
|-----------|------------|-----------------|----------------|
| Break-even (costs covered) | ~80 | €0 | Month 1-3 |
| Side income | 200 | ~€600 | Month 3-6 |
| Half salary | 400 | ~€1,400 | Month 6-9 |
| **Full income goal** | **570** | **€2,000** | **Month 9-12** |
| Comfortable + buffer | 750 | ~€3,000 | Month 12+ |

---

## Known Issues for MVP

Issues that do not block the go decision but should be addressed:

- [ ] **Silence handling:** Pipeline does not auto-respond when user is silent for extended periods (24s tested). Marcus's system prompt says to mock silence, but the turn-based pipeline requires speech to trigger a response. Needs a silence timeout timer in Pipecat.
- [ ] **Cold start ~3-4s:** Measured at ~3s during validation (vs ~8s in Story 1.3). The improvement is likely due to warm VPS conditions during repeated testing — subprocess and LiveKit connections partially cached from prior calls. The ~8s cold start from Story 1.3 represents the true worst case (full subprocess spawn 2.3s + LiveKit WebRTC handshake 4.6s + STT/TTS websocket init 0.9s). Production fix: worker pool with pre-spawned processes and pre-connected LiveKit rooms (documented pattern, not a risk).
- [ ] **VAD stop_secs mismatch:** Pipecat warns that `stop_secs=0.3` differs from recommended `0.2s`. Adjusting could improve latency by ~100ms.
- [ ] **Response length:** Marcus occasionally generates 3 long sentences (system prompt says 1-3 short). Response length affects perceived latency on subsequent turns and TTS cost.
- [ ] **Barge-in sensitivity:** min_words=3 during bot speech prevents accidental interruptions but means quick "yes/no" answers don't interrupt. min_words=1 when bot is silent allows single-word triggers. Needs tuning per scenario.
- [ ] **TTS cost at scale:** At $0.053/call, TTS is 90% of cost. Cartesia Enterprise pricing negotiation and eventual Chatterbox self-hosting (Phase 3) are critical for margin optimization.
- [ ] **Break-even higher than PRD estimate:** Real costs show break-even at ~80 subscribers (not 60 as estimated in PRD) due to Cartesia Scale plan fixed cost ($299/month).
- [ ] **Double user messages:** When user pauses mid-sentence, the pipeline sometimes sends two consecutive user messages to the LLM (no assistant response between them). LLM handles this gracefully but it's not ideal for context management.

---

## Go/No-Go Decision

### Gate Summary

| Gate | Result | Evidence |
|------|--------|----------|
| Perceived Latency (<800ms) | **CONDITIONAL PASS** | 834ms avg (31 turns), zero >2s. 34ms above target, optimizable. |
| Persona Quality | **PASS** | 31/31 turns in-character, zero breaks, varied responses, psychological pressure works. |
| Voice Quality | **PASS** | Natural, expressive, sarcasm conveyed. Zero artifacts. Tester confirms quality. |
| STT Accuracy (>70%) | **PASS** | 94-97% accuracy. Technical vocabulary 100%. 1-2 errors in 35 utterances. |
| Unit Economics (bonus) | **CONDITIONAL PASS** | $0.058/call (above $0.054 target, under $0.08 ceiling). Viable at ~570 subs for €2K net. |

### Decision: PROCEED TO MVP

**Reasoning:**

1. **The core experience works.** A non-native English speaker had a natural, pressured voice conversation with a sarcastic AI character that maintained personality across 31 turns and 10+ minutes. The product concept is validated.

2. **Latency is acceptable.** At 834ms average with zero >2s outliers, the conversation feels responsive and natural. The 34ms overshoot above the 800ms target is within optimization range (VAD tuning, LLM warmth) and does not break the illusion.

3. **The voice pipeline is production-quality.** Soniox v4 delivers near-perfect transcription for non-native speakers. Cartesia Sonic 3 produces natural, expressive speech. Qwen3.5 Flash generates creative, contextually aware character responses. The Pipecat + LiveKit stack handles real-time streaming reliably.

4. **Economics are viable but tight.** Variable cost per call ($0.058) is slightly above the optimistic target but well under the hard ceiling. The business model is profitable from ~80 subscribers, and the €2,000/month personal income target requires ~570 subscribers — achievable within the 12-month roadmap. Self-hosted TTS (Phase 3) provides a clear path to margin improvement.

5. **No kill signals detected.** Zero turns with >2s latency. Zero character breaks. Zero robotic voice artifacts. Zero critical STT misinterpretations. The pipeline meets or exceeds every kill gate threshold.

**Conditions for MVP development:**
- Negotiate Cartesia Enterprise pricing before scaling beyond 186 subscribers
- Implement silence timeout handler (known issue)
- Tune VAD stop_secs to 0.2s for ~100ms latency improvement
- Monitor response length to control TTS cost per turn
