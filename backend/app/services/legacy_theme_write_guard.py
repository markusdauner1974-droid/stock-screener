"""Keep unfenced legacy Theme writers out of economic authority (#472).

Fenced legacy writers go through ``legacy_producer_write``, which admits only
``LEGACY_WRITE_MODES``. The writers that bypass that fence use the same mode set
here, so in economic authority they skip (tasks), return 409 (APIs) or refuse
(CLIs) instead of changing legacy tables with no source revision.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from functools import wraps

from sqlalchemy.orm import Session

from app.models.economic_taxonomy_runtime import TaxonomyAuthority

logger = logging.getLogger(__name__)

LEGACY_WRITE_MODES = frozenset({"legacy", "shadow", "dual"})
ECONOMIC_AUTHORITY_SKIP_REASON = "economic_authority"


class LegacyThemeWritesBlocked(RuntimeError):
    """Legacy Theme tables are read-only while economic authority serves."""


def legacy_theme_writes_blocked(db: Session) -> bool:
    authority = db.get(TaxonomyAuthority, 1)
    return authority is not None and authority.mode not in LEGACY_WRITE_MODES


def economic_authority_skip_payload() -> dict[str, object]:
    return {
        "status": "skipped",
        "reason": ECONOMIC_AUTHORITY_SKIP_REASON,
        "message": "Legacy Theme writes are disabled under economic authority.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def skip_in_economic_authority(task):
    """Task decorator: return a skip result before the body runs in economic mode.

    Place it below ``@celery_app.task``. Works for bound tasks (``self`` passes
    through unchanged).
    """

    @wraps(task)
    def wrapper(*args, **kwargs):
        from app.database import SessionLocal

        with SessionLocal() as db:
            blocked = legacy_theme_writes_blocked(db)
        if blocked:
            logger.info("Skipping %s: %s", task.__name__, ECONOMIC_AUTHORITY_SKIP_REASON)
            return economic_authority_skip_payload()
        return task(*args, **kwargs)

    return wrapper


def ensure_legacy_theme_writes_allowed(db: Session, *, force: bool = False) -> None:
    """For operator CLIs: refuse in economic authority unless explicitly forced."""
    if force or not legacy_theme_writes_blocked(db):
        return
    raise LegacyThemeWritesBlocked(
        "Legacy Theme writes are disabled under economic authority; "
        "rerun with --force-legacy-writes only if you intend to change legacy tables."
    )


def exit_if_legacy_theme_writes_blocked(db: Session, *, force: bool = False) -> None:
    """CLI form of ``ensure_legacy_theme_writes_allowed``: print STOP and exit 1."""
    try:
        ensure_legacy_theme_writes_allowed(db, force=force)
    except LegacyThemeWritesBlocked as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


FORCE_LEGACY_WRITES_HELP = "Write legacy Theme tables even under economic authority (#472)."
