"""Workload fencing under real PostgreSQL row locks and concurrent sessions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextvars
from datetime import date
import threading

import pytest

from app.database import SessionLocal, engine
from app.models.market_breadth import MarketBreadth
from app.tasks.workload_fence import (
    LeaseLost,
    _claim_generation,
    check_workload_fences,
    workload_fence,
)

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="requires PostgreSQL row locks"
)

KEY = "market_workload:us"


def _breadth_row() -> MarketBreadth:
    return MarketBreadth(market="US", date=date(2026, 9, 25), total_stocks_scanned=1)


def _successor_claim(pool: ThreadPoolExecutor):
    # A successor runs in another worker: fresh context, own connection.
    return pool.submit(contextvars.Context().run, _claim_generation, KEY)


def _breadth_rows() -> int:
    with SessionLocal() as db:
        return db.query(MarketBreadth).count()


def test_write_in_flight_at_takeover_cannot_commit_afterwards():
    with ThreadPoolExecutor(1) as pool, pytest.raises(LeaseLost):
        with workload_fence(KEY, threading.Event()):
            with SessionLocal() as db:
                db.add(_breadth_row())
                db.flush()  # the write is already in the old holder's transaction
                assert _successor_claim(pool).result(timeout=5) == 2
                with pytest.raises(LeaseLost, match="superseded"):
                    db.commit()
                db.rollback()
    assert _breadth_rows() == 0


def test_successor_claim_waits_for_a_commit_already_past_the_fence_check():
    with ThreadPoolExecutor(1) as pool:
        with workload_fence(KEY, threading.Event()):
            with SessionLocal() as db:
                db.add(_breadth_row())
                db.flush()
                check_workload_fences(db)  # commit in progress holds FOR SHARE
                claim = _successor_claim(pool)
                with pytest.raises(TimeoutError):
                    claim.result(timeout=0.5)
                db.commit()  # the old holder's commit lands before the takeover
        assert claim.result(timeout=5) == 2
    assert _breadth_rows() == 1


def test_concurrent_first_claims_for_a_new_key_both_succeed():
    barrier = threading.Barrier(2)

    def claim():
        barrier.wait()
        return _claim_generation(KEY)

    with ThreadPoolExecutor(2) as pool:
        claims = [pool.submit(contextvars.Context().run, claim) for _ in range(2)]
        assert sorted(f.result(timeout=5) for f in claims) == [1, 2]
