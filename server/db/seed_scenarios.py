"""Idempotent YAML → scenarios-table seeder (ADR 001).

Invoked from `api/app.py`'s lifespan AFTER `run_migrations()`. Reads every
`.yaml` file under `server/pipeline/scenarios/` and upserts it into the DB.
On any parse error or missing required key, raises so FastAPI startup fails
loudly rather than booting with a half-seeded catalog.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from loguru import logger

from db.database import get_connection
from db.queries import upsert_scenario

_SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "pipeline" / "scenarios"


def _row_from_yaml(doc: dict) -> dict:
    """Map an authored YAML doc to the canonical column dict (ADR 001).

    Raises `ValueError` with a specific message on any shape violation so the
    caller can decorate it with the offending filename (see `seed_scenarios`).
    """
    if not isinstance(doc, dict) or "metadata" not in doc:
        raise ValueError("top-level `metadata:` mapping is missing")
    meta = doc["metadata"]

    # `is_free` must be a real bool — YAML nulls, empty strings, and zeros all
    # coerce to `else 0` (=paid), which would silently ship a scenario behind
    # the paywall. Require an explicit bool per ADR 001 is_free CHECK(0,1).
    if not isinstance(meta.get("is_free"), bool):
        raise ValueError(
            f"metadata.is_free must be a bool (true/false); got {meta.get('is_free')!r}"
        )

    # `language_focus` is authored as a comma-separated string per ADR 001 Q3.
    # If a future YAML switches to a native list (`[a, b, c]`), fail loudly
    # here rather than crashing with AttributeError inside `str.split`.
    lf_raw = meta.get("language_focus")
    if not isinstance(lf_raw, str):
        raise ValueError(
            f"metadata.language_focus must be a comma-separated string; "
            f"got {type(lf_raw).__name__}"
        )
    language_focus = [s.strip() for s in lf_raw.split(",") if s.strip()]

    # `checkpoints` must be a list of objects per ADR 001. `json.dumps` happily
    # serialises a dict or scalar, so the corruption would only surface at
    # response-render time as a generic 500. Validate the shape here.
    checkpoints = doc.get("checkpoints")
    if not isinstance(checkpoints, list) or not all(
        isinstance(cp, dict) for cp in checkpoints
    ):
        raise ValueError("`checkpoints` must be a list of objects (mapping nodes)")

    # Content-warning authors use YAML folded block scalars (`>`), which emit
    # a trailing `\n`. Strip it so the client never renders stray whitespace.
    content_warning = meta.get("content_warning")
    if isinstance(content_warning, str):
        content_warning = content_warning.strip() or None

    escalation = meta.get("escalation_thresholds")
    return {
        "id": meta["id"],
        "title": meta["title"],
        "difficulty": meta["difficulty"],
        "is_free": 1 if meta["is_free"] else 0,
        "rive_character": meta["rive_character"],
        "base_prompt": doc["base_prompt"],
        "checkpoints": json.dumps(checkpoints, ensure_ascii=False),
        "briefing": json.dumps(doc["briefing"], ensure_ascii=False),
        "exit_lines": json.dumps(doc["exit_lines"], ensure_ascii=False),
        "language_focus": json.dumps(language_focus, ensure_ascii=False),
        "content_warning": content_warning,
        "patience_start": meta.get("patience_start"),
        "fail_penalty": meta.get("fail_penalty"),
        "silence_penalty": meta.get("silence_penalty"),
        "recovery_bonus": meta.get("recovery_bonus"),
        "silence_prompt_seconds": meta.get("silence_prompt_seconds"),
        "silence_hangup_seconds": meta.get("silence_hangup_seconds"),
        "escalation_thresholds": (
            json.dumps(escalation, ensure_ascii=False)
            if escalation is not None
            else None
        ),
        "tts_voice_id": meta.get("tts_voice_id"),
        "tts_speed": meta.get("tts_speed"),
        "scoring_model": meta.get("scoring_model"),
    }


async def seed_scenarios() -> None:
    """Upsert every YAML under `server/pipeline/scenarios/` into the DB.

    Idempotent: re-running leaves row counts unchanged thanks to
    `INSERT … ON CONFLICT(id) DO UPDATE`. The whole batch is wrapped in a
    single `BEGIN IMMEDIATE … COMMIT` so a mid-file crash rolls back cleanly
    rather than leaving the catalog half-populated.

    Pre-flight check: if two YAMLs share the same `metadata.id`, the UPSERT
    would silently keep only the last one (alphabetical order). That is a
    bug-friendly footgun (copy-paste a YAML, forget to rename the id), so
    we detect collisions BEFORE any DB write and fail loudly with the
    offending file pair.
    """
    files = sorted(_SCENARIOS_DIR.glob("*.yaml"))
    if not files:
        raise RuntimeError(f"No scenario YAMLs found under {_SCENARIOS_DIR}")

    # Pass 1 — parse every file, collect rows, fail loudly on duplicates.
    # Each YAML is wrapped in a try/except so a parse/shape error names the
    # offending file instead of dumping a bare KeyError/ValueError traceback
    # (AC3: "the seeder logs the offender and raises").
    rows: list[tuple[str, dict]] = []
    seen_ids: dict[str, str] = {}  # id → file name that first declared it
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            row = _row_from_yaml(doc)
        except (yaml.YAMLError, KeyError, ValueError, TypeError) as exc:
            logger.error(f"seed_scenarios: failed to parse {path.name}: {exc}")
            raise RuntimeError(f"Invalid scenario YAML {path.name}: {exc}") from exc
        if row["id"] in seen_ids:
            raise RuntimeError(
                f"Duplicate scenario id {row['id']!r} found in "
                f"{path.name} (first seen in {seen_ids[row['id']]}). "
                "Each YAML must declare a unique metadata.id."
            )
        seen_ids[row["id"]] = path.name
        rows.append((path.name, row))

    # Pass 2 — atomic upsert batch. Log the failure BEFORE attempting rollback
    # so the original exception's traceback isn't masked if rollback itself
    # raises (e.g. connection already closed).
    async with get_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            for name, row in rows:
                await upsert_scenario(db, row)
                logger.info(f"Seeded scenario {row['id']!r} from {name}")
            await db.commit()
        except BaseException:
            logger.exception("seed_scenarios failed; rolling back")
            await db.rollback()
            raise
