"""Shared/exclusive write fence for Economic Taxonomy producers and publishers.

Lock order is deliberately centralized here:

``writer fence -> authority row -> producer locks -> domain rows -> outbox``.

Provider calls and other slow external work must happen before entering either
context manager.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from threading import Condition

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.economic_taxonomy.contracts import AuthorityMode
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.models.economic_taxonomy_runtime import TaxonomyAuthority

ECONOMIC_TAXONOMY_FENCE_KEY = 78_124_017


class TaxonomyWriteRejected(RuntimeError):
    code = "taxonomy_write_rejected"


class StaleAuthorityEpoch(TaxonomyWriteRejected):
    code = "stale_authority_epoch"


class AuthorityModeRejected(TaxonomyWriteRejected):
    code = "authority_mode_rejected"


class AuthorityWritesFenced(TaxonomyWriteRejected):
    code = "authority_writes_fenced"


class _ProcessReadWriteLock:
    def __init__(self):
        self._condition = Condition()
        self._readers = 0
        self._writer = False

    def acquire_shared(self):
        with self._condition:
            while self._writer:
                self._condition.wait()
            self._readers += 1

    def release_shared(self):
        with self._condition:
            self._readers -= 1
            if self._readers == 0:
                self._condition.notify_all()

    def acquire_exclusive(self):
        with self._condition:
            while self._writer or self._readers:
                self._condition.wait()
            self._writer = True

    def release_exclusive(self):
        with self._condition:
            self._writer = False
            self._condition.notify_all()


_SQLITE_FENCE = _ProcessReadWriteLock()


def _mode_value(mode: AuthorityMode | str) -> str:
    return mode.value if isinstance(mode, AuthorityMode) else str(mode)


def assert_write_allowed(
    authority: TaxonomyAuthority,
    *,
    expected_epoch: int,
    allowed_modes: Iterable[AuthorityMode | str],
) -> None:
    if authority.authority_epoch != expected_epoch:
        raise StaleAuthorityEpoch("stale_authority_epoch")
    if authority.writes_fenced:
        raise AuthorityWritesFenced("authority_writes_fenced")
    allowed = {_mode_value(mode) for mode in allowed_modes}
    if authority.mode not in allowed:
        raise AuthorityModeRejected("authority_mode_rejected")


@contextmanager
def producer_write(
    session: Session,
    *,
    expected_epoch: int,
    allowed_modes: set[AuthorityMode | str],
) -> Iterator[TaxonomyAuthority]:
    """Enter the mandatory shared pre-commit fence for a producer."""

    dialect = session.get_bind().dialect.name
    sqlite_acquired = False
    if dialect == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock_shared(:key)"),
            {"key": ECONOMIC_TAXONOMY_FENCE_KEY},
        )
    else:
        _SQLITE_FENCE.acquire_shared()
        sqlite_acquired = True
    try:
        authority = EconomicTaxonomyPublicationRepository(session).lock_authority()
        assert_write_allowed(
            authority,
            expected_epoch=expected_epoch,
            allowed_modes=allowed_modes,
        )
        yield authority
    finally:
        if sqlite_acquired:
            _SQLITE_FENCE.release_shared()


@contextmanager
def exclusive_publication(session: Session) -> Iterator[TaxonomyAuthority]:
    """Drain shared writers, then lock the singleton authority row."""

    dialect = session.get_bind().dialect.name
    sqlite_acquired = False
    if dialect == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": ECONOMIC_TAXONOMY_FENCE_KEY},
        )
    else:
        _SQLITE_FENCE.acquire_exclusive()
        sqlite_acquired = True
    try:
        yield EconomicTaxonomyPublicationRepository(session).lock_authority()
    finally:
        if sqlite_acquired:
            _SQLITE_FENCE.release_exclusive()

