"""Equivalence regression test for the three_weeks_tight vectorisation.

The detector has one implementation, ``_find_tight_runs``, which evaluates
every window of a given length with sliding-window views. This module holds an
independent scalar reference, ``_reference_find_tight_runs`` -- the original
one-pandas-slice-per-window loop -- and pins the two against each other.

They must produce identical ``_TightRun`` sequences across deterministic
patterns, boundary lengths, random walks, and numerical edge cases.

If a future change makes the fast path diverge, this test fails on the exact
field that differs rather than on a vague outcome mismatch.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import app.analysis.patterns.three_weeks_tight as three_weeks_tight_module

from app.analysis.patterns.config import DEFAULT_SETUP_ENGINE_PARAMETERS
from app.analysis.patterns.detectors.base import PatternDetectorInput
from app.analysis.patterns.normalization import normalize_ohlcv_frame
from app.analysis.patterns.three_weeks_tight import (
    _MAX_CANDIDATES,
    _MAX_WEEKS_TIGHT,
    _MIN_WEEKS_TIGHT,
    _TightRun,
    _find_tight_runs,
)

PARAMS = DEFAULT_SETUP_ENGINE_PARAMETERS

def _flat_frame(n: int, *, value: float = 100.0) -> pd.DataFrame:
    return _weekly_frame(np.full(n, value, dtype=float))


def _walk_frame(n: int, *, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return _weekly_frame(100.0 + np.cumsum(rng.normal(0.0, 1.5, n)))


_CASE_BUILDERS = {
    "flat": lambda: _flat_frame(300),
    "walk": lambda: _walk_frame(300, seed=7),
    "flat-120": lambda: _flat_frame(120, value=50.0),
    "walk-500": lambda: _walk_frame(500, seed=11),
}

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
    expected = _reference_find_tight_runs(frame, PARAMS)
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
    """Hand-built shapes (tight run, too-wide band, flat, trends, sine) stay identical."""
    assert _compare(_weekly_frame(close), label) == []


# ---------------------------------------------------------------------------
# Boundary lengths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14, 15, 16])
def test_equivalence_boundary_lengths(n: int) -> None:
    """Frame lengths around the minimum-window boundary agree, including empty frames."""
    rng = np.random.default_rng(1000 + n)
    close = rng.normal(100, 2, n) if n else np.array([])
    assert _compare(_weekly_frame(close), f"n={n}") == []


# ---------------------------------------------------------------------------
# Random walks, including squeezed final weeks that produce real 3WT runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [30, 60, 120, 250, 300, 350])
@pytest.mark.parametrize("trial", range(4))
def test_equivalence_random_walk(n: int, trial: int) -> None:
    """Random walks of varying length agree when no run is forced."""
    rng = np.random.default_rng((n, trial))
    close = np.maximum(100 + np.cumsum(rng.normal(0, 1.0, n)), 5.0)
    volume = rng.uniform(2e5, 3e6, n)
    frame = _weekly_frame(close, volume=volume)
    assert _compare(frame, f"walk n={n} #{trial}") == []


@pytest.mark.parametrize("n", [200, 350])
@pytest.mark.parametrize("trial", range(4))
def test_equivalence_random_walk_with_tight_tail(n: int, trial: int) -> None:
    """Walks with a deliberately squeezed final weeks do produce runs, and they agree."""
    rng = np.random.default_rng((7_000 + n, trial))
    close = np.maximum(50 + np.cumsum(rng.normal(0, 0.8, n)), 5.0)
    k = int(rng.integers(6, 16))
    close[-k:] = close[-k] * (1 + rng.normal(0, 0.002, k))
    assert _compare(_weekly_frame(close), f"walk+tight n={n} #{trial}") == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_equivalence_zero_prices() -> None:
    """An all-zero series is handled identically (no division blow-up)."""
    assert _compare(_weekly_frame(np.zeros(50)), "zeros") == []


def test_equivalence_negative_prices() -> None:
    """Negative prices stay identical -- they are rejected, not silently rescaled."""
    assert _compare(_weekly_frame(np.full(50, -5.0)), "negative") == []


def test_equivalence_very_small_and_huge_prices() -> None:
    """Extreme magnitudes (1e-9 and 1e9) agree, guarding the relative band maths."""
    assert _compare(_weekly_frame(np.full(50, 1e-9)), "tiny") == []
    assert _compare(_weekly_frame(np.full(50, 1e9)), "huge") == []


def test_equivalence_zero_price_within_series() -> None:
    """A single zero inside an otherwise normal series agrees."""
    close = np.concatenate([np.full(20, 100.0), [0.0], np.full(20, 100.0)])
    assert _compare(_weekly_frame(close), "zero-in-series") == []


def test_normalization_drops_nan_rows_before_detection() -> None:
    """NaN bars never reach ``_find_tight_runs``; normalization drops them.

    This is the precondition the vectorised path relies on. numpy propagates
    NaN where pandas reductions skip it silently, so the two disagree on a
    NaN-bearing frame. ``detect()`` therefore cleans the frame first, via
    ``normalize_detector_input_ohlcv`` -> ``normalize_ohlcv_frame``, which
    ends in ``df.dropna(subset=required)``.

    Pinning it here keeps the precondition honest: if that drop were removed,
    the vectorised path would silently produce different scores on real
    frames rather than fail loudly.
    """
    close = np.concatenate([np.full(20, 100.0), [np.nan], np.full(20, 100.0)])
    frame = _weekly_frame(close)
    assert np.isnan(frame[["Close"]].to_numpy()).sum() == 1

    normalized = normalize_ohlcv_frame(frame, timeframe="weekly", min_bars=30)

    assert normalized.frame is not None
    columns = ["Close", "High", "Low", "Volume"]
    assert np.isnan(normalized.frame[columns].to_numpy()).sum() == 0
    assert len(normalized.frame) == len(frame) - 1


def test_normalization_keeps_nan_free_frame_intact() -> None:
    """A clean frame passes through normalization unchanged in length."""
    frame = _weekly_frame(np.full(50, 100.0))
    normalized = normalize_ohlcv_frame(frame, timeframe="weekly", min_bars=30)

    assert normalized.frame is not None
    assert len(normalized.frame) == len(frame)


def test_equivalence_zero_volume() -> None:
    """Zero volume throughout agrees, including the volume-ratio gate."""
    frame = _weekly_frame(np.full(50, 100.0), volume=np.zeros(50))
    assert _compare(frame, "zero-volume") == []


def test_equivalence_partial_zero_volume() -> None:
    """Zero volume only in part of the series agrees."""
    volume = np.concatenate([np.full(20, 1e6), np.zeros(30)])
    frame = _weekly_frame(np.full(50, 100.0), volume=volume)
    assert _compare(frame, "partial-zero-volume") == []


def test_equivalence_inverted_high_low() -> None:
    """Inverted high/low values agree rather than silently producing different bands."""
    rng = np.random.default_rng(11)
    close = np.maximum(100 + rng.normal(0, 1, 80), 1.0)
    frame = _weekly_frame(close, high=close * 0.9, low=close * 1.1)
    assert _compare(frame, "inverted-hl") == []


def test_equivalence_non_datetime_index() -> None:
    """A non-datetime index agrees -- the detector indexes positionally."""
    frame = _weekly_frame(np.full(60, 100.0))
    frame.index = pd.RangeIndex(60)
    assert _compare(frame, "range-index") == []


def test_equivalence_integer_volume_dtype() -> None:
    """Integer volume dtype agrees with the float path."""
    frame = _weekly_frame(np.full(60, 100.0))
    frame["Volume"] = frame["Volume"].astype("int64")
    assert _compare(frame, "int-volume") == []


# ---------------------------------------------------------------------------
# The ``limit`` path used by detect()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["flat", "walk", "flat-120", "walk-500"],
)
def test_limit_equals_unbounded_head(name: str) -> None:
    """``limit=_MAX_CANDIDATES`` is exactly the head of the unbounded list.

    ``detect()`` reads ``runs[:_MAX_CANDIDATES]`` and nothing else, so the
    detector now asks for that head directly rather than materialising every
    candidate. This pins the shortcut's semantics: not "the first N found",
    which would depend on accumulation order, but the same ranking head the
    unbounded call produced.
    """
    frame = _CASE_BUILDERS[name]()
    full = _find_tight_runs(frame, PARAMS)
    limited = _find_tight_runs(frame, PARAMS, limit=_MAX_CANDIDATES)

    assert len(limited) == min(len(full), _MAX_CANDIDATES)
    for index, (a, b) in enumerate(zip(limited, full[:_MAX_CANDIDATES])):
        for field in _COMPARED_FIELDS:
            left, right = getattr(a, field), getattr(b, field)
            if isinstance(left, float) and isinstance(right, float):
                if math.isnan(left) and math.isnan(right):
                    continue
            assert left == right, f"{name}[{index}].{field}: {left!r} != {right!r}"


def test_limit_above_candidate_count_returns_all() -> None:
    """A limit larger than the candidate count is not a truncation."""
    frame = _walk_frame(101, seed=3)
    full = _find_tight_runs(frame, PARAMS)
    assert _find_tight_runs(frame, PARAMS, limit=len(full) + 10) == full


def test_unbounded_call_still_returns_the_scalar_tail() -> None:
    """``limit=None`` keeps the full list, tail included.

    The equivalence tests depend on this: they compare the unbounded result
    against the scalar reference, so a silent default of ``_MAX_CANDIDATES``
    would make them pass while hiding every dropped run.
    """
    frame = _walk_frame(300, seed=5)
    full = _find_tight_runs(frame, PARAMS)
    assert len(full) > _MAX_CANDIDATES
    assert full == _reference_find_tight_runs(frame, PARAMS)


def test_detect_passes_the_candidate_limit() -> None:
    """``detect()`` asks for the head directly, not the whole ranking.

    Counting on the module rather than inspecting the source keeps the
    assertion honest if the call site moves.
    """
    calls: list[int | None] = []
    real = three_weeks_tight_module._find_tight_runs

    def spy(weekly, parameters, *, limit=None):
        calls.append(limit)
        return real(weekly, parameters, limit=limit)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(three_weeks_tight_module, "_find_tight_runs", spy)
    try:
        detector = three_weeks_tight_module.ThreeWeeksTightDetector()
        detector.detect(
            PatternDetectorInput(
                symbol="TEST",
                timeframe="weekly",
                daily_bars=0,
                weekly_bars=300,
                features={"weekly_ohlcv": _CASE_BUILDERS["flat"]()},
            ),
            PARAMS,
        )
    finally:
        monkeypatch.undo()

    assert calls == [_MAX_CANDIDATES]


def test_detect_passes_normalized_weekly_frame_to_finder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``detect()`` hands the *normalized* frame to ``_find_tight_runs``.

    The normalization tests above call ``normalize_ohlcv_frame`` directly, so
    they prove the drop exists -- not that ``detect()`` uses it. If the call
    site in ``detect()`` were changed to pass the raw weekly frame, they would
    stay green while the vectorised finder received NaNs on real data. This
    captures the frame at the boundary instead: a NaN-bearing input must
    arrive at the finder one bar shorter and NaN-free.
    """
    close = np.concatenate([np.full(20, 100.0), [np.nan], np.full(20, 100.0)])
    frame = _weekly_frame(close)
    assert np.isnan(frame[["Close"]].to_numpy()).sum() == 1

    received: list[pd.DataFrame] = []

    def capture(weekly, parameters, *, limit=None):
        received.append(weekly)
        return []

    monkeypatch.setattr(three_weeks_tight_module, "_find_tight_runs", capture)

    detector = three_weeks_tight_module.ThreeWeeksTightDetector()
    detector.detect(
        PatternDetectorInput(
            symbol="TEST",
            timeframe="weekly",
            daily_bars=0,
            weekly_bars=len(frame),
            features={"weekly_ohlcv": frame},
        ),
        PARAMS,
    )

    assert len(received) == 1, "the finder was not reached"
    handed_over = received[0]
    assert len(handed_over) == len(frame) - 1, "the NaN bar was not dropped"
    columns = ["Close", "High", "Low", "Volume"]
    assert np.isnan(handed_over[columns].to_numpy()).sum() == 0


# ---------------------------------------------------------------------------
# Structural guarantee: one implementation, reached by every production frame
# ---------------------------------------------------------------------------


def test_module_carries_no_scalar_fallback() -> None:
    """The detector module holds exactly one implementation.

    The scalar fallback was removed because it could not run in production:
    ``detect()`` always normalizes first, so ``_find_tight_runs`` never sees a
    NaN frame. An unreachable ~100-line copy in the ship path meant two
    implementations to maintain against a path no caller could take -- and the
    NaN check that selected it was never true. The scalar loop lives on as the
    test-side reference, ``_reference_find_tight_runs``.
    """
    assert not hasattr(three_weeks_tight_module, "_find_tight_runs_scalar")

    source = Path(three_weeks_tight_module.__file__).read_text()
    assert "np.isnan" not in source, "a NaN guard reappeared in the detector"


def test_non_nan_frame_matches_scalar_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """The vectorised path is the one exercised on clean production frames.

    ``_compare`` derives its expectation from ``_reference_find_tight_runs``, so a
    detector that quietly diverged from it would still be caught -- but only on
    the result. Counting calls to the module's ``sliding_window_view`` pins the
    *path*, so removing the vectorisation cannot leave this suite green.
    """
    frame = _weekly_frame(np.concatenate([np.full(20, 100.0), np.full(20, 100.05)]))
    assert np.isnan(frame[["Close", "High", "Low", "Volume"]].to_numpy()).sum() == 0

    calls = 0
    original = three_weeks_tight_module.sliding_window_view

    def counting_sliding_window_view(*args: object, **kwargs: object) -> np.ndarray:
        """Count invocations of the module-level sliding-window view."""
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        three_weeks_tight_module,
        "sliding_window_view",
        counting_sliding_window_view,
    )

    assert _compare(frame, "clean-frame") == []

    # weeks_tight windows plus the trailing 10-week volume average.
    assert calls > 0, "the frame never reached the vectorised window views"


def _reference_find_tight_runs(
    weekly: pd.DataFrame,
    parameters: SetupEngineParameters,
) -> list[_TightRun]:
    """Reference implementation: one pandas slice per candidate window.

    This is the original scalar loop, moved out of the detector module. It is
    kept here so the vectorised production path has an independent oracle to
    be compared against, field by field.
    """
    closes = weekly["Close"]
    highs = weekly["High"]
    lows = weekly["Low"]
    volumes = weekly["Volume"]
    n = len(weekly)
    runs: list[_TightRun] = []

    strict_threshold = (
        parameters.three_weeks_tight_max_contraction_pct_strict
    )
    relaxed_threshold = (
        parameters.three_weeks_tight_max_contraction_pct_relaxed
    )

    for weeks_tight in range(_MIN_WEEKS_TIGHT, _MAX_WEEKS_TIGHT + 1):
        for end_idx in range(weeks_tight - 1, n):
            start_idx = end_idx - weeks_tight + 1
            close_window = closes.iloc[start_idx : end_idx + 1]
            high_window = highs.iloc[start_idx : end_idx + 1]
            low_window = lows.iloc[start_idx : end_idx + 1]

            median_close = float(close_window.median())
            if median_close <= 0.0:
                continue

            tight_band_pct = float(
                (
                    (close_window - median_close).abs() / median_close
                ).max()
                * 100.0
            )
            tight_range_pct = float(
                ((high_window.max() - low_window.min()) / median_close) * 100.0
            )

            if start_idx >= 10:
                prior_10w = float(volumes.iloc[start_idx - 10 : start_idx].mean())
                run_vol = float(volumes.iloc[start_idx : end_idx + 1].mean())
                vol_vs_10w = (run_vol / prior_10w) if prior_10w > 0 else None
            else:
                vol_vs_10w = None

            pivot_offset = int(high_window.to_numpy(dtype=float).argmax())
            pivot_idx = start_idx + pivot_offset
            pivot_price = float(highs.iat[pivot_idx])
            recency_weeks = n - 1 - end_idx

            if tight_band_pct <= strict_threshold:
                mode = "strict"
                threshold = strict_threshold
                mode_bias = 0.10
            elif tight_band_pct <= relaxed_threshold:
                mode = "relaxed"
                threshold = relaxed_threshold
                mode_bias = 0.0
            else:
                continue

            score = (
                min(weeks_tight, _MAX_WEEKS_TIGHT) * 0.16
                + max(0.0, 1.0 - (tight_band_pct / max(threshold, 1e-9)))
                * 0.55
                + max(0.0, 1.0 - recency_weeks / 10.0) * 0.19
                + mode_bias
            )
            runs.append(
                _TightRun(
                    start_idx=start_idx,
                    end_idx=end_idx,
                    weeks_tight=weeks_tight,
                    mode=mode,
                    max_contraction_pct=threshold,
                    tight_band_pct=tight_band_pct,
                    tight_range_pct=tight_range_pct,
                    vol_vs_10w=vol_vs_10w,
                    pivot_idx=pivot_idx,
                    pivot_price=pivot_price,
                    recency_weeks=recency_weeks,
                    score=score,
                )
            )

    runs.sort(
        key=lambda run: (
            -run.score,
            run.recency_weeks,
            -run.weeks_tight,
            run.tight_band_pct,
            run.mode != "strict",
            -run.pivot_idx,
        )
    )
    return runs
