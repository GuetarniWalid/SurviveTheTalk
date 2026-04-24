# Story {{epic_num}}.{{story_num}}: {{story_title}}

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a {{role}},
I want {{action}},
so that {{benefit}}.

## Acceptance Criteria

1. [Add acceptance criteria from epics/PRD]

## Tasks / Subtasks

- [ ] Task 1 (AC: #)
  - [ ] Subtask 1.1
- [ ] Task 2 (AC: #)
  - [ ] Subtask 2.1

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** Include this section for any story that touches a server endpoint, adds or changes a DB migration, or requires a VPS deployment. **Omit entirely for Flutter-client-only stories.**
>
> **Transition rule:** Every unchecked box below is a stop-ship for the `in-progress → review` transition. Paste the actual command run and its output as proof — a checked box without evidence does not count. Epic 3 and Epic 4 both hit this gap because the gate was an oral reminder; this section exists so it can't be forgotten.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line -->

- [ ] **Happy-path endpoint round-trip.** Production-like curl against `http://167.235.63.129` returns the expected `{data, meta}` envelope and HTTP status.
  - _Command:_ <!-- e.g. curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/scenarios -->
  - _Expected:_ <!-- 200 + abbreviated body shape -->
  - _Actual:_ <!-- paste output -->

- [ ] **Error / unauth path produces the `{error}` envelope.** At least one negative case returns the canonical error shape (not a raw 500 or FastAPI default).
  - _Command:_ <!-- paste -->
  - _Expected:_ <!-- e.g. 401 + {"error": "UNAUTHENTICATED", ...} -->
  - _Actual:_ <!-- paste output -->

- [ ] **DB side-effect verified (if the story writes rows or adds a migration).** Read back via `sqlite3` confirms the expected state. Mark N/A with one-line rationale if the story has zero DB impact.
  - _Command:_ <!-- e.g. sqlite3 app.db "SELECT version FROM schema_migrations;" -->
  - _Actual:_ <!-- paste rows -->

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 50 --since "5 min ago"` shows no ERROR or Traceback for the request(s) fired above.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

## Dev Notes

- Relevant architecture patterns and constraints
- Source tree components to touch
- Testing standards summary

### Project Structure Notes

- Alignment with unified project structure (paths, modules, naming)
- Detected conflicts or variances (with rationale)

### References

- Cite all technical details with source paths and sections, e.g. [Source: docs/<file>.md#Section]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
