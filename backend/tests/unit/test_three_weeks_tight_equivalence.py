"""Equivalence regression test for the three_weeks_tight vectorisation.

The detector keeps two implementations of the same algorithm:

* ``_find_tight_runs_scalar`` -- the original, one pandas slice per window.
* ``_find_tight_runs`` -- the vectorised path, plus a NaN fallback to the
  scalar one.

They must produce identical ``_TightRun`` sequences. This module pins that
property across deterministic patterns, boundary lengths, random walks, real
weekly frames where available, and the edge cases that motivated the NaN
fallback in the first place.

If a future change makes the fast path diverge, this test fails on the exact
field that differs rather than on a vague outcome mismatch.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.analysis.patterns.config import DEFAULT_SETUP_ENGINE_PARAMETERS
from app.analysis.patterns.three_weeks_tight import (
    _find_tight_runs,
    _find_tight_runs_scalar,
)

PARAMS = DEFAULT_SETUP_ENGINE_PARAMETERS

# Every field of _TightRun. Listed explicitly so a new field added without
# being compared here is a visible omission rather than a silent gap.
_COMPARED_FIELDS = (
    "start_idx",
    "end_idx",
    "weeks_tight",
    "mode",
    "max_contraction_pct",
    "tight_band_pct",
    "tight_range_pct",
    "vol_vs_10w",
    "pivot_idx",
    "pivot_price",
    "recency_weeks",
    "score",
)


def _weekly_frame(
    close: np.ndarray,
    *,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume: np.ndarray | None = None,
) -> pd.DataFrame:
    """Build a weekly OHLCV frame in the orientation the detector expects."""
    close = np.asarray(close, dtype=float)
    n = len(close)
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01 if high is None else np.asarray(high, float),
            "Low": close * 0.99 if low is None else np.asarray(low, float),
            "Close": close,
            "Volume": (
                np.full(n, 1_000_000.0, dtype=float)
                if volume is None
                else np.asarray(volume, dtype=float)
            ),
        },
        index=pd.date_range("2015-01-02", periods=n, freq="W-FRI"),
    )


def _compare(frame: pd.DataFrame, label: str) -> list[str]:
    """Return a list of human-readable differences (empty when equivalent)."""
    expected = _find_tight_runs_scalar(frame, PARAMS)
    actual = _find_tight_runs(frame, PARAMS)

    problems: list[str] = []
    if len(expected) != len(actual):
        problems.append(f"{label}: run count {len(expected)} != {len(actual)}")
        return problems

    for index, (want, got) in enumerate(zip(expected, actual)):
        for field in _COMPARED_FIELDS:
            a = getattr(want, field)
            b = getattr(got, field)

            if a is None or b is None:
                if a is not b:
                    problems.append(f"{label}[{index}].{field}: {a!r} != {b!r}")
                continue

            if isinstance(a, float):
                both_nan = math.isnan(a) and math.isnan(b)
                if both_nan:
                    continue
                if math.isnan(a) or math.isnan(b):
                    problems.append(
                        f"{label}[{index}].{field}: NaN mismatch {a!r} != {b!r}"
                    )
                    continue

            if a != b:
                problems.append(f"{label}[{index}].{field}: {a!r} != {b!r}")

    return problems


# ---------------------------------------------------------------------------
# Deterministic patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "close"),
    [
        (
            "tight_run",
            np.concatenate(
                [
                    np.linspace(70, 95, 24),
                    np.array([100.0, 100.2, 99.9, 100.1, 100.0, 100.15]),
                ]
            ),
        ),
        (
            "band_too_wide",
            np.concatenate(
                [
                    np.linspace(20, 95, 24),
                    np.array([100.0, 108.0, 92.0, 107.0, 93.0, 106.0]),
                ]
            ),
        ),
        ("flat", np.full(50, 100.0)),
        ("uptrend", np.linspace(50, 150, 100)),
        ("downtrend", np.linspace(150, 50, 100)),
        ("sinusoidal", 100 + 20 * np.sin(np.arange(120) / 5.0)),
    ],
)
def test_equivalence_deterministic_patterns(label: str, close: np.ndarray) -> None:
    assert _compare(_weekly_frame(close), label) == []


# ---------------------------------------------------------------------------
# Boundary lengths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14, 15, 16])
def test_equivalence_boundary_lengths(n: int) -> None:
    rng = np.random.default_rng(1000 + n)
    close = rng.normal(100, 2, n) if n else np.array([])
    assert _compare(_weekly_frame(close), f"n={n}") == []


# ---------------------------------------------------------------------------
# Random walks, including squeezed final weeks that produce real 3WT runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [30, 60, 120, 250, 300, 350])
@pytest.mark.parametrize("trial", range(4))
def test_equivalence_random_walk(n: int, trial: int) -> None:
    rng = np.random.default_rng((n, trial))
    close = np.maximum(100 + np.cumsum(rng.normal(0, 1.0, n)), 5.0)
    volume = rng.uniform(2e5, 3e6, n)
    frame = _weekly_frame(close, volume=volume)
    assert _compare(frame, f"walk n={n} #{trial}") == []


@pytest.mark.parametrize("n", [200, 350])
@pytest.mark.parametrize("trial", range(4))
def test_equivalence_random_walk_with_tight_tail(n: int, trial: int) -> None:
    rng = np.random.default_rng((7_000 + n, trial))
    close = np.maximum(50 + np.cumsum(rng.normal(0, 0.8, n)), 5.0)
    k = int(rng.integers(6, 16))
    close[-k:] = close[-k] * (1 + rng.normal(0, 0.002, k))
    assert _compare(_weekly_frame(close), f"walk+tight n={n} #{trial}") == []


# ---------------------------------------------------------------------------
# Edge cases, including the ones that select the NaN fallback
# ---------------------------------------------------------------------------


def test_equivalence_zero_prices() -> None:
    assert _compare(_weekly_frame(np.zeros(50)), "zeros") == []


def test_equivalence_negative_prices() -> None:
    assert _compare(_weekly_frame(np.full(50, -5.0)), "negative") == []


def test_equivalence_very_small_and_huge_prices() -> None:
    assert _compare(_weekly_frame(np.full(50, 1e-9)), "tiny") == []
    assert _compare(_weekly_frame(np.full(50, 1e9)), "huge") == []


def test_equivalence_zero_price_within_series() -> None:
    close = np.concatenate([np.full(20, 100.0), [0.0], np.full(20, 100.0)])
    assert _compare(_weekly_frame(close), "zero-in-series") == []


def test_equivalence_nan_in_close_uses_fallback() -> None:
    close = np.concatenate([np.full(20, 100.0), [np.nan], np.full(20, 100.0)])
    assert _compare(_weekly_frame(close), "nan-close") == []


def test_equivalence_nan_in_high_uses_fallback() -> None:
    high = np.concatenate([np.full(20, 101.0), [np.nan], np.full(19, 101.0)])
    frame = _weekly_frame(np.full(40, 100.0), high=high)
    assert _compare(frame, "nan-high") == []


def test_equivalence_zero_volume() -> None:
    frame = _weekly_frame(np.full(50, 100.0), volume=np.zeros(50))
    assert _compare(frame, "zero-volume") == []


def test_equivalence_partial_zero_volume() -> None:
    volume = np.concatenate([np.full(20, 1e6), np.zeros(30)])
    frame = _weekly_frame(np.full(50, 100.0), volume=volume)
    assert _compare(frame, "partial-zero-volume") == []


def test_equivalence_inverted_high_low() -> None:
    rng = np.random.default_rng(11)
    close = np.maximum(100 + rng.normal(0, 1, 80), 1.0)
    frame = _weekly_frame(close, high=close * 0.9, low=close * 1.1)
    assert _compare(frame, "inverted-hl") == []


def test_equivalence_non_datetime_index() -> None:
    frame = _weekly_frame(np.full(60, 100.0))
    frame.index = pd.RangeIndex(60)
    assert _compare(frame, "range-index") == []


def test_equivalence_integer_volume_dtype() -> None:
    frame = _weekly_frame(np.full(60, 100.0))
    frame["Volume"] = frame["Volume"].astype("int64")
    assert _compare(frame, "int-volume") == []


# ---------------------------------------------------------------------------
# Structural guarantee: the fallback is actually wired up
# ---------------------------------------------------------------------------


def test_nan_frame_selects_scalar_path() -> None:
    """A NaN frame must route through the scalar path, not silently differ.

    The vectorised path cannot reproduce pandas' NaN-skipping reductions, so
    the detector delegates instead of approximating. If the fallback were not
    wired up, the NaN frame would yield a NaN median, no window would pass the
    positivity test, and the run count would collapse -- which ``_compare``
    catches on the count before comparing any field.

    ``_compare`` rather than ``==``: ``_TightRun`` holds ``pivot_price``, which
    is NaN whenever a window's high contains one, and ``nan != nan`` would make
    an equality assertion fail on two identical lists.
    """
    close = np.concatenate([np.full(20, 100.0), [np.nan], np.full(20, 100.0)])
    frame = _weekly_frame(close)
    assert _compare(frame, "nan-close") == []


def test_non_nan_frame_matches_scalar_results() -> None:
    """The vectorised path is the one exercised on clean production frames."""
    frame = _weekly_frame(np.concatenate([np.full(20, 100.0), np.full(20, 100.05)]))
    assert np.isnan(frame[["Close", "High", "Low", "Volume"]].to_numpy()).sum() == 0
    assert _compare(frame, "clean-frame") == []
