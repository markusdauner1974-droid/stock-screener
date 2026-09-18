from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from types import SimpleNamespace

from app.domain.relative_strength import BALANCED_RS_FORMULA_VERSION
from app.scripts import export_static_site
from app.services.market_exposure_service import EXPOSURE_BACKFILL_DAYS
from app.services.static_market_publish_policy import StaticMarketRsArtifactState


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _ReadyGroupRankBackfill:
    ready_for_enrichment = True

    def as_dict(self) -> dict[str, str]:
        return {"status": "completed"}


def test_refresh_static_daily_prices_uses_exposure_lookback_for_history_hydration(
    monkeypatch,
):
    init_kwargs: dict[str, object] = {}
    refresh_kwargs: dict[str, object] = {}

    class _FakeStaticDailyPriceRefreshService:
        def __init__(self, **kwargs):
            init_kwargs.update(kwargs)

        def refresh(self, **kwargs):
            refresh_kwargs.update(kwargs)
            return {"status": "completed"}

    monkeypatch.setattr(
        export_static_site,
        "StaticDailyPriceRefreshService",
        _FakeStaticDailyPriceRefreshService,
    )
    monkeypatch.setattr(export_static_site, "SessionLocal", object())
    monkeypatch.setattr(export_static_site, "get_price_cache", lambda: object())
    monkeypatch.setattr(export_static_site, "BulkDataFetcher", lambda: object())

    result = export_static_site._refresh_static_daily_prices(
        as_of_date=date(2026, 7, 31),
        market="US",
    )

    assert result == {"status": "completed"}
    assert (
        init_kwargs["breadth_history_price_lookback_days"]
        == EXPOSURE_BACKFILL_DAYS
    )
    assert refresh_kwargs == {
        "as_of_date": date(2026, 7, 31),
        "market": "US",
        "ensure_static_history": True,
    }


def test_static_daily_refresh_ensures_market_breadth_before_exposure(monkeypatch):
    events: list[tuple[str, str]] = []
    breadth_call: dict[str, object] = {}

    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("HK",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 7, 31),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )
    monkeypatch.setattr(
        export_static_site,
        "_prepare_static_rs_formula",
        lambda *, market, as_of_date, formula_version: {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "classify_static_market_rs_artifact_result",
        lambda *args, **kwargs: StaticMarketRsArtifactState.READY,
    )

    def ensure_breadth(*, as_of_date, market, min_trading_days=None, lookback_days=None):
        breadth_call.update(
            as_of_date=as_of_date,
            market=market,
            min_trading_days=min_trading_days,
            lookback_days=lookback_days,
        )
        events.append(("breadth", market))
        return {"status": "completed", "market": market, "as_of_date": as_of_date.isoformat()}

    def compute_exposure(*, as_of_date, market):
        events.append(("exposure", market))
        return {"market": market, "date": as_of_date.isoformat(), "status": "stored"}

    monkeypatch.setattr(export_static_site, "_ensure_breadth_history", ensure_breadth)
    monkeypatch.setattr(export_static_site, "_compute_static_market_exposure", compute_exposure)

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(
            run=lambda **kwargs: {
                "status": "published",
                "run_id": 7,
                "market": kwargs["market"],
            }
        ),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_group_rank_history",
        lambda **kwargs: _ReadyGroupRankBackfill(),
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="HK",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert warnings == []
    assert results["market_exposure"]["HK"]["status"] == "stored"
    assert events.index(("breadth", "HK")) < events.index(("exposure", "HK"))
    assert breadth_call == {
        "as_of_date": date(2026, 7, 31),
        "market": "HK",
        "min_trading_days": 0,
        "lookback_days": EXPOSURE_BACKFILL_DAYS,
    }


def test_static_daily_refresh_rewinds_to_latest_benchmark_backed_session(
    monkeypatch,
):
    prepare_calls: list[date] = []
    snapshot_calls: list[dict[str, object]] = []

    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("DE",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 8, 3),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )

    def prepare_static_rs(*, market, as_of_date, formula_version):
        prepare_calls.append(as_of_date)
        if as_of_date == date(2026, 8, 3):
            return {
                "status": "failed",
                "market": market,
                "as_of_date": "2026-08-03",
                "formula_version": formula_version,
                "reason_code": "benchmark_adjusted_anchor_missing",
                "diagnostics": {
                    "error": "benchmark_not_current",
                    "market": market,
                    "date": "2026-08-03",
                    "benchmark_candidates": [
                        {
                            "symbol": "^GDAXI",
                            "role": "primary",
                            "source": "fetch",
                            "status": "stale_required_date",
                            "latest_date": datetime(2026, 7, 31, 15, 30),
                        },
                    ],
                },
                "market_rs_run_id": None,
            }
        return {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        }

    monkeypatch.setattr(export_static_site, "_prepare_static_rs_formula", prepare_static_rs)
    monkeypatch.setattr(
        export_static_site,
        "_ensure_breadth_history",
        lambda **kwargs: {
            "status": "completed",
            "market": kwargs["market"],
            "as_of_date": kwargs["as_of_date"].isoformat(),
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "_compute_static_market_exposure",
        lambda **kwargs: {
            "market": kwargs["market"],
            "date": kwargs["as_of_date"].isoformat(),
            "status": "stored",
        },
    )

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    def build_snapshot(**kwargs):
        snapshot_calls.append(kwargs)
        return {
            "status": "published",
            "run_id": 7,
            "market": kwargs["market"],
            "as_of_date": kwargs["as_of_date_str"],
        }

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(run=build_snapshot),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_group_rank_history",
        lambda **kwargs: _ReadyGroupRankBackfill(),
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="DE",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert prepare_calls == [date(2026, 8, 3), date(2026, 7, 31)]
    assert results["market_rs"]["DE"]["status"] == "completed"
    assert results["market_rs"]["DE"]["as_of_date"] == "2026-07-31"
    assert snapshot_calls[0]["as_of_date_str"] == "2026-07-31"
    assert (
        "Static export market DE using benchmark-backed as-of date 2026-07-31 "
        "because benchmarks were unavailable for 2026-08-03."
    ) in warnings


def test_static_daily_refresh_skips_exposure_when_breadth_history_errors(monkeypatch):
    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("US",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 7, 31),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )
    monkeypatch.setattr(
        export_static_site,
        "_prepare_static_rs_formula",
        lambda *, market, as_of_date, formula_version: {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "classify_static_market_rs_artifact_result",
        lambda *args, **kwargs: StaticMarketRsArtifactState.READY,
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_breadth_history",
        lambda **kwargs: {
            "status": "errored",
            "market": kwargs["market"],
            "as_of_date": kwargs["as_of_date"].isoformat(),
            "errors": 1,
            "error_dates": [kwargs["as_of_date"].isoformat()],
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "_compute_static_market_exposure",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("exposure must not compute when breadth is incomplete")
        ),
    )

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(
            run=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("snapshot must not publish after exposure is skipped")
            )
        ),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )
    monkeypatch.setattr(
        export_static_site,
        "_run_static_cot_refresh",
        lambda: {"status": "published", "run_id": 99},
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="US",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert results["market_exposure"]["US"]["error"] == "market_breadth_not_ready"
    assert results["feature_snapshots"]["US"]["reason"] == "market_exposure_not_ready"
    assert results["cot"] == {"status": "published", "run_id": 99}
    assert (
        "Static export market US exposure not stored for 2026-07-31: "
        "market_breadth_not_ready."
    ) in warnings

    market_only_results, _ = export_static_site._run_daily_refresh(
        market="US",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        skip_cot_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )
    assert "cot" not in market_only_results


def test_static_daily_refresh_quarantines_breadth_history_exceptions(monkeypatch):
    monkeypatch.setattr(export_static_site, "STATIC_EXPORT_MARKETS", ("HK",))
    monkeypatch.setattr(export_static_site, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(export_static_site, "disable_serialized_data_fetch_lock", nullcontext)
    monkeypatch.setattr(export_static_site, "disable_serialized_market_workload", nullcontext)
    monkeypatch.setattr(export_static_site, "_tracked_ibd_csv_path", lambda: "ibd.csv")
    monkeypatch.setattr(
        export_static_site.IBDIndustryService,
        "load_from_csv",
        lambda _db, csv_path: 0,
    )
    monkeypatch.setattr(
        export_static_site,
        "_resolve_latest_completed_trading_date",
        lambda market: date(2026, 7, 31),
    )
    monkeypatch.setattr(
        export_static_site,
        "_refresh_static_daily_prices",
        lambda *, as_of_date, market: {"status": "completed", "market": market},
    )
    monkeypatch.setattr(
        export_static_site,
        "_prepare_static_rs_formula",
        lambda *, market, as_of_date, formula_version: {
            "status": "completed",
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "formula_version": formula_version,
            "market_rs_run_id": 42,
        },
    )
    monkeypatch.setattr(
        export_static_site,
        "classify_static_market_rs_artifact_result",
        lambda *args, **kwargs: StaticMarketRsArtifactState.READY,
    )
    monkeypatch.setattr(
        export_static_site,
        "_ensure_breadth_history",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("cache read failed")),
    )
    monkeypatch.setattr(
        export_static_site,
        "_compute_static_market_exposure",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("exposure must not compute when breadth raises")
        ),
    )

    import app.interfaces.tasks.feature_store_tasks as feature_store_tasks

    monkeypatch.setattr(
        feature_store_tasks,
        "build_daily_snapshot",
        SimpleNamespace(
            run=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("snapshot must not publish after breadth raises")
            )
        ),
    )
    monkeypatch.setattr(
        feature_store_tasks,
        "_enrich_feature_run_with_ibd_metadata",
        lambda **kwargs: {"status": "completed"},
    )

    results, warnings = export_static_site._run_daily_refresh(
        market="HK",
        skip_universe_refresh=True,
        skip_fundamentals_refresh=True,
        rs_formula_version=BALANCED_RS_FORMULA_VERSION,
    )

    assert results["breadth_history"]["HK"] == {
        "status": "errored",
        "market": "HK",
        "as_of_date": "2026-07-31",
        "error": "cache read failed",
        "exception_type": "RuntimeError",
    }
    assert results["market_exposure"]["HK"]["error"] == "market_breadth_not_ready"
    assert results["feature_snapshots"]["HK"]["reason"] == "market_exposure_not_ready"
    assert (
        "Static export market HK breadth history failed for 2026-07-31: "
        "cache read failed"
    ) in warnings
