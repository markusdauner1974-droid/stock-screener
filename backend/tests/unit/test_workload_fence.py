"""Commit-time fencing rejects writes from a superseded workload lease holder."""

from __future__ import annotations

import contextvars
from datetime import date
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from celery.exceptions import Retry
import pandas as pd
import pytest

from app.database import SessionLocal
from app.infra.db.models.feature_store import FeatureRun
from app.models.industry import IBDGroupRank
from app.models.market_breadth import MarketBreadth
from app.models.stock import StockPrice
from app.services.price_cache_service import PriceCacheService
from app.tasks.workload_fence import LeaseLost, _claim_generation, workload_fence

KEY = "market_workload:us"
DAY = date(2026, 9, 25)

# One row per fenced destination: breadth, group ranks, snapshots, prices.
DESTINATION_ROWS = {
    "breadth": lambda: MarketBreadth(market="US", date=DAY, total_stocks_scanned=1),
    "group_ranks": lambda: IBDGroupRank(
        market="US", industry_group="Semis", date=DAY, rank=1, avg_rs_rating=90.0
    ),
    "snapshots": lambda: FeatureRun(
        as_of_date=DAY, run_type="daily_snapshot", status="running"
    ),
    "prices": lambda: StockPrice(symbol="AAPL", date=DAY, close=1.0),
}


def _successor_takes_over() -> None:
    # A successor runs in another worker, outside this task's fences.
    contextvars.Context().run(_claim_generation, KEY)


def _count(model) -> int:
    with SessionLocal() as db:
        return db.query(model).count()


@pytest.mark.parametrize("destination", sorted(DESTINATION_ROWS))
def test_current_holder_commits_to_every_destination(destination):
    row = DESTINATION_ROWS[destination]()
    with workload_fence(KEY, threading.Event()):
        with SessionLocal() as db:
            db.add(row)
            db.commit()
    assert _count(type(row)) == 1


@pytest.mark.parametrize("destination", sorted(DESTINATION_ROWS))
def test_former_holder_cannot_commit_after_successor_takes_over(destination):
    row = DESTINATION_ROWS[destination]()
    with pytest.raises(LeaseLost):
        with workload_fence(KEY, threading.Event()):
            _successor_takes_over()
            with SessionLocal() as db:
                db.add(row)
                with pytest.raises(LeaseLost, match="superseded"):
                    db.commit()
    assert _count(type(row)) == 0


def test_lease_loss_signal_rejects_commit_before_any_successor_claims():
    lost = threading.Event()
    with pytest.raises(LeaseLost):
        with workload_fence(KEY, lost):
            lost.set()
            with SessionLocal() as db:
                db.add(DESTINATION_ROWS["breadth"]())
                with pytest.raises(LeaseLost, match="lease lost"):
                    db.commit()
    assert _count(MarketBreadth) == 0


def test_price_cache_writer_propagates_rejection_instead_of_swallowing_it():
    prices = pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1]},
        index=pd.DatetimeIndex([pd.Timestamp(DAY)], name="Date"),
    )
    cache = PriceCacheService(redis_client=MagicMock(), session_factory=SessionLocal)
    with pytest.raises(LeaseLost):
        with workload_fence(KEY, threading.Event()):
            _successor_takes_over()
            with pytest.raises(LeaseLost):
                cache._store_batch_in_database({"AAPL": prices})
    assert _count(StockPrice) == 0


def test_swallowed_rejection_still_fails_the_fenced_block():
    with pytest.raises(LeaseLost, match="rejected"):
        with workload_fence(KEY, threading.Event()):
            _successor_takes_over()
            with SessionLocal() as db:
                db.add(DESTINATION_ROWS["breadth"]())
                try:
                    db.commit()
                except Exception:
                    db.rollback()  # a writer that logs and moves on


def test_nested_block_for_same_key_keeps_outer_generation():
    with workload_fence(KEY, threading.Event()):
        with workload_fence(KEY, threading.Event()):
            pass
        with SessionLocal() as db:
            db.add(DESTINATION_ROWS["breadth"]())
            db.commit()
    assert _count(MarketBreadth) == 1


def test_commits_outside_a_fence_are_not_checked():
    _claim_generation(KEY)
    with SessionLocal() as db:
        db.add(DESTINATION_ROWS["breadth"]())
        db.commit()
    assert _count(MarketBreadth) == 1


@patch("app.wiring.bootstrap.get_workload_coordination")
def test_decorated_task_waits_and_retries_after_losing_its_lease(mock_get_coordination):
    from app.tasks.workload_coordination import serialized_market_workload

    coordination = MagicMock()
    coordination.acquire_market_workload.return_value = (True, False)
    coordination.renew_market_workload.return_value = True
    mock_get_coordination.return_value = coordination
    retries = []

    def _retry(*, exc=None, countdown=None, max_retries=None):
        retries.append(exc)
        raise Retry(message=str(exc))

    task = SimpleNamespace(request=SimpleNamespace(id="t-1", retries=0), retry=_retry)

    @serialized_market_workload("calculate_daily_breadth")
    def body(self, market=None):
        _successor_takes_over()  # mid-run takeover
        with SessionLocal() as db:
            db.add(DESTINATION_ROWS["breadth"]())
            db.commit()

    with pytest.raises(Retry):
        body(task, market="US")

    assert "waiting_for_market_workload:US" in str(retries[0])
    assert _count(MarketBreadth) == 0
