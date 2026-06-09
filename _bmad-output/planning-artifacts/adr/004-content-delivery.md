# ADR 004 — Server-Driven Content Delivery (OTA Rive asset + scenario-served character data)

**Status:** Proposed
**Date:** 2026-06-09
**Deciders:** Winston (Architect), Walid (Project Lead)
**Related:** [[content-must-be-server-side]] (project memory); Story 7.2 (first slice — `end_phrases` server-side); `character_catalog.dart` "promotion to server-side" note; `architecture.md` §client-assets
**Supersedes:** the interim "generic shared animated body" idea floated 2026-06-09 (replaced by Option C below).

---

## Context

**Product rule (Walid 2026-06-09):** ALL user-facing content must be editable and expandable **server-side**, so changes and new scenarios reach users **without an app-store release**. Drivers: content is revised often (a user complaint → fix the wording immediately), and Walid intends to add scenarios **daily** (morning + afternoon). An app release per content change is untenable.

**Current state (what violates the rule):**

- Scenario LIST data (title, difficulty, language_focus, content_warning, …) is **already server-driven** (`GET /scenarios` → `Scenario.fromJson`). ✅
- **Hardcoded in the app** ❌: character display **names + roles** + avatar **JPGs** (`client/lib/features/scenarios/character_catalog.dart` `kCharacterCatalog`), scenario **taglines** (`kScenarioTaglines`), and the animated **puppet** `assets/rive/characters.riv` (one file, with a `character` ViewModel enum holding one **per-character animated variant** each — 1:1 with the catalog).

**The tension to resolve:** Walid wants to keep **per-character animated faces** (each character is visually distinct on screen during the call — a product feature) AND wants to **add characters without an app update**. But the `.riv` is **bundled** in the app, so today adding a character variant requires an app-store release. A "one generic shared face for everyone" approach would remove the app update but **downgrade** the existing distinct characters — rejected by Walid.

---

## Decision

Adopt a **two-channel** content-delivery model. **All character content is server-owned; the app is a renderer with an offline-safe local fallback.**

1. **Character DATA → scenario-served (DB + API).** Name, role/personality, voice id, end-phrases, taglines, briefings — authored server-side and delivered in the scenario/character payload the app already fetches. (Story 7.2 ships the first slice: `end_phrases`.)

2. **Animated puppet `characters.riv` → bundled baseline + Over-The-Air (OTA) update.** The app ships with a **local copy** of `characters.riv` (works on first launch and offline). The server **hosts the current `characters.riv` + a version marker**. On launch (silent, background), the app compares versions; if the server's is newer, it **downloads and caches** the new file, and the Rive runtime loads from the **cached file** thereafter. **Adding a character = Walid edits the single `.riv`, uploads it, bumps the version → every app pulls it. No app-store release.** Per-character faces are preserved (they live inside the one edited file).

3. **Avatar still photos → served + cached**, same offline-fallback principle (delivered alongside the OTA asset set or as per-character image URLs in the character data).

**Offline / failure rule:** the app always has a usable character set — last-cached if present, else the bundled baseline. A failed/absent update is never user-visible and never blocks a call.

---

## Options Considered

| Option | What | Verdict |
|---|---|---|
| **A — Status quo (all bundled)** | Keep names/avatars/`.riv` in the app. | ❌ Violates the rule — every content change is an app release. |
| **B — One generic shared animated face** | All characters share a single bundled animated body; per-character = name + voice + photo only. | ❌ Cheapest to add characters, but **downgrades the 5 existing distinct characters** on screen. Rejected by Walid. (A flat per-character *photo* on the rig can't lip-sync, so the animated face must be vector art in the rig — generic or not.) |
| **C — Per-character faces in ONE `.riv`, served OTA with bundled fallback** *(CHOSEN)* | Keep the single-file, per-character-variant `.riv`; serve it from the server with a local fallback + background update. Character text via scenarios. | ✅ Keeps per-character identity **and** removes the app-store dependency for new content. Matches Walid's existing edit-one-file workflow. |

---

## Rationale

- **Preserves the product feature** (distinct animated characters) that Option B would sacrifice.
- **Removes the app-store bottleneck** for the daily-content goal — the real driver of the whole rule.
- **Offline-robust:** the bundled baseline guarantees first-launch + no-connection always work; OTA is an enhancement, never a hard dependency.
- **Low authoring friction for Walid:** he keeps editing one Rive file (his current mental model), then uploads it.
- **Standard, proven pattern:** bundled-asset + OTA update is widely used; the Rive runtime supports loading from file/bytes (not only bundled assets), so the swap is mechanical.

---

## Consequences & Implementation Notes (future stories — recommendations, Walid to confirm)

This is a **multi-story** effort; the ADR records the target so the stories align. Recommended phasing (each its own story/commit):

1. **Character TEXT → server (small).** Move `kCharacterCatalog` name/role + `kScenarioTaglines` into the scenario/character data + API; the app reads them. (Story 7.2 already does `end_phrases`.)
2. **Avatar photos → served + cached (small–medium).** Per-character image URL in the character data (or in the OTA asset set), downloaded + cached, bundled fallback.
3. **`.riv` OTA mechanism (the real engineering).** A small **asset manifest** endpoint (recommended: `GET /assets/manifest` → `{ "characters_riv": { "version": …, "url": …, "sha256": … }, … }`), the `.riv` hosted as a **static file behind Caddy** on the VPS, and client logic: check-on-launch → conditional download → cache to local storage → verify hash → Rive loads from cache (else last-cache, else bundled). Update applies **next call**, never mid-call; the check is silent and non-blocking.

**Open technical sub-points (I recommend; tell me to change any):**
- **Update timing:** silent background check on app launch / scenario-list entry; new `.riv` takes effect on the next call. *(Recommend — avoids any mid-call swap.)*
- **Version signal:** an explicit `version` + `sha256` in a manifest (clear, verifiable, extensible to avatars/other assets) over bare HTTP ETag. *(Recommend.)*
- **Hosting:** static file via Caddy on the existing VPS (no new infra). *(Recommend.)*
- **Avatar photos:** ride in the same manifest/asset set as the `.riv` (one version check) **or** per-character URLs in the character data. *(Lean: per-character URLs — more granular, simpler to add one character's photo.)*

**Not in scope of this ADR:** the in-call latency/voice pipeline, auth, billing. This ADR is only about how character **content + visual assets** reach the app.

---

## Status note

Walid decided the core (Option C — OTA Rive with bundled fallback, character data via scenarios) on 2026-06-09. This ADR is **Proposed** pending his sign-off on the doc + the recommended sub-points above; on approval it flips to **Accepted** and seeds the phasing stories.
