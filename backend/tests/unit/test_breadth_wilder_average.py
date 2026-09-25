"""Pin ``_wilder_average`` to the per-element pandas loop it replaced.

The production helper now walks a numpy array instead of reading and writing
``Series.iloc`` one element at a time. The recursion, its NaN resets and its
pandas-mean seeding are unchanged, so the output must be bit-identical to the
original loop kept below as an oracle.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.breadth.formulas import _wilder_average


def _reference_wilder_average(values: pd.Series, period: int) -> pd.Series:
    """The original implementation, verbatim."""
    result = pd.Series(np.nan, index=values.index, dtype=float)
    if period <= 0 or len(values) < period:
        return result

    previous = np.nan
    for position in range(period - 1, len(values)):
        current = values.iloc[position]
        if pd.isna(current):
            previous = np.nan
        elif pd.isna(previous):
            restart = values.iloc[position - period + 1 : position + 1]
            previous = float(restart.mean()) if not restart.isna().any() else np.nan
        else:
            previous = ((previous * (period - 1)) + float(current)) / period
        result.iloc[position] = previous
    return result


def _series(values) -> pd.Series:
    values = np.asarray(values, dtype=float)
    return pd.Series(values, index=pd.bdate_range("2021-01-04", periods=len(values)))


def _assert_identical(values: pd.Series, period: int) -> None:
    expected = _reference_wilder_average(values, period)
    actual = _wilder_average(values, period)
    pd.testing.assert_index_equal(actual.index, expected.index)
    assert actual.dtype == expected.dtype
    # Bit-identical, NaN positions included -- not approximately equal.
    assert np.array_equal(actual.to_numpy(), expected.to_numpy(), equal_nan=True)


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("length", [0, 1, 13, 14, 15, 300, 1260])
def test_matches_reference_on_random_true_ranges(seed: int, length: int) -> None:
    rng = np.random.default_rng(seed)
    _assert_identical(_series(rng.lognormal(0.0, 0.6, length)), 14)


@pytest.mark.parametrize("seed", range(8))
def test_matches_reference_with_nan_gaps_and_restarts(seed: int) -> None:
    rng = np.random.default_rng(100 + seed)
    values = rng.lognormal(0.0, 0.6, 400)
    # Leading gap, isolated NaNs, and a gap shorter than the period so the
    # restart window itself still contains a NaN for a while.
    values[:3] = np.nan
    values[rng.integers(0, 400, 6)] = np.nan
    values[200:205] = np.nan
    _assert_identical(_series(values), 14)


@pytest.mark.parametrize("period", [-1, 0, 1, 2, 14, 50])
def test_matches_reference_across_periods(period: int) -> None:
    rng = np.random.default_rng(7)
    values = rng.lognormal(0.0, 0.6, 120)
    values[40] = np.nan
    _assert_identical(_series(values), period)


def test_matches_reference_with_infinite_values() -> None:
    values = np.full(60, 2.0)
    values[20] = np.inf
    _assert_identical(_series(values), 14)


def test_accepts_nullable_float_dtype() -> None:
    values = pd.Series([1.0, 2.0, None, 3.0, 4.0, 5.0], dtype="Float64")
    expected = _reference_wilder_average(values, 2)
    actual = _wilder_average(values, 2)
    assert np.array_equal(actual.to_numpy(), expected.to_numpy(dtype=float), equal_nan=True)
