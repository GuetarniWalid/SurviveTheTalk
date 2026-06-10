# Claude Code Instructions for This Project

## Command-Line Execution — the agent runs it, Walid is the last resort

**RULE (Walid 2026-06-03): command lines are the AGENT's job by default — never punt them to Walid.** Whenever a task needs a terminal command and the agent is capable of running it, the **agent runs it first** and reports the result: `pytest`, `ruff`, `flutter analyze` / `flutter test`, builds, `git`, VPS `ssh` / `systemctl` / `journalctl`, scripts, etc. Walid running a command himself is the **last resort**, reserved only for what the agent genuinely cannot do:

- on-device tests (Pixel 9 smoke gates),
- anything needing a secret/credential the agent does not hold (e.g. live API keys),
- interactive auth the agent cannot complete.

Do **not** pre-emptively hand a runnable command to Walid "to be safe." If you can run it, run it. Only escalate to Walid **after** you have actually tried and hit a real wall — and state exactly what the wall was.

This explicitly retires the old habit of deferring the full server `pytest` to Walid: that was based on a stale "sandbox livekit import hang" note. The full suite runs fine in-sandbox once warmed (**574 passed, verified 2026-06-03**); see `memory/feedback_sandbox_livekit_import_hang.md` (cold-start Defender-scan quirk only — warm once with `import aiohttp`, then run).

## Voice Smoke Tests — always hand Walid a ready-to-play script

**RULE (Walid 2026-06-04): whenever a change needs Walid to run a voice test himself (Pixel 9 smoke gate, on-device call, any live mic test), you MUST proactively hand him a ready-to-play script BEFORE he calls — never make him improvise or think up what to say.** Walid wants to just read lines and watch, not design the test. Every single time, provide:

1. **Which scenario to open** (exact name as it appears in the app).
2. **The exact lines to say, turn by turn, in order** — verbatim phrases he reads aloud, each one engineered to exercise the specific behaviour under test (e.g. to validate a given checkpoint, or to trigger the exact edge case the change is about — out-of-order crediting, a hang-up, a redirect, etc.).
3. **The approximate response to expect** after each line (the gist of what the character should say) **+ what to watch on the HUD** (which checkpoint should tick, whether the on-screen step moves or holds). Say plainly that responses are approximate — it is a live LLM, not 100% deterministic; the goal is a no-think replay, not an exact prediction.

Call out the **"money" moment** explicitly — the one turn where the behaviour the change is about actually happens — so Walid knows exactly what to look for. Keep it copy-pasteable and minimal. This applies on top of the smoke-gate analysis-mode rule (`memory/feedback_smoke_gate_analysis_mode.md`): hand the script first, then stay silent during the call and compile one report at the end.

## Git Commit Messages

**IMPORTANT**: Do NOT add "Co-Authored-By" lines to any commits in this project.

All commits should be authored solely by the project owner without co-author attribution.

### Commit Message Format

Use a **list format** for readability:

```
feat: short summary of the story/change

- Add component X with feature Y
- Add widget Z with specific behavior
- Integrate service A into module B
- Add N new tests (total passing)
```

Rules:
- First line: `feat:`/`fix:`/`style:`/`refactor:` prefix, lowercase English, < 72 chars
- Body: bulleted list (`- `), each line describes one logical change
- Each bullet starts with a verb: Add, Fix, Integrate, Replace, Remove, Update, Migrate
- Keep bullets concise (one line each)
- Last bullet mentions test count if tests were added/changed

### Commit Cadence — one commit per story STAGE (not per story)

**RULE (Walid 2026-06-09): commit at EVERY stage of a story's lifecycle, each as its own normal commit.**

- **create-story** → commit (the story spec + the `sprint-status.yaml` flip to `ready-for-dev`).
- **dev-story** → commit (the implementation + the flip to `review`/`in-progress`).
- **code-review** → commit (the review fixes + the flip).
- Any further validated follow-up → its own commit.

**This REVERSES the old "one story = one commit; amend follow-up fixes back in" rule.** Do **NOT** `git commit --amend`, `git reset --soft HEAD~1`, squash, or `git push --force*` to fold a story's stages into a single commit. It is simpler — and it stops stories from **overwriting each other** (amend/force-push on a shared `main` risks clobbering another story's work and tangling history). A clean commit per stage keeps each step independently recorded and recoverable. The commit FORMAT and pre-commit gates above still apply to every commit.

## Pre-Commit Validation

**CRITICAL RULE**: Before EVERY commit, you MUST run validation checks.

### Flutter (in `client/`)

```bash
cd client && flutter analyze
```

**MUST return "No issues found!"** - fix ALL issues including infos.

- CI/CD fails on ANY flutter analyze issue (errors, warnings, OR infos)
- Even info-level lints must be fixed or explicitly disabled in analysis_options.yaml
- Never assume infos are acceptable - they block the build

```bash
cd client && flutter test
```

**MUST show "All tests passed!"** - fix ALL failing tests.

- Run `flutter test` (without arguments) to run ALL tests, not just new ones
- After modifying core components (App, services, blocs), old tests may break
- Don't assume only new tests need to pass - verify everything

### Python (in `server/`)

```bash
cd server && ruff check .
cd server && ruff format --check .
cd server && pytest
```

All three must pass with zero issues.

### Commit only if ALL checks pass

**The rule**: Only commit if all applicable checks pass completely.

## Sprint-Status — `review → done` Flip Discipline

**RULE (Walid 2026-06-10 — SUPERSEDES the 2026-06-04 wording): `done` requires BOTH the formal code review AND the Pixel 9 smoke gate. NEVER flip a story from dev to `done` directly — a smoke-gate sign-off alone does NOT flip `done` if the code review has not run.** (The 2026-06-10 trigger: Story 6.27 was flipped `done` on the smoke gate with the code review skipped — wrong; it was reverted to `review`.)

The mandatory story lifecycle, every time, no shortcuts:

1. **dev-story complete** → flip the status to `review` (story file + `sprint-status.yaml`) → **commit**.
2. **The reviewer runs the formal code review** (`/bmad-code-review`).
3. **Only when ALL of these hold** — review findings resolved, automated gates green, AND the Pixel 9 smoke gate validated (or explicitly waived by Walid) — **the REVIEWER flips `review → done`** (both places) → **commit**.

Whichever gate clears LAST triggers the flip — the order between code review and smoke gate is free, but BOTH are required:

- **At the END of every code review**, if the smoke gate is still owed, the story STAYS `review` — and the review summary MUST end with an explicit, one-line callout: *"Story X is review-complete; it is now waiting ONLY on your Pixel 9 smoke gate for the `review → done` flip."* Never finish a review silently leaving the status ambiguous.
- **When Walid validates the smoke gate** ("it passed / looks good / ship it / passe-la en done"): record the sign-off in the story's gate boxes immediately. If the code review is ALSO already complete, flip `review → done` in the SAME turn, in BOTH places (`sprint-status.yaml` + the story file `Status:`). If the code review has NOT run yet, the story stays `review` and the next step is to run it — say so explicitly.

**Anti-rot half (kept from 2026-06-04):** a story with BOTH gates cleared must never rot in `review` — the flip is mandatory and immediate the instant the second gate clears. And never re-propose a story whose two gates are already cleared as a review target; that is a bookkeeping bug, not a pending review. A story in `review` with the smoke gate signed but NO code review yet IS a legitimate pending review target.

## Database Migrations — Test Against Production Shape

**CRITICAL RULE**: A test that passes on an empty DB says nothing about production. Any new file under `server/db/migrations/` must keep `tests/test_migrations.py` green — that test replays migrations against `tests/fixtures/prod_snapshot.sqlite` (a sanitised copy of the live VPS DB) and asserts no FK / CHECK / integrity violations. This is the active enforcement layer; `pytest` will fail if you ship a migration that crashes against the real prod shape.

If your migration introduces a new table, new constraint, or a structural change you want represented in the snapshot:

```bash
cd server && python scripts/refresh_prod_snapshot.py
```

Then commit the refreshed `tests/fixtures/prod_snapshot.sqlite` alongside your migration. The script SSHs to the VPS, pulls the live DB, scrubs PII (emails → `user-{id}@example.invalid`, jwt_hash → NULL, auth_codes → deleted), and writes the result.

Why this matters: Story 5.1 shipped a tier-rename migration that crashed on first deploy because the local test DB was empty (no FK-referencing rows to violate). Snapshot-based testing makes that class of bug impossible to ship — local pytest replays the migration against the real prod shape on every run.
