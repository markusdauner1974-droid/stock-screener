from __future__ import annotations

import pytest

from scripts.profile_scan_phases import PhaseClock, _Timed, summarize


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
