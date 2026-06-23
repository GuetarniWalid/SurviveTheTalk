# Survive the Talk — Landing Page Build Plan

> Produced 2026-06-23 by a 7-agent research+design workflow (4 finders → synthesize → adversarial critique → finalize). The adversarial critique's findings were folded into this final plan. **Infra facts live-verified over SSH 2026-06-23:** the VPS IPv6 `2a01:4f8:1c18:fbfd::1` is REAL and globally bound (critique's "fabricated" claim was wrong → keep the AAAA), Caddy runs as `caddy:caddy`, the live Caddyfile is `/etc/caddy/Caddyfile`.
>
> **Status: PLAN — awaiting Walid's §8 decisions. Nothing deployed.**

**Target:** `survivethetalk.com` (apex) | **Owner:** Kindopia / Walid | **Status:** pre-launch, no store links exist yet

---

## 1. Goal & Constraints

### Primary goal (two jobs, one page)
1. **Pass Google Play ORG website verification** — `survivethetalk.com` must be a real, on-domain page serving the company (Kindopia), the product, an on-domain contact email, and Privacy/Terms links, so reviewers cross-checking email↔domain↔registration see a legitimate business.
2. **Serve as a pre-launch marketing teaser** — capture an email from the right visitor (stuck-intermediate ESL learners: expats, interview prep).

### Hard constraints
- **One scrolling page.** No nav menu, no fake App Store / Play badges (they'd be lies and would render broken).
- **One CTA, repeated, never multiplied** — every button/link resolves to the email field.
- **Extends the app's existing identity** ("The Handler's Brief" design system) — this is a port of the app's look to web, NOT a rebrand. Reuse the exact 16-token palette and the Frijole/Inter type pair.
- **Primer-inspired restraint:** layout is calm, sober, uncluttered; the copy carries the attitude. Restraint lives in the words and the layout — never in hype or busy animation.
- **No hype.** Banned hard-fails (review gate): exclamation marks, question marks in chrome, praise, emoji, reassurance ("don't worry"), tips/how-to, urgency/scarcity cues, **and author-voice taunts that editorialize rather than state a fact**. The mechanical `!`/`?` lint does not catch hype-by-aside (e.g. "Yes, really.") — those are cut by hand at review.
- **A2/B1 parseable** — present tense, second person, no idioms. The audience is intermediate learners reading under mild stress.
- **Motion budget ≈ zero** — at most a subtle ticking timer in the hero mock. No parallax, no confetti, no autoplay.
- **Accessibility:** real `<label>` on the email input, AA+ contrast (the dark stage gives 13.5:1 text / 9.1:1 accent — don't dilute), `focus-visible` states, single-column reflow on mobile (~83% of traffic), page works with mock visuals turned off (text-first).

---

## 2. Google Org-Website Verification

### The requirement
Since Feb 2024, every new **organization** Play Console account must clear a verification suite (D-U-N-S, business-registration docs, identity via Google Payments profile, verified contact email/phone, **and** an Organization Website). The website step is a **domain-ownership proof** — a control check, not a content/design review. No human scores the prose; content matters only because reviewers and anti-fraud systems cross-check that org + email + domain form a coherent real business.

### The exact verification mechanism

Google accepts **two** ways to prove ownership. Use the first; keep the second as a fallback.

**Recommended path — Domain property (DNS TXT):**
1. Play Console shows **"Website Verification Required"** → View details → redirects to **Google Search Console**.
2. In Search Console, add a property of type **Domain** — enter the bare apex `survivethetalk.com` (NOT a subdomain, NOT `https://`, NOT `www`).
3. Search Console returns a **DNS TXT record** (`google-site-verification=...`). For a **Domain** property specifically the only offered method is DNS — HTML meta tag and HTML-file upload are not offered for that property type.
4. Add that TXT at **GoDaddy DNS**, Host `@`, full value, wait for propagation (can take up to 48h), click **Verify** in Search Console.
5. Back in Play Console → Account details → Organization website → **Send verification request**.

**Fallback path — URL-prefix property (HTML file or meta tag):** if DNS propagation stalls or the same-account rule below bites, add a **URL-prefix** property `https://survivethetalk.com/` instead. URL-prefix properties **do** offer the HTML-file-upload and meta-tag methods — drop the verification file into the served `public/` (or add the meta tag to `Base.astro`'s `<head>`) and rsync. This is a legitimate alternative; the "DNS only" restriction applies to **Domain** properties, not to Google Play verification as a whole.

**Account-matching rule (critical):** verify the domain in Search Console **while logged in as the exact Google account that owns the Play Console**. Same account → approval is automatic/instant. Different account → Search Console's registered owner must email-approve, and the request can stall.

**Keep the verification record forever** — removing the TXT (or the HTML file) un-verifies you.

### Pre-flight: resolve the account / contact-email conflict BEFORE submitting
The project's developer/contact identity today is `guetarni.walid@gmail.com` (a free Gmail), but the org check (a) needs the Search Console domain verified under the **same Google account that owns Play Console**, and (b) wants a **non-free** org contact email (`contact@survivethetalk.com`). These can collide. Resolve, in order, before clicking "Send verification request":
1. Confirm **which Google account owns the Play Console org account.**
2. Verify the Search Console property logged in as **that** account.
3. Confirm whether that account's **org contact email** must move off Gmail to `contact@survivethetalk.com` for the org check, and that the on-domain address actually receives mail (Resend MX/routing live).

### Must-have page content (so the org reads as legitimate)
The DNS TXT alone clears the technical gate, but the apex must serve a real page before you click "Send verification request":
- **About / who-we-are** naming **Kindopia** as the company behind the product — matching the legal name on the D-U-N-S / FR registration docs **verbatim**.
- **Contact email on the org's own domain** (e.g. `contact@survivethetalk.com`) — **must NOT be a free/generic mail** (no @gmail); Google rejects those for org accounts. Align it with the developer/contact email on the account.
- **The product:** what Survive the Talk is + pricing transparency (3 free scenarios, then $1.99/week).
- **Links to Privacy Policy and Terms** — already served over HTTPS (see §6 / L1: serve them from the apex itself so the cross-check never leaves `survivethetalk.com`).

### Top failure modes to avoid
1. **Apex 301-redirecting to a different domain** — Search Console does NOT follow cross-domain redirects. Serve the page **on `survivethetalk.com` itself**; never point the apex at another host.
2. **Verification record wrong/missing/not propagated** — paste the FULL TXT value at host `@`, wait (up to 48h), then Verify. If it stalls, switch to the URL-prefix HTML-file fallback.
3. **Wrong property type / domain string** — a Domain property = bare apex (auto-covers `api.` and all subdomains). No `www`, no `https://`, no typo'd TLD.
4. **Search Console owner ≠ Play Console account** — use the same Google account for both (see pre-flight).
5. **Kindopia name mismatch across D&B ↔ FR registration ↔ Google Payments** — the #1 documented org-verification failure (separate from the website step). Align the name verbatim everywhere; upload clear, uncropped docs.

### Ordering
Verification record (TXT or HTML file) = mandatory before clicking Verify. A populated landing page = strongly recommended before "Send verification request." Practical sequence: (a) align Kindopia name across D&B/Payments/registration, (b) resolve the account/contact-email pre-flight, (c) stand up the apex landing page, (d) Search Console-verify with the Play Console Google account, (e) Send verification request.

---

## 3. Web Design Tokens

Carry the app identity to web. These hex values are the single source of truth (`client/lib/core/theme/app_colors.dart`, verified 2026-06-23 — the 16-token set, count-asserted by `theme_tokens_test.dart`).

### Color tokens (CSS variable → hex → role)

**Core palette (what the marketing page leans on):**
| CSS var | Hex | Role |
|---|---|---|
| `--bg` | `#1E1F23` | Primary background — dark charcoal. The "stage." |
| `--surface` | `#414143` | Raised surface (debrief mock fill, avatar circles). (`avatarBg` in the app.) |
| `--text-primary` | `#F0F0F0` | ALL body text + icons. 13.5:1 on bg. |
| `--text-secondary` | `#8A8A95` | Metadata, eyebrows, captions, chrome. |

**Accent + functional (sparingly):**
| CSS var | Hex | Role |
|---|---|---|
| `--accent` | `#00E5A0` | Toxic mint. 9.1:1 on bg. **CTA / pill FILL ONLY. NEVER text or icon color.** |
| `--status-completed` | `#2ECC40` | "Survived" green — **data viz only**. |
| `--status-in-progress` | `#FF6B6B` | "Attempted, not survived" coral — **data viz only**. |
| `--destructive` | `#E74C3C` | Hang-up / errors on DARK only. Earned-meaning only. |
| `--warning` | `#F59E0B` | Amber. Rare, semantically earned. |

**Supporting:**
| CSS var | Hex | Role |
|---|---|---|
| `--hairline` | `rgba(255,255,255,0.08)` (`#14FFFFFF`) | The ONE sanctioned line — section separators / scroll-pinned footer edge. |
| `--gauge-track` | `#2A2B30` | Unfilled arc of a survival-score ring. |
| `--paywall-error` | `#C0392B` | Red text **on a light surface** (4.7:1). Use instead of `#E74C3C` (which fails AA on light). |

**Light-surface rule:** the page is overwhelmingly dark. If any section is built light (`#F0F0F0`), text-primary becomes near-black and any red text becomes `#C0392B` — never `#E74C3C`.

### Type system (self-host both, ship OFL.txt)
**Display — Frijole (weight 400 only):**
- File: `client/assets/fonts/frijole/Frijole-Regular.ttf`. Heavy slab/blackletter display face.
- **Web role:** hero H1 + section punch-lines ONLY, ALL-CAPS, 1–4 words per line. Never paragraphs, never UI chrome. Do NOT synthesize bold/italic.
- Tight line-height; guard letter-spacing (kerning loosens at large sizes).
- **FOUT note:** because the giant hero H1 is the one guaranteed-read element, do NOT leave it on plain `font-display: swap` (the heavy face snaps in visibly). **Preload Frijole** (`<link rel="preload" as="font" type="font/woff2" crossorigin href="/fonts/frijole/Frijole-Regular.woff2">`) and use `font-display: optional` on the Frijole `@font-face` so the hero either has the face or cleanly falls back without a late snap.

**Body/UI — Inter (400 / 500 / 600 / 700; italic 400), `font-display: swap`:**
| Class | Size | Weight | Use |
|---|---|---|---|
| `display` | 64px | 700 | The survival-% number in the debrief mock |
| `h1` | 38px | 400 | (rarely on web) |
| `h2` | 24px | 700 | Big numbers |
| `headline` | 18px | 600 | Section titles |
| `section` | 14px | 600 | Sub-headers |
| `body` | 16px | 400 | Body. On dark, always `line-height: 1.5`. |
| `body-emphasis` | 16px | 500 | Inline emphasis (weight, not color) |
| `caption` | 13px | 400 | Metadata |
| `eyebrow` | 12px | 500 | UPPERCASE, `letter-spacing: +1px`, `--text-secondary` |

**Responsive scale:** hero Frijole `clamp(40px, 8vw, 96px)`; Inter body 16–18px. Drama comes ONLY from the scale jump between a `12px` eyebrow and the big Frijole title.

### Voice / copy rules ("The Handler's Brief")
- **2 voice lines per section max** — everything else is flat, verifiable data. ≤ ~24 non-data words per section.
- **Page-wide taunt budget = 2.** Author-voice "winks" (taunts/asides that editorialize rather than state a fact) are capped at **two for the entire page**, not two per section. Past that, the page tips from deadpan into trying-too-hard.
- **Banned (hard fails):** `!`, `?` in chrome, praise, emoji, reassurance, tips, urgency/scarcity, hype-by-aside ("Yes, really.").
- **A2/B1 law:** present tense, second person, no idioms.
- **Tone by predictability, not comfort** — every comforting instinct becomes a fact or gets cut. Every taunting instinct clears the same bar: state a fact or cut it.
- **CTAs are plain declaratives** ("Notify me"), never "Get started today!".
- **Accent green is never a text color.**

### Layout principles
- **One left rail.** Nothing centered (hero Frijole may be the sole exception for impact; body/sections align left).
- **Two-ink discipline:** content = `--text-primary`, chrome = `--text-secondary`. Accent = fill only.
- **Zero furniture:** no cards, boxes, dividers, drop-shadows, or per-section icons. Grouping is done by **spacing ratio** — ~8px inside a group, 32px between groups, 40px after a header lockup. Only sanctioned line = the `--hairline`.
- **Emphasis by weight + position** (put the critical line LAST, nearest the CTA), never a chip/badge/box/color.
- **Whitespace is the design** — defend "empty-looking" tall sections against the add-a-box reflex.
- **No sticky nav-bar.** A sticky bar with its own CTA is the single most template-y element on a page like this and it multiplies the CTA. The hero CTA + the `#notify` section already carry conversion (see Section 0).

### DO / DON'T (condensed)
**DO:** open on `#1E1F23` with `#F0F0F0` text · Frijole ALL-CAPS for one hero line (preloaded, `font-display: optional`) · one left rail · single `#00E5A0` mint CTA pill with dark text · `#2ECC40`/`#FF6B6B` ONLY in the debrief data mock · self-host fonts + OFL · `#C0392B` for red on any light surface · cap author-voice taunts at 2 page-wide.
**DON'T:** color text green · add cards/shadows/gradients/dividers/icons · center the layout · add a sticky nav-bar/second persistent CTA · write hype/emoji/praise/scarcity/hype-by-aside · use Frijole for paragraphs · introduce a new color or second accent · use idioms · reassure/over-explain · add decorative motion.

---

## 4. Information Architecture — section-by-section with final copy

One scrolling page. Order: hook → define → mechanic → make-it-real → unique payoff → qualify → price → capture → legal. Every button resolves to the email field (`#notify`).

### Section 0 — Header (wordmark only, NOT a nav bar)
**Purpose:** orient without inviting exploration. A plain, **non-sticky** wordmark lockup at the very top — no menu, no persistent link, no second CTA. It scrolls away with the page.
**Copy:**
- Left wordmark: `Survive the Talk`
- No menu, no link, no outbound links. (Conversion is carried by the Hero CTA and the `#notify` section.)

### Section 1 — Hero
**Purpose:** state what this is and who it's at war with, in one breath. The only section guaranteed to be read.
**Copy:**
- **Frijole punch-line (H1, ALL-CAPS):** `NOT REAL. STILL BRUTAL.`
- **Headline (Inter, below):** `A phone call in English. With someone who hangs up on you.`
- **Subhead (1–2 lines, plain):** `Survive high-stakes calls with an AI that is sarcastic, impatient, and almost out of patience. Freeze, and it ends the call. Then it tells you exactly what you got wrong.`
- **Category line (small, `--text-secondary`):** `Spoken-English practice as a game you survive — not a study app.`
- **Primary CTA pill (`#00E5A0` fill, dark text, → `#notify`):** `Get notified`
- **Visual (optional, right column desktop / below copy or omitted on mobile):** a single restrained call-screen frame — caller avatar, a live ticking timer (the one allowed motion), a low "patience" bar in the red. Looks like a screenshot of a tense moment, not a brochure.

### Section 2 — What it is
**Purpose:** Content-First clarity for anyone who didn't fully get the hero. Disambiguate from study apps. Full-width quiet band, one column, 60–70 chars/line, thin `--hairline` top rule, no icons.
**Copy:**
> Most apps let you tap multiple-choice answers in your own time. This one calls you. You speak out loud, in real time, to a character who reacts, interrupts, gets annoyed, and leaves if you stall. It is the unscripted conversation you keep avoiding — on purpose, in a place where the stakes are fake.
>
> You are not studying English. You are surviving a conversation in it.

(Last line gets `body-emphasis` weight 500 — the differentiator, by weight not color.)

### Section 3 — How it works (3 beats)
**Purpose:** make the loop concrete and show it's a cycle. Three stacked rows (NOT side-by-side cards), numbered `01 / 02 / 03` in mono, `--hairline` between rows. On wide screens, a 3-column band, still divider-separated, still left-aligned.
**Copy:**
- **01 — Pick up.** `Choose a scenario. The phone rings. You have no script and no pause button.`
- **02 — Survive.** `Talk your way through. Hesitate too long and the character `**`hangs up on you`**`.`
  *(only "hangs up on you" gets weight 500 — the signature threat; the line carries itself, no aside)*
- **03 — Read the damage.** `Get a brutal debrief: the exact mistakes you made, the slang you missed, and a survival score you will want to beat.`

### Section 4 — Scenarios teaser
**Purpose:** make "high-stakes calls" tangible; closest substitute for social proof. Vertical list of 3–4 plain text rows: name (`--text-primary`, weight 500) + stakes line (`--text-secondary`). No avatars needed.
**Copy:**
- Framing line: `The calls you will have to survive.`
- **The landlord** — `He thinks you broke the lease. You have ninety seconds to disagree.`
- **The job interview** — `She is already bored. Change that.`
- **The cop** — `Routine stop. Do not make it less routine.`
- Quiet closer (`--text-secondary`, small): `More scenarios at launch. New ones added regularly.`

### Section 5 — The debrief (the unique payoff)
**Purpose:** the brutal post-call debrief is the differentiator; it earns its own section. One place where a **mono "report" mock** earns its keep — the one sanctioned bordered block (`--surface` fill or `--hairline` border), two-ink, screenshot-credible.
**Copy:**
- **Punch line / headline:** `Then it tells you the truth.`
- **Body:** `No gold stars. After every call you get the exact lines you fumbled, the slang and idioms you missed, the moment you lost the room, and a survival score. It is not encouraging. It is accurate.`
- **Mock artifact (monospace):**
```
SURVIVAL SCORE      42 / 100
You froze at 0:38. He hung up.
MISSED SLANG        "ballpark figure", "no rush"
WEAK MOMENT         "How are you?" (twice)
VERDICT             Survived: NO
```
- **Caption under mock (`--text-secondary`, tiny):** `Sample debrief. Yours will be worse.`
  *(This is one of the page's TWO sanctioned author-voice taunt lines — it is tied to the artifact, so it stays.)*

*(In the mock, `42 / 100` may use `--status-in-progress` and a survived line `--status-completed` — the only sanctioned data-color use. The block border is the one allowed exception to "zero furniture" because it IS the debrief artifact, not decoration.)*

### Section 6 — Who it's for
**Purpose:** let the stuck-intermediate self-identify; gently turn away beginners. Tight single paragraph, no persona photos.
**Copy:**
> For the plateau no app talks about: you understand podcasts and Netflix fine, but a real, live conversation still falls apart. Built for expats, interview prep, and anyone tired of understanding English without being able to speak it.
>
> Not for beginners. You need to already hold a basic conversation. This throws you in.

### Section 7 — Pricing (stated, not sold)
**Purpose:** set the commercial expectation honestly. NOT a pricing table (one tier ≠ a comparison grid). A single quiet block, free tier first, accent used ONLY on the price/number if at all.
**Copy:**
- `Three scenarios free. No card, no signup wall.`
- `After that, $1.99 a week if you want the rest.`
- (dry line — the page's SECOND and final sanctioned taunt) `Cancel whenever. We would rather you stayed because you keep losing to the landlord.`

### Section 8 — Email capture (`id="notify"` — the conversion anchor)
**Purpose:** the whole point. ONE field. Strong contrast; the one place the accent fill carries the button.
**Copy:**
- **Headline (Frijole or Inter headline):** `NOT LIVE YET.`
- **Sub:** `It is coming. Get one message when it does.`
- **Email field** (real `<label>`, `placeholder="you@email.com"`)
- **Button (`#00E5A0` fill, dark text):** `Notify me`
- **Microcopy under field (`--text-secondary`):** `One email when it launches. No spam, no drip sequence, no tips.`
- **Post-submit state:** `You are on the list. Try not to freeze.`
- **Platform note (muted, tiny):** `iOS and Android.` (no badges)

### Section 9 — Footer (legitimacy + Google verification content)
**Purpose:** compliance + the legal/contact content the Google org check wants. Quiet, low-contrast, small type, `--hairline` divider above. Two-column desktop (brand left, links right), stacked mobile.
**Copy:**
- Wordmark (small): `Survive the Talk`
- **About line (Kindopia — required for verification):** `Survive the Talk is made by Kindopia.`
- Links: `Privacy Policy` · `Terms` · `Contact`
- **Contact email (on-domain, required):** `contact@survivethetalk.com`
- Copyright: `© 2026 Kindopia. Survive the Talk.`

> **Page-wide taunt budget spent:** the two sanctioned author-voice lines are §5 "Sample debrief. Yours will be worse." and §7 "…you keep losing to the landlord." The earlier draft's footer sign-off ("We just started picking fights.") is **cut** — it would be a third taunt and push the page past deadpan. Everything else in the footer is flat fact.

> **Verification cross-check:** Section 9 carries the four things Google reviewers look for — Kindopia named, on-domain non-free contact email, the product + pricing (Sections 1/7), and Privacy/Terms links. Serve Privacy/Terms **from the apex** (see L1 in §6) so the reviewer's "links on the org domain" cross-check never leaves `survivethetalk.com`.

---

## 5. Tech Stack — Astro + Tailwind CSS

### Why Astro
- **Zero JS by default** — Astro ships static HTML; the only interactivity here is one email form + one smooth-scroll, so the page is essentially HTML/CSS. Matches the "motion budget ≈ zero" constraint and gives instant loads.
- **Trivial output** — `astro build` emits a plain `dist/` folder of static files that rsyncs straight to the VPS. No runtime, no server.
- **Component model** keeps the sections as separate `.astro` files without a heavy framework.
- **First-class font self-hosting** + easy `<link rel="preload">` for Frijole (committed, not optional — see §3 FOUT note).

### Why Tailwind
- Maps the brand tokens to utility classes once in config; enforces the two-ink discipline by simply not defining off-brand colors.
- Arbitrary-value escape hatch for the few exact pixel values (Frijole clamp).

### Project structure
```
landing/
├── astro.config.mjs
├── tailwind.config.cjs
├── package.json
├── public/
│   ├── fonts/
│   │   ├── frijole/Frijole-Regular.woff2   (convert from .ttf)
│   │   ├── frijole/OFL.txt
│   │   ├── inter/Inter-Regular.woff2 … Bold.woff2, Italic.woff2
│   │   └── inter/OFL.txt
│   ├── og-image.png            (social card)
│   └── favicon.svg
└── src/
    ├── styles/global.css       (@font-face, CSS vars, body leading)
    ├── layouts/Base.astro      (<head>, fonts preload, meta/OG)
    ├── components/
    │   ├── Header.astro        (wordmark only, non-sticky)
    │   ├── Hero.astro
    │   ├── WhatItIs.astro
    │   ├── HowItWorks.astro
    │   ├── Scenarios.astro
    │   ├── Debrief.astro
    │   ├── WhoFor.astro
    │   ├── Pricing.astro
    │   ├── Notify.astro         (the email form)
    │   └── Footer.astro
    └── pages/index.astro       (composes all sections)
```

### Brand tokens → Tailwind config
```js
// tailwind.config.cjs
module.exports = {
  content: ['./src/**/*.{astro,html,js,ts}'],
  theme: {
    colors: {
      bg:        '#1E1F23',
      surface:   '#414143',
      'text-primary':   '#F0F0F0',
      'text-secondary': '#8A8A95',
      accent:    '#00E5A0',     // FILL ONLY — never text-*
      survived:  '#2ECC40',     // data viz only
      failed:    '#FF6B6B',     // data viz only
      destructive: '#E74C3C',
      warning:   '#F59E0B',
      'gauge-track': '#2A2B30',
      'paywall-error': '#C0392B',
    },
    extend: {
      fontFamily: {
        display: ['Frijole', 'serif'],          // weight 400 only, caps
        sans:    ['Inter', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        hero: ['clamp(40px,8vw,96px)', { lineHeight: '0.95' }],
        h2:   ['24px', { lineHeight: '1.2', fontWeight: '700' }],
        headline: ['18px', { lineHeight: '1.3', fontWeight: '600' }],
        body: ['16px', { lineHeight: '1.5' }],   // 1.5 leading on dark
        caption: ['13px', { lineHeight: '1.4' }],
        eyebrow: ['12px', { lineHeight: '1', letterSpacing: '1px' }],
      },
      borderColor: { hairline: 'rgba(255,255,255,0.08)' },
      ringColor:   { focus: '#00E5A0' },
    },
  },
};
```
**Guard rule (enforce in review):** `accent` may only appear as `bg-accent`, never `text-accent`. `survived`/`failed` only inside the Debrief mock.

`global.css` declares the `@font-face` blocks (self-hosted woff2), sets `body { background: #1E1F23; color: #F0F0F0; }`, the body `line-height: 1.5`. **`font-display`: `optional` for the Frijole face (with preload), `swap` for Inter.**

### Email form — two build options (decision in §8)
- **Hosted static-form provider (truly no backend):** point the `<form>` `action` at Formspree / Buttondown's hosted endpoint. Zero server code; works on any static host. **Recommended for speed.**
- **Self-hosted endpoint:** POST to a tiny `/subscribe` route on the existing FastAPI (`api.survivethetalk.com`) writing to the DB / Resend. More control, more code, needs CORS.

> ⚠️ **Resend Audiences is NOT backendless from a static page.** Resend's API requires a secret key that **cannot** sit in static client JS. "Use Resend from the static page" still needs a server-side hop (a Resend-hosted form, a serverless proxy, or the FastAPI `/subscribe` route). So the real choice is **hosted-form provider (zero backend) vs. small FastAPI `/subscribe` route** — Resend-direct-from-static is not actually an option.

---

## 6. Hosting & Deploy

### RECOMMENDATION: **Option 1 — serve the static site from the same VPS via a new Caddy block.**
For a solo dev already operating this exact VPS + Caddy + GoDaddy-DNS stack, Option 1 is strictly simpler and avoids Option 2's one real landmine — the apex-CNAME / nameserver question that would drag DNS back toward the Cloudflare-account mess Story 10.2 just escaped. The auto-renewing Let's Encrypt setup on `api.survivethetalk.com` already proves the pattern; the landing page is the same recipe with `file_server` instead of `reverse_proxy`. A static page adds ~zero load.

### Option 1 — same VPS (recommended) — exact steps

**A. DNS at GoDaddy** (apex must be A/AAAA — GoDaddy can't CNAME the zone apex). **Both A and AAAA are correct here:** verified 2026-06-23 (SSH) that the VPS has a real, bound global IPv6 (`2a01:4f8:1c18:fbfd::1/64`, `scope global`) and Caddy listens dual-stack on `*:80`/`*:443`, so the AAAA record is fully serviceable — keep it.
| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | `167.235.63.129` | 600 |
| AAAA | `@` | `2a01:4f8:1c18:fbfd::1` | 600 |
| CNAME | `www` | `survivethetalk.com` | 600 |
| TXT | `@` | `google-site-verification=…` (from Search Console) | 600 |

**B. VPS directory** (outside the atomic-release tree so a server deploy never wipes it). **Do NOT `chown www-data`** — verified 2026-06-23 (SSH) that Caddy runs as **`caddy:caddy`**. Root-owned, world-readable static files serve fine; for exact ownership, `chown caddy:caddy` **after** the rsync (the rsync runs as `root`, so files land root-owned otherwise):
```bash
ssh root@167.235.63.129 'mkdir -p /opt/landing/public'
```

**C. Build + push:**
```bash
# local, in landing/
npm run build           # → dist/
rsync -az --delete ./dist/ root@167.235.63.129:/opt/landing/public/
# optional, exact ownership for the caddy service user:
ssh root@167.235.63.129 'chown -R caddy:caddy /opt/landing'
```

**D. Caddy block** — append to `deploy/Caddyfile`. Includes security headers (net-new — the existing `api.` block sets none) and serves Privacy/Terms **from the apex** (L1) so the Google cross-check never leaves the domain. Fold `www` into the apex block via Caddy's host matching rather than a second site block, to **halve the cert surface**:
```caddy
survivethetalk.com, www.survivethetalk.com {
    # www → apex (single block, so only one cert host pair to issue)
    @www host www.survivethetalk.com
    redir @www https://survivethetalk.com{uri} permanent

    encode gzip zstd

    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options "nosniff"
    }

    # Keep Privacy/Terms on the apex domain for the verification cross-check.
    handle /legal/* {
        reverse_proxy localhost:8000
    }

    handle {
        root * /opt/landing/public
        file_server
    }
}
```
*(The existing `api.survivethetalk.com` and `http://167.235.63.129` blocks in `deploy/Caddyfile` are unchanged. Legal HTML is served by FastAPI at `/legal/privacy` and `/legal/terms` — confirmed live; the apex `handle /legal/*` proxies them so footer links read `https://survivethetalk.com/legal/...`.)*

**E. Apply (Caddy is NOT in CI — manual):**
```bash
# verify the live path first (confirmed 2026-06-23: /etc/caddy/Caddyfile)
ssh root@167.235.63.129 'systemctl cat caddy | grep -i Caddyfile'
scp deploy/Caddyfile root@167.235.63.129:/etc/caddy/Caddyfile
ssh root@167.235.63.129 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy'
```

**F. TLS (DNS-resolve gate before reload):** Caddy issues one cert covering **both** `survivethetalk.com` and `www.survivethetalk.com` via HTTP-01 on port 80 (already open). **Both names must resolve to the VPS BEFORE `systemctl reload caddy`** — if `www` does not yet resolve, the ACME challenge for `www` fails and Caddy logs errors on every reload until DNS lands. So: add A/AAAA `@` + CNAME `www` in step A, **wait for both `survivethetalk.com` and `www.survivethetalk.com` to resolve to the VPS** (`dig +short survivethetalk.com` / `dig +short www.survivethetalk.com`), THEN run step E. Cert auto-renews thereafter, same mechanism as `api.`.

**Caveats:** keep `/opt/landing` outside `/opt/survive-the-talk/releases` (atomic-release prune never touches it); confirm the live Caddyfile path before `scp` (it is `/etc/caddy/Caddyfile`).

### Option 2 — external static host (fallback)
Git-push CI, global CDN, host-managed TLS; VPS stays purely the API.
- **Netlify** — connect repo → auto-deploy on push; GoDaddy stays DNS host (no NS move). Apex A `75.2.60.5` + `www` CNAME `<site>.netlify.app`. TLS auto.
- **GitHub Pages** — push static files, enable Pages. Apex 4 A records `185.199.108–111.153` + `www` CNAME `<user>.github.io`. Free TLS via "Enforce HTTPS". Build via Actions.
- **Cloudflare Pages** — cleanest CI, but apex-CNAME wants nameservers moved to Cloudflare → re-opens the DNS-account fragility Story 10.2 escaped. **Avoid.**

**Why not lead with it:** new account + dashboard, the apex-CNAME friction, and more moving parts for one HTML page. Cons outweigh the CI convenience here.

---

## 7. Build Task List (zero → deployed → Google-verified)

**Scaffold & brand**
- [ ] `npm create astro@latest landing` (empty/minimal), add `@astrojs/tailwind`.
- [ ] Convert `Frijole-Regular.ttf` → woff2; copy Inter 400/500/600/700 + italic woff2 into `public/fonts/`; copy both `OFL.txt`.
- [ ] Write `global.css` (`@font-face`: Frijole `font-display: optional`, Inter `swap`; CSS vars; body bg/leading).
- [ ] Drop the brand palette + type scale into `tailwind.config.cjs` (§5).

**Build the page (one component per section, §4 copy verbatim)**
- [ ] `Base.astro` layout — `<head>`, **Frijole preload** (`<link rel="preload" as="font" type="font/woff2" crossorigin>`), meta description, OG image/title, `lang="en"`.
- [ ] Header (wordmark only, NON-sticky) → Hero → WhatItIs → HowItWorks → Scenarios → Debrief → WhoFor → Pricing → Notify → Footer.
- [ ] Hero call-screen mock (avatar + ticking timer + low patience bar) — text-first, omit on mobile.
- [ ] Debrief monospace report mock (the one bordered block).
- [ ] Notify form: real `<label>`, `id="notify"`, smooth-scroll target; wire `action` to chosen provider (§8); deadpan post-submit state.
- [ ] Smooth-scroll for Hero CTA → `#notify` (no sticky-bar CTA to wire).

**QA gates (the brand review)**
- [ ] Banned-copy lint: no `!`, no `?` in chrome, no praise/emoji/reassurance/tips/scarcity. **Manual hype-by-aside pass** (the lint won't catch "Yes, really."-style winks).
- [ ] **Taunt-budget check:** at most TWO author-voice taunt lines page-wide (currently §5 "Yours will be worse." + §7 "losing to the landlord."); confirm the footer sign-off stayed cut.
- [ ] Color lint: no `text-accent`; `survived`/`failed` only inside the Debrief mock.
- [ ] A2/B1 read-through: present tense, second person, no idioms.
- [ ] Accessibility: `<label>` present, focus-visible states, AA+ contrast (watch `--text-secondary` stakes lines), single-column mobile reflow, page legible with mocks off.
- [ ] Lighthouse pass (perf/a11y).

**Deploy (Option 1)**
- [ ] GoDaddy: add A `@` (`167.235.63.129`), AAAA `@` (`2a01:4f8:1c18:fbfd::1`), CNAME `www`.
- [ ] `ssh … 'mkdir -p /opt/landing/public'` (no `www-data` chown).
- [ ] `npm run build` → `rsync -az --delete ./dist/ root@…:/opt/landing/public/` → optional `chown -R caddy:caddy /opt/landing`.
- [ ] Append the single combined apex+www Caddy block (with `header` + `/legal/*` proxy) to `deploy/Caddyfile`.
- [ ] **Wait until BOTH `survivethetalk.com` and `www.survivethetalk.com` resolve to the VPS** (`dig +short`).
- [ ] Verify live Caddyfile path → `scp` → `caddy validate && systemctl reload caddy`.
- [ ] Hit `https://survivethetalk.com` and `https://www.survivethetalk.com` (cert auto-issues for both); confirm `/legal/privacy` + `/legal/terms` resolve on the apex.

**Google verification**
- [ ] Resolve the account/contact-email pre-flight (§2): confirm which Google account owns Play Console; decide if the org contact email moves off Gmail.
- [ ] In Play Console, "Website Verification Required" → Search Console, **logged in as the Play Console Google account**.
- [ ] Add a **Domain** property = `survivethetalk.com` (recommended) → add the `google-site-verification` **TXT at GoDaddy host `@`** → wait → click Verify. *(Fallback if DNS stalls: add a **URL-prefix** property `https://survivethetalk.com/` and verify via HTML-file upload / meta tag.)*
- [ ] Confirm Section 9 shows Kindopia + `contact@survivethetalk.com` + Privacy/Terms + product/pricing.
- [ ] Play Console → Account details → Organization website → **Send verification request**.
- [ ] Leave the verification record (TXT or HTML file) in place permanently.

**Commit**
- [ ] Commit the `landing/` project + the `deploy/Caddyfile` change (note Caddy is applied manually, not via CI).

---

## 8. Open Decisions for Walid

1. **Hosting** — confirm **Option 1 (same VPS / Caddy)** as recommended, or pick an external static host. (Recommendation: Option 1.)
2. **Email-capture provider** — the real choice is **hosted-form provider (Formspree / Buttondown — zero backend)** vs. a **small self-hosted `/subscribe` route on the existing FastAPI.** Note: "Resend Audiences from the static page" is NOT backendless (its API key can't live in client JS) — Resend still needs a server-side hop, which collapses it into one of those two options. Recommendation: hosted-form provider for launch speed; revisit FastAPI `/subscribe` if Walid wants the list in-house. Confirm or override.
3. **Kindopia about/contact line** — confirm the footer states `made by Kindopia` exactly as the legal name appears on D-U-N-S / FR registration / Google Payments (must match verbatim — the #1 org-verification failure is a name mismatch).
4. **Exact contact email** — confirm `contact@survivethetalk.com` (must be on-domain, non-free) and that the Resend MX/routing for it is live so the address actually receives mail. (Tied to the account/contact-email pre-flight in §2.)
5. **Hero & debrief visuals** — ship the text-first version first, or invest in the call-screen mock + debrief artifact now? (Plan assumes both, mobile omits the hero mock.)
6. **Taunt-budget sign-off** — the page is set to its 2-taunt cap (§5 "Yours will be worse." + §7 "losing to the landlord."); the draft footer line "We just started picking fights." is cut. Confirm the cut, or swap which two taunts survive.

---

**Files an engineer will touch:** new `landing/` project at repo root; `deploy/Caddyfile` (append the combined apex+www block, apply manually over SSH). Brand source of truth: `client/lib/core/theme/app_colors.dart` (+ `app_typography.dart`). Fonts: `client/assets/fonts/frijole/Frijole-Regular.ttf` (+ Inter). Legal HTML served live by FastAPI at `/legal/privacy` + `/legal/terms` (also on disk at `/opt/survive-the-talk/current/server/static/legal/`).

**Infra facts (live SSH-checked 2026-06-23):** AAAA `2a01:4f8:1c18:fbfd::1` is REAL and globally bound on the VPS — KEEP it. Caddy runs as `caddy:caddy`. Caddy binds dual-stack `*:80`/`*:443`. Live Caddyfile path is `/etc/caddy/Caddyfile`.
