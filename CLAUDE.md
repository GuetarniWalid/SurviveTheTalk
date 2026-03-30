# Claude Code Instructions for This Project

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
