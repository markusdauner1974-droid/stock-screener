"""Three-Weeks-Tight / Multi-Weeks-Tight detector entrypoint.

Expected input orientation:
- Weekly bars derived from chronological daily bars.
- Current incomplete week excluded unless policy explicitly permits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from app.analysis.patterns.config import SetupEngineParameters
from app.analysis.patterns.detectors.base import (
    PatternDetector,
    PatternDetectorInput,
    PatternDetectorResult,
)
from app.analysis.patterns.models import PatternCandidateModel
from app.analysis.patterns.normalization import normalize_detector_input_ohlcv
from app.analysis.patterns.technicals import (
    has_incomplete_last_period,
    resample_ohlcv,
)

_MIN_WEEKS_TIGHT = 3
_MAX_WEEKS_TIGHT = 8
_MAX_CANDIDATES = 5


@dataclass(frozen=True)
class _TightRun:
    start_idx: int
    end_idx: int
    weeks_tight: int
    mode: str
    max_contraction_pct: float
    tight_band_pct: float
    tight_range_pct: float
    vol_vs_10w: float | None
    pivot_idx: int
    pivot_price: float
    recency_weeks: int
    score: float


class ThreeWeeksTightDetector(PatternDetector):
    """Compile-safe entrypoint for 3WT/MWT detection."""

    name = "three_weeks_tight"

    def detect(
        self,
        detector_input: PatternDetectorInput,
        parameters: SetupEngineParameters,
    ) -> PatternDetectorResult:
        weekly_frame, warnings = _resolve_weekly_frame(detector_input)
        if weekly_frame is None:
            return PatternDetectorResult.insufficient_data(
                self.name,
                failed_checks=("missing_weekly_ohlcv_for_three_weeks_tight",),
                warnings=warnings,
            )

        normalized_weekly = normalize_detector_input_ohlcv(
            features={"weekly_ohlcv": weekly_frame},
            timeframe="weekly",
            min_bars=_MIN_WEEKS_TIGHT + 2,
            feature_key="weekly_ohlcv",
            fallback_bar_count=len(weekly_frame),
        )
        if not normalized_weekly.prerequisites_ok:
            return PatternDetectorResult.insufficient_data(
                self.name,
                normalized=normalized_weekly,
                warnings=warnings,
            )

        if normalized_weekly.frame is None:
            return PatternDetectorResult.insufficient_data(
                self.name,
                failed_checks=("missing_weekly_ohlcv_for_three_weeks_tight",),
                warnings=warnings,
            )

        warnings = tuple(warnings) + normalized_weekly.warnings
        weekly = normalized_weekly.frame
        runs = _find_tight_runs(weekly, parameters)
        if not runs:
            return PatternDetectorResult.no_detection(
                self.name,
                failed_checks=("tight_run_not_found",),
                warnings=warnings,
            )

        candidates: list[PatternCandidateModel] = []
        for run_rank, run in enumerate(runs[:_MAX_CANDIDATES], start=1):
            pivot_date = weekly.index[run.pivot_idx].date().isoformat()
            run_slice = weekly.iloc[run.start_idx : run.end_idx + 1]
            median_close = float(run_slice["Close"].median())
            confidence = min(
                0.95,
                max(
                    0.05,
                    0.35
                    + min(run.weeks_tight, _MAX_WEEKS_TIGHT) * 0.06
                    + max(0.0, 1.0 - (run.tight_band_pct / 3.0)) * 0.20,
                ),
            )
            quality_score = min(
                100.0,
                max(
                    0.0,
                    30.0
                    + min(run.weeks_tight, _MAX_WEEKS_TIGHT) * 6.0
                    + max(0.0, 1.0 - (run.tight_band_pct / 3.0)) * 30.0,
                ),
            )
            readiness_score = min(
                100.0,
                max(
                    0.0,
                    55.0
                    + max(0.0, 1.0 - run.recency_weeks / 8.0) * 20.0
                    + max(0.0, 1.0 - (run.tight_band_pct / 2.0)) * 15.0,
                ),
            )

            candidates.append(
                PatternCandidateModel(
                    pattern=self.name,
                    timeframe="weekly",
                    source_detector=self.name,
                    pivot_price=run.pivot_price,
                    pivot_type="tight_area_high",
                    pivot_date=pivot_date,
                    distance_to_pivot_pct=(
                        ((run.pivot_price - float(weekly["Close"].iat[-1]))
                         / max(float(weekly["Close"].iat[-1]), 1e-9))
                        * 100.0
                    ),
                    quality_score=quality_score,
                    readiness_score=readiness_score,
                    confidence=confidence,
                    metrics={
                        "run_rank": run_rank,
                        "weeks_tight": run.weeks_tight,
                        "tight_mode": run.mode,
                        "tight_mode_threshold_pct": round(
                            run.max_contraction_pct, 4
                        ),
                        "tight_band_pct": round(run.tight_band_pct, 6),
                        "tight_range_pct": round(run.tight_range_pct, 6),
                        "vol_vs_10w": (
                            round(run.vol_vs_10w, 6)
                            if run.vol_vs_10w is not None
                            else None
                        ),
                        "run_start_date": weekly.index[run.start_idx]
                        .date()
                        .isoformat(),
                        "run_end_date": weekly.index[run.end_idx]
                        .date()
                        .isoformat(),
                        "median_close": round(median_close, 6),
                        "recency_weeks": run.recency_weeks,
                    },
                    checks={
                        "weeks_tight_min_met": run.weeks_tight >= _MIN_WEEKS_TIGHT,
                        "tight_band_ok": run.tight_band_pct
                        <= run.max_contraction_pct,
                        "tight_mode_strict": run.mode == "strict",
                        "tight_mode_relaxed": run.mode == "relaxed",
                    },
                    notes=("strict_relaxed_modes_evaluated",),
                )
            )

        return PatternDetectorResult.detected(
            self.name,
            tuple(candidates),
            passed_checks=("tight_run_detected",),
            warnings=warnings,
        )


def _resolve_weekly_frame(
    detector_input: PatternDetectorInput,
) -> tuple[pd.DataFrame | None, tuple[str, ...]]:
    warnings: list[str] = []
    weekly_raw = detector_input.features.get("weekly_ohlcv")
    if isinstance(weekly_raw, pd.DataFrame):
        return weekly_raw, ()

    daily_raw = detector_input.features.get("daily_ohlcv")
    if isinstance(daily_raw, pd.DataFrame):
        normalized_daily = normalize_detector_input_ohlcv(
            features={"daily_ohlcv": daily_raw},
            timeframe="daily",
            min_bars=30,
            feature_key="daily_ohlcv",
            fallback_bar_count=detector_input.daily_bars,
        )
        warnings.extend(normalized_daily.warnings)
        if not normalized_daily.prerequisites_ok or normalized_daily.frame is None:
            return None, tuple(warnings)
        if has_incomplete_last_period(normalized_daily.frame.index, rule="W-FRI"):
            warnings.append("incomplete_current_week_excluded_from_weekly_resample")
        resampled = resample_ohlcv(
            normalized_daily.frame,
            rule="W-FRI",
            exclude_incomplete_last_period=True,
        )
        warnings.append("weekly_ohlcv_resampled_from_daily")
        return resampled, tuple(warnings)

    return None, tuple(warnings)


def _find_tight_runs(
    weekly: pd.DataFrame,
    parameters: SetupEngineParameters,
) -> list[_TightRun]:
    """Collect all tight runs in the weekly frame.

    Precondition: ``weekly`` is NaN-free across ``Close``/``High``/``Low``/
    ``Volume``. ``detect()`` always routes the weekly frame through
    ``normalize_detector_input_ohlcv``, which drops any bar with a NaN in a
    required column, so the detector never sees one. This matters because the
    vectorised maths propagates NaN where pandas reductions skip it silently;
    the two disagree on such frames, and the frame is therefore cleaned before
    it arrives here rather than handled twice.

    The former scalar reference implementation now lives in
    ``tests/unit/test_three_weeks_tight_equivalence.py``, where it pins this
    one's output.
    """
    close_arr = weekly["Close"].to_numpy(dtype=float)
    high_arr = weekly["High"].to_numpy(dtype=float)
    low_arr = weekly["Low"].to_numpy(dtype=float)
    vol_arr = weekly["Volume"].to_numpy(dtype=float)
    n = len(weekly)

    if n == 0:
        return []

    strict_threshold = (
        parameters.three_weeks_tight_max_contraction_pct_strict
    )
    relaxed_threshold = (
        parameters.three_weeks_tight_max_contraction_pct_relaxed
    )

    runs: list[_TightRun] = []

    # Rolling mean over 10 bars, used for the volume comparison. Index i holds
    # the mean of volumes[i : i + 10]; the prior-10-week mean for a run that
    # starts at s is therefore entry s - 10.
    prior_10w_lookup: np.ndarray | None = None
    if n >= 10:
        prior_10w_lookup = sliding_window_view(vol_arr, 10).mean(axis=1)

    for weeks_tight in range(_MIN_WEEKS_TIGHT, _MAX_WEEKS_TIGHT + 1):
        if weeks_tight > n:
            continue

        close_win = sliding_window_view(close_arr, weeks_tight)
        high_win = sliding_window_view(high_arr, weeks_tight)
        low_win = sliding_window_view(low_arr, weeks_tight)
        vol_win = sliding_window_view(vol_arr, weeks_tight)

        median_close = np.median(close_win, axis=1)
        positive = median_close > 0.0
        if not positive.any():
            continue

        with np.errstate(divide="ignore", invalid="ignore"):
            tight_band_pct = (
                (np.abs(close_win - median_close[:, None]) / median_close[:, None])
                .max(axis=1)
                * 100.0
            )
            tight_range_pct = (
                (high_win.max(axis=1) - low_win.min(axis=1))
                / median_close
                * 100.0
            )

        strict_mask = positive & (tight_band_pct <= strict_threshold)
        relaxed_mask = (
            positive
            & ~strict_mask
            & (tight_band_pct <= relaxed_threshold)
        )
        keep = strict_mask | relaxed_mask
        if not keep.any():
            continue

        pivot_offset = high_win.argmax(axis=1)
        run_vol = vol_win.mean(axis=1)

        window_count = n - weeks_tight + 1
        end_all = np.arange(weeks_tight - 1, window_count + weeks_tight - 1)

        for i in np.nonzero(keep)[0]:
            start_idx = int(i)
            end_idx = int(end_all[i])

            if strict_mask[i]:
                mode = "strict"
                threshold = strict_threshold
                mode_bias = 0.10
            else:
                mode = "relaxed"
                threshold = relaxed_threshold
                mode_bias = 0.0

            if start_idx >= 10:
                prior_10w = float(prior_10w_lookup[start_idx - 10])
                vol_vs_10w = (
                    float(run_vol[i]) / prior_10w if prior_10w > 0 else None
                )
            else:
                vol_vs_10w = None

            pivot_idx = start_idx + int(pivot_offset[i])
            pivot_price = float(high_arr[pivot_idx])
            recency_weeks = n - 1 - end_idx
            band_pct = float(tight_band_pct[i])

            score = (
                min(weeks_tight, _MAX_WEEKS_TIGHT) * 0.16
                + max(0.0, 1.0 - (band_pct / max(threshold, 1e-9)))
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
                    tight_band_pct=band_pct,
                    tight_range_pct=float(tight_range_pct[i]),
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
