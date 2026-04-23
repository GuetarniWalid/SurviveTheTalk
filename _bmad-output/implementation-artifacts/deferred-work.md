# Deferred Work

Items flagged during code review but postponed — each entry records where the review surfaced it and why it was not actioned at the time.

## Deferred from: code review of story 4-5-build-first-call-incoming-call-experience (2026-04-23)

- **Bot subprocess never reaped** — `server/api/routes_calls.py:63-76` fires `subprocess.Popen` and never tracks it. Real lifecycle (terminate on call-end, zombie cleanup) belongs to Epic 6.4 / 7.1 via `POST /calls/{id}/end`.
- **`CallPlaceholderScreen` has no LiveKit timeout / reconnect / disconnect-event handler** — `call_placeholder_screen.dart:34-60` silently hangs on "Connecting to Tina…" if the room never comes up. Spec scopes real call UX (including error recovery) to Epic 6.2 Story 6.2.
- **Mic permission revoked between onboarding and `/call` not user-guided** — `call_placeholder_screen.dart:44-58` catches the failure and shows a generic "Couldn't connect" without offering a path back to settings. Epic 6.2 owns the real mic-error UX.
- **No rate-limit / per-user in-flight guard on `/calls/initiate`** — `routes_calls.py:33-101` allows unbounded subprocess spawns per user. Post-MVP infrastructure concern (middleware / Redis / idempotency key).
- **Migration `002_calls.sql` has no explicit `ON DELETE` policy on `user_id` FK** — defaults to `NO ACTION`, which blocks user deletion when call rows exist. Intentional (preserves audit trail) but undocumented; re-visit when user deletion / GDPR erasure lands.
