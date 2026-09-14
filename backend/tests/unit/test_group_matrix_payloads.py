import json

import pandas as pd
import pytest

from app.scanners.criteria.price_sparkline import PriceSparklineCalculator
from app.services.group_matrix_payloads import build_group_matrix_payload, cap_tier


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "unknown"),
        (0, "unknown"),
        (-1, "unknown"),
        (True, "unknown"),
        (float("nan"), "unknown"),
        (float("inf"), "unknown"),
        (1, "nano"),
        (49_999_999, "nano"),
        (50_000_000, "micro"),
        (299_999_999, "micro"),
        (300_000_000, "small"),
        (1_999_999_999, "small"),
        (2_000_000_000, "mid"),
        (9_999_999_999, "mid"),
        (10_000_000_000, "large_mega"),
    ],
)
def test_cap_boundaries(value, expected):
    assert cap_tier(value) == expected


def test_missing_data_stays_visible_and_coverage_is_not_an_exclusion_count():
    result = build_group_matrix_payload(
        rows=[
            {
                "symbol": "A",
                "sector": "Tech",
                "ibd_industry_group": "Software",
                "market_cap_usd": 3e9,
                "price_change_1d": 0,
                "rs_rating": 87,
            },
            {"symbol": "B", "market_cap_usd": float("nan"), "rs_rating": 110},
            {
                "symbol": "C", "ibd_industry_group": "Software", "price_change_1d": float("inf")
            },
        ],
        metadata={"market": "US"},
        universe_count=4,
    )
    assert result["available"] is True
    assert result["coverage"] == {
        "universe_count": 4,
        "stock_count": 3,
        "missing_feature_count": 1,
        "ibd_mapped_count": 2,
        "unknown_sector_count": 2,
        "unknown_cap_count": 2,
        "missing_daily_change_count": 2,
        "missing_weekly_change_count": 3,
        "missing_monthly_change_count": 3,
        "missing_rs_count": 2,
    }
    assert result["stocks"][0]["price_change_1d"] == 0
    assert result["stocks"][1]["rs_rating"] is None
    assert result["stocks"][1]["cap_tier"] == "unknown"
    json.dumps(result, allow_nan=False)


def test_no_actual_ibd_mapping_is_unavailable():
    result = build_group_matrix_payload(
        rows=[{"symbol": "A"}], metadata={"market": "HK"}, universe_count=1
    )
    assert result["reason"] == "missing_ibd_mappings"
    assert result["stocks"] == []
    assert result["coverage"]["stock_count"] == 1


@pytest.mark.parametrize("value,expected", [(0, 0), (-4.25, -4.25), (None, None), (True, None), ("2.5", None), (float("nan"), None), (float("inf"), None)])
def test_weekly_monthly_returns_preserve_zero_and_normalize_invalid_values(value, expected):
    result = build_group_matrix_payload(
        rows=[{"symbol": "A", "ibd_industry_group": "Software", "price_change_1w": value, "price_change_1m": value}],
        metadata={"market": "US"}, universe_count=1,
    )
    assert result["stocks"][0]["price_change_1w"] == expected
    assert result["stocks"][0]["price_change_1m"] == expected
    assert result["coverage"]["missing_weekly_change_count"] == (expected is None)
    assert result["coverage"]["missing_monthly_change_count"] == (expected is None)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "rows,count", [([{"symbol": "A"}, {"symbol": "A"}], 2), ([{"symbol": "A"}], 0)]
)
def test_incoherent_membership_is_rejected(rows, count):
    with pytest.raises(ValueError):
        build_group_matrix_payload(
            rows=rows, metadata={"market": "US"}, universe_count=count
        )


def test_daily_change_producer_uses_percentage_points():
    assert (
        PriceSparklineCalculator()._calculate_price_change_1d(pd.Series([100.0, 102.0]))
        == 2
    )
