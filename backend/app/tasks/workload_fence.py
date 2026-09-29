"""Commit-time fencing for Redis workload leases.

A Redis lease can expire while its holder still runs (e.g. during a Redis
outage longer than the TTL), and a successor can then take it. Expiry does
not stop the former holder, so each lease acquisition claims a new
generation in Postgres, and every session commit made under the lease checks
that generation inside the committing transaction.

The check takes a shared row lock (``FOR SHARE``) held until commit, and a
successor's claim updates that row, so the two serialize: a commit already in
flight either finishes before the takeover, or sees the newer generation and
is rejected. Commits outside any fenced block (API, scripts, bypassed leases)
are not checked.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading

from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from ..models.workload_fence import WorkloadFence


class LeaseLost(BaseException):
    """The workload lease was lost or superseded; this commit is rejected.

    A ``BaseException``, like ``asyncio.CancelledError``: task code is full of
    ``except Exception`` handlers that log and carry on, and a superseded
    holder must stop rather than keep writing (e.g. to Redis) until the next
    commit. Only the lease decorators catch it, to wait and retry.
    """


@dataclass(frozen=True)
class _Fence:
    key: str
    generation: int
    lost: threading.Event
    rejected: threading.Event = field(default_factory=threading.Event)


_ACTIVE_FENCES: ContextVar[tuple[_Fence, ...]] = ContextVar(
    "workload_fences", default=()
)


def _claim_generation(key: str) -> int:
    from ..database import SessionLocal

    with SessionLocal() as db:
        # One atomic upsert, so concurrent first claims for a key never race.
        # SQLite is the unit-test harness only.
        dialect = db.get_bind().dialect.name
        insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
        generation = db.execute(
            insert(WorkloadFence)
            .values(key=key, generation=1)
            .on_conflict_do_update(
                index_elements=[WorkloadFence.key],
                set_={"generation": WorkloadFence.generation + 1},
            )
            .returning(WorkloadFence.generation)
        ).scalar_one()
        db.commit()
    return generation


@contextmanager
def workload_fence(key: str, lost: threading.Event) -> Iterator[None]:
    """Fence every commit in this block to a fresh generation of ``key``.

    Call only while holding the lease for ``key``. ``lost`` is set by the
    lease renewer when the lease is lost; commits then fail fast. If any
    commit was rejected, ``LeaseLost`` is raised on exit even when the block
    swallowed it, so the owning task never reports success. A nested block
    for a key already fenced keeps the outer generation.
    """
    fences = _ACTIVE_FENCES.get()
    if any(fence.key == key for fence in fences):
        yield
        return
    fence = _Fence(key, _claim_generation(key), lost)
    token = _ACTIVE_FENCES.set(fences + (fence,))
    try:
        yield
    finally:
        _ACTIVE_FENCES.reset(token)
    if fence.rejected.is_set():
        raise LeaseLost(f"{key}: a commit was rejected after the lease was lost")


def check_workload_fences(session: Session) -> None:
    """Raise ``LeaseLost`` unless every active fence is still current."""
    for fence in _ACTIVE_FENCES.get():
        if fence.lost.is_set():
            reason = "lease lost during task"
        else:
            current = session.execute(
                select(WorkloadFence.generation)
                .where(WorkloadFence.key == fence.key)
                .with_for_update(read=True)
            ).scalar_one_or_none()
            if current == fence.generation:
                continue
            reason = f"generation {fence.generation} superseded by {current}"
        fence.rejected.set()
        raise LeaseLost(f"{fence.key}: {reason}")


event.listen(Session, "before_commit", check_workload_fences)
