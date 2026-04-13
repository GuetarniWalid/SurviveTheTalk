# Story 2.7: Create Visual Assets (App Icon, Splash Screen, Scenario Backgrounds)

Status: done

## Story

As a designer,
I want the app icon, splash screen, and scenario background images created,
So that the app has a complete visual identity for development and store submission.

## Acceptance Criteria

1. **Given** the app targets iOS and Android
   **When** the app icon is created
   **Then** it follows Apple Human Interface Guidelines and Google Play icon specs (1024x1024 source, adaptive icon for Android)
   **And** the icon reflects the adversarial entertainment positioning (edgy, not educational)

2. **Given** the app launches with a splash screen before the scenario list
   **When** the splash screen is designed
   **Then** it uses the dark theme background (`#1E1F23`) with minimal branding (logo/wordmark)

3. **Given** the call screen uses scenario-specific background images with gaussian blur
   **When** background images are created
   **Then** one background image exists per launch scenario (5 minimum), each setting the ambient mood for the scenario
   **And** images work well when blurred (~15-25px gaussian) — colors and shapes remain readable as atmosphere

## Tasks / Subtasks

- [x] Task 1: Create app icon (AC: #1)
  - [x] Design 1024x1024 source icon reflecting edgy/adversarial entertainment positioning
  - [x] Verify icon works at small sizes (29px, 40px, 60px, 76px, 83.5px, 1024px for iOS; 48dp, 72dp, 96dp for Android)
  - [x] Prepare adaptive icon layers for Android (foreground + background, 108x108dp safe zone = 72dp centered)
  - [x] Export all required sizes or prepare source for `flutter_launcher_icons` generation
- [x] Task 2: Create splash screen asset (AC: #2)
  - [x] Design splash screen with `#1E1F23` background and minimal branding element (logo or wordmark)
  - [x] Ensure branding element works on dark background and is centered
  - [x] Prepare source for `flutter_native_splash` generation or manual placement
- [x] Task 3: Create 5 scenario background images and 5 character avatars (AC: #3)
  - [x] Mugger scenario background — dark alley ambiance (`scenario_backgrounds/dark_alley.jpg`)
  - [x] Waiter scenario background — restaurant ambiance (`scenario_backgrounds/restaurant.jpg`)
  - [x] Girlfriend scenario background — home/apartment ambiance (`scenario_backgrounds/apartment_night.jpg`)
  - [x] Cop scenario background — street/police car ambiance (`scenario_backgrounds/street_police.jpg`)
  - [x] Landlord scenario background — apartment hallway ambiance (`scenario_backgrounds/building_hallway.jpg`)
  - [x] 5 character avatar images created (`characters/{mugger,waiter,girlfriend,cop,landlord}.jpg`)
  - [x] Validate all backgrounds work well with ~15-25px gaussian blur (colors/shapes remain readable as mood)
- [x] Task 4: Add assets to Flutter project
  - [x] Place assets in `client/assets/images/` (scenario_backgrounds/, characters/, icon/, splash/)
  - [x] Declare new asset paths in `client/pubspec.yaml` under `flutter.assets`
  - [x] Run `flutter analyze` and `flutter test` to verify no regressions

## Dev Notes

### Story Type: Asset Creation + Minimal Flutter Configuration

This is primarily a **design/creative task** (like Stories 2.1-2.6). The main work is creating visual assets outside the IDE. The only code change is adding asset declarations to `pubspec.yaml`.

### Visual Identity Context

**Design direction:** "Dark Contact List" — Monochrome Minimalism with Character-Driven Color.

- App background: `#1E1F23` (dark charcoal, warm undertone — NOT pure black)
- Brand accent: `#00E5A0` (toxic mint green)
- Text: `#F0F0F0` (near-white)
- Destructive: `#E74C3C`
- Visual tone: edgy, minimalist, adult animation aesthetic (Rick & Morty / South Park energy, 100% original designs)
- The Rive character is the only visually rich element — UI stays invisible

### App Icon Design Direction

- Must communicate "adversarial entertainment" — edgy, not educational
- Should NOT look like a language learning app (no books, no ABC, no flags)
- Should evoke the phone call / confrontation / survival concept
- Must work at all sizes from 29px to 1024px (simple shapes, high contrast)
- Avoid fine detail that disappears at small sizes
- Consider using the toxic mint accent `#00E5A0` on dark `#1E1F23` background for brand recognition
- Android adaptive icon: foreground layer must work on any background shape (circle, squircle, rounded square)

### Splash Screen Design Direction

- Background: solid `#1E1F23`
- Branding element: minimal — logo mark or wordmark, NOT a full illustration
- Element should be centered both horizontally and vertically
- No loading indicator, no animation — just brand presence during app cold start
- NFR6 specifies cold start to scenario list <3s target, so splash is brief

### Scenario Background Images

These backgrounds appear on the call screen behind the Rive character canvas. They are blurred with `BackdropFilter` gaussian blur (~15-25px). The blur means:

- **DO** use strong ambient colors and shapes that create mood when blurred
- **DO** create distinct color palettes per scenario so each call feels different
- **DO NOT** rely on fine detail — everything >15px gets blurred away
- **DO NOT** include text or small icons — they become unreadable

**Recommended approach:** Abstract or semi-realistic atmospheric images with dominant color zones. Think "out-of-focus photography" — the mood is the content, not the detail.

| Scenario | Character | Ambient Mood | Suggested Color Palette |
|----------|-----------|-------------|------------------------|
| Mugger | The Mugger | Dark alley, nighttime, urban danger | Deep blues, dark grays, faint streetlight yellows |
| Waiter | Sarcastic Waiter | Restaurant interior, warm lighting | Warm amber/browns, soft candlelight glow |
| Girlfriend | Furious Girlfriend | Home/apartment, intimate tension | Warm indoor lighting, muted oranges/browns |
| Cop | Suspicious Cop | Street/police car, authority pressure | Blue/red police light tones, dark asphalt grays |
| Landlord | Angry Landlord | Apartment hallway, confrontation | Fluorescent lighting, pale yellows, worn building tones |

**Resolution:** Images should be at least 1080x1920 (portrait, full HD) for crisp display on modern phones. Since they are blurred, file size should stay reasonable — JPEG quality 80-85% is fine (blur hides compression artifacts).

### Asset File Organization

```
client/assets/
├── rive/
│   └── character.riv          # Already exists (Story 2.6, 57KB)
├── images/
│   ├── icon/
│   │   ├── app_icon.png       # 1024x1024 source icon
│   │   └── app_icon_foreground.png  # Android adaptive foreground layer
│   ├── splash/
│   │   └── splash_logo.png    # Branding element for splash screen
│   ├── scenario_backgrounds/
│   │   ├── dark_alley.jpg     # Mugger scenario background (~15-25px blur target)
│   │   ├── restaurant.jpg     # Waiter scenario background
│   │   ├── apartment_night.jpg # Girlfriend scenario background
│   │   ├── street_police.jpg  # Cop scenario background
│   │   └── building_hallway.jpg # Landlord scenario background
│   └── characters/
│       ├── mugger.jpg         # Character avatar 512x512
│       ├── waiter.jpg
│       ├── girlfriend.jpg
│       ├── cop.jpg
│       └── landlord.jpg
```

### pubspec.yaml Changes

Add the following under `flutter.assets` (alongside existing `assets/rive/character.riv`):

```yaml
assets:
  - assets/rive/character.riv
  - assets/images/icon/
  - assets/images/splash/
  - assets/images/scenario_backgrounds/
  - assets/images/characters/
```

Using directory-level declarations loads all files in each directory.

### What NOT to Do

1. **Do NOT write Flutter/Dart code** beyond `pubspec.yaml` asset declarations — icon generation, splash screen integration, and background loading are Epic 4+ scope
2. **Do NOT use `flutter_launcher_icons` or `flutter_native_splash` packages yet** — just prepare the source files; package integration happens when the app structure is built (Epic 4)
3. ~~Do NOT create character avatar images~~ — **Overridden**: 5 character avatar images (512x512 JPG) were added to fill the gap identified in Story 2.2 (incoming call screen and scenario cards require static avatars, not Rive renders)
4. **Do NOT include text in background images** — they get blurred beyond readability
5. **Do NOT copy third-party art or photography** — all assets must be original or properly licensed
6. **Do NOT make the app icon look educational** — this is adversarial entertainment, not a learning app
7. **Do NOT add icon/splash generation config files yet** (e.g., `flutter_launcher_icons.yaml`) — that's implementation scope
8. **Do NOT create background images larger than necessary** — they're blurred, so >1080x1920 is wasteful

### Pre-Commit Validation

Since this story creates binary assets and only modifies `pubspec.yaml`:

```bash
cd client && flutter analyze   # Must pass — validates pubspec.yaml syntax
cd client && flutter test       # Must pass — ensures no regressions
```

No Python checks needed (server code untouched).

### Project Structure Notes

- Asset directory `client/assets/` already exists with `rive/character.riv`
- New directories (`images/icon/`, `images/splash/`, `images/scenario_backgrounds/`, `images/characters/`) must be created
- Follows the architecture's asset organization pattern: assets grouped by type under `client/assets/`
- Background images will be consumed by `CallScreenCanvas` widget (Epic 6, Story 6.2) using `BackdropFilter`
- Icon source will be consumed by `flutter_launcher_icons` package (Epic 10, Story 10.3)
- Android adaptive icon: foreground layer provided (`app_icon_foreground.png`, contains mouth + swirl), background will use solid color `#120F0F` in `flutter_launcher_icons` config (Story 10.3)
- Splash source will be consumed by `flutter_native_splash` package (Epic 4, Story 4.1)

### Previous Story Intelligence (Story 2.6)

- **Story type pattern confirmed:** Epic 2 stories are design/asset creation, NOT coding tasks
- **Validation pattern:** Story 2.6 validated its `.riv` asset with a temporary checker — consider visual validation of backgrounds by viewing them with blur applied
- **File size awareness:** Story 2.6 delivered 57KB `.riv` file — keep background images reasonable (target <500KB each after JPEG compression)
- **pubspec.yaml already declares** `assets/rive/character.riv` — extend the assets list, don't replace it

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Epic 2, Story 2.7]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — Color System, Visual Design Direction, Call Screen specs]
- [Source: _bmad-output/planning-artifacts/architecture.md — Flutter asset structure, static asset serving]
- [Source: _bmad-output/planning-artifacts/prd.md — UX-DR6 CallScreenCanvas, NFR6 cold start]
- [Source: _bmad-output/implementation-artifacts/2-6-create-rive-character-puppet-file.md — Previous story learnings]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

- Fixed `dark_alley.jpg .jpg` filename (extra space + double extension) — renamed to `dark_alley.jpg`

### Completion Notes List

- Walid created all visual assets manually using Midjourney (adult cartoon style)
- Scope expanded from original story: added 5 character avatar images (JPG 512x512) for incoming call screen and scenario cards — addresses gap between Story 2.2 design (static avatar needed) and original Story 2.7 spec (which said "do not create character avatars")
- Renamed background images from character names to scene names for clarity (e.g., `mugger.jpg` → `dark_alley.jpg`) — these paths will be referenced by scenario JSON files (Epic 3)
- Changed background directory from `backgrounds/` to `scenario_backgrounds/` to distinguish from potential future UI backgrounds
- Background resolution reduced from 1080x1920 to 720x1280 — blur makes higher resolution imperceptible
- Updated `pubspec.yaml` with directory-level asset declarations for all 4 new image directories
- `flutter analyze` — No issues found
- `flutter test` — All 3 tests passed

### File List

- `client/assets/images/icon/app_icon.png` (NEW — 1024x1024 app icon source)
- `client/assets/images/icon/app_icon_foreground.png` (NEW — Android adaptive icon foreground, transparent bg)
- `client/assets/images/splash/splash_logo.png` (NEW — splash screen branding element, transparent bg)
- `client/assets/images/scenario_backgrounds/dark_alley.jpg` (NEW — Mugger scenario background)
- `client/assets/images/scenario_backgrounds/restaurant.jpg` (NEW — Waiter scenario background)
- `client/assets/images/scenario_backgrounds/apartment_night.jpg` (NEW — Girlfriend scenario background)
- `client/assets/images/scenario_backgrounds/street_police.jpg` (NEW — Cop scenario background)
- `client/assets/images/scenario_backgrounds/building_hallway.jpg` (NEW — Landlord scenario background)
- `client/assets/images/characters/mugger.jpg` (NEW — Mugger character avatar 512x512)
- `client/assets/images/characters/waiter.jpg` (NEW — Waiter character avatar 512x512)
- `client/assets/images/characters/girlfriend.jpg` (NEW — Girlfriend character avatar 512x512)
- `client/assets/images/characters/cop.jpg` (NEW — Cop character avatar 512x512)
- `client/assets/images/characters/landlord.jpg` (NEW — Landlord character avatar 512x512)
- `client/pubspec.yaml` (MODIFIED — added 4 asset directory declarations)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (MODIFIED — story status: review)
- `_bmad-output/implementation-artifacts/2-7-create-visual-assets.md` (MODIFIED — this story file)

### Change Log

- 2026-04-13: Created all visual assets (app icon, splash logo, 5 scenario backgrounds, 5 character avatars). Added asset declarations to pubspec.yaml. All Flutter checks pass. Story marked for review.
- 2026-04-13: Code review corrections applied:
  - Re-compressed 5 scenario backgrounds from ~5MB total to ~720KB (JPEG quality 75) — all now under 200KB, well within <500KB target
  - Normalized `street_police.jpg` (720x1282→720x1280) and `building_hallway.jpg` (720x1269→720x1280) to consistent 720x1280
  - Updated stale `backgrounds/` paths to `scenario_backgrounds/` in story doc (3 occurrences)
  - Amended "What NOT to Do" #3 to reflect accepted scope expansion (character avatars)
  - Documented adaptive icon background decision: solid color `#120F0F` for Story 10.3 (foreground layer contains mouth + swirl)
  - Accepted `street_police.jpg` police tape text as scene ambiance (blur renders it quasi-unreadable)
  - `flutter analyze` — No issues found; `flutter test` — All 3 tests passed
