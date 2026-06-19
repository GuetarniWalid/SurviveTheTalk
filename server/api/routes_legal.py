"""Public, UNAUTHENTICATED HTML routes for the legal pages (Story 10.1).

These are the ONLY browser-facing routes in the API and they DELIBERATELY
bypass the uniform `{data, meta}` / `{error}` JSON envelope that every other
endpoint uses: store review crawlers, the onboarding consent screen, and the
paywall open these URLs directly in an external browser and expect raw HTML, not
a JSON envelope. A future reviewer should NOT "fix" these into `ok(...)`.

They carry NO `AUTH_DEPENDENCY` (mirroring `routes_health` / `routes_auth`, the
other public routers) so they answer with a `200` + HTML even with no token —
do NOT copy the auth-gated routers here.

The HTML source lives under `server/static/legal/` so Caddy ALSO serves it
directly at `/static/legal/*.html` (belt-and-suspenders); these routes give it a
clean, store-friendly path (`/legal/privacy`, `/legal/terms`) plus an easy
pytest round-trip. Story 10.2 owns the eventual HTTPS public domain — 10.1 only
serves the content on the current host.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/legal", tags=["legal"])

# `server/static/legal/` — resolved from this file (api/routes_legal.py → api/ →
# server/ → static/legal/) via __file__ so it never depends on the process CWD,
# the same posture as `routes_health._read_git_sha`.
_LEGAL_DIR = Path(__file__).resolve().parent.parent / "static" / "legal"


def _read_page(filename: str) -> str:
    return (_LEGAL_DIR / filename).read_text(encoding="utf-8")


# Cached at import time — the HTML is immutable for the lifetime of a release
# (a deploy rsyncs fresh files and restarts the service). Re-reading per request
# would be wasted IO. A missing file raises here at import → the server fails
# LOUD at boot rather than 500-ing per request, and the file is committed.
_PRIVACY_HTML = _read_page("privacy.html")
_TERMS_HTML = _read_page("terms.html")


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    """Serve the Privacy Policy as raw HTML (public, no auth)."""
    return HTMLResponse(content=_PRIVACY_HTML)


@router.get("/terms", response_class=HTMLResponse)
async def terms_of_service() -> HTMLResponse:
    """Serve the Terms of Service as raw HTML (public, no auth)."""
    return HTMLResponse(content=_TERMS_HTML)
