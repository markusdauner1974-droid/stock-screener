from __future__ import annotations

import os

import pytest

from scripts.profile_scan_phases import PhaseClock, _Timed, block_provider_fetches, summarize


def test_summarize_reports_shares_and_the_prefetch_overlap_bound():
    chunks = [
        {"prefetch": 1.0, "compute": 4.0, "persist": 0.5, "commit": 0.5, "wall": 6.5},
        {"prefetch": 2.0, "compute": 1.0, "persist": 0.5, "commit": 0.5, "wall": 4.5},
        {"prefetch": 0.5, "compute": 3.0, "wall": 3.5},
    ]

    summary = summarize(chunks)

    assert summary["wall_seconds"] == pytest.approx(14.5)
    assert summary["totals"]["compute"] == pytest.approx(8.0)
    assert summary["totals"]["other_parent"] == pytest.approx(1.0)
    assert summary["parent_io_share"] == pytest.approx(5.5 / 14.5)
    # Chunk 2's prefetch (2.0s) fits inside chunk 1's compute (4.0s); chunk 3's
    # prefetch (0.5s) fits inside chunk 2's compute (1.0s). Chunk 1's cannot overlap.
    assert summary["prefetch_overlap_seconds"] == pytest.approx(2.5)
    assert summary["max_speedup_from_prefetch_overlap"] == pytest.approx(14.5 / 12.0)


def test_chunk_wall_time_excludes_time_between_chunks(monkeypatch):
    now = iter([0.0, 10.0, 12.0, 20.0])
    monkeypatch.setattr("scripts.profile_scan_phases.time.perf_counter", lambda: next(now))
    clock = PhaseClock()  # 0.0

    clock.end_chunk()  # 10.0: chunk 1 took 10s
    clock.restart()  # 12.0: 2s of profiler output in between
    clock.end_chunk()  # 20.0: chunk 2 took 8s

    assert [chunk["wall"] for chunk in clock.chunks] == [10.0, 8.0]


def test_block_provider_fetches_stubs_every_price_provider_entry_point(monkeypatch):
    from app.services.benchmark_cache_service import BenchmarkCacheService
    from app.services.bulk_data_fetcher import BulkDataFetcher
    from app.services.price_cache_service import PriceCacheService

    # Re-set each patched name so monkeypatch restores it after the test.
    for owner, name in (
        (BulkDataFetcher, "fetch_prices_in_batches"),
        (BenchmarkCacheService, "_fetch_normalized_benchmark"),
        (PriceCacheService, "_fetch_direct_historical_data"),
    ):
        monkeypatch.setattr(owner, name, getattr(owner, name))
    for variable in ("NO_PROXY", "no_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY",
                     "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(variable, "*")

    blocked = block_provider_fetches()

    assert BulkDataFetcher.fetch_prices_in_batches(None, ["A", "B"], period="2y") == {}
    assert BenchmarkCacheService._fetch_normalized_benchmark(None, "SPY", "2y", "US") is None
    assert PriceCacheService._fetch_direct_historical_data(None, "A", period="2y") is None
    assert blocked == {"calls": 3, "symbols": 4}
    assert "NO_PROXY" not in os.environ and "no_proxy" not in os.environ
    assert os.environ["HTTPS_PROXY"] == os.environ["https_proxy"] == "http://127.0.0.1:9"


def test_timed_wrapper_charges_only_the_named_methods():
    class Port:
        def slow(self, value):
            return value * 2

        def untimed(self):
            return "plain"

    clock = PhaseClock()
    port = _Timed(Port(), clock, {"slow": "prefetch"})

    assert port.slow(21) == 42
    assert port.untimed() == "plain"
    assert set(clock.current) == {"prefetch"}
