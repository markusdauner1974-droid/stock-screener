"""Pure normalization and coverage calculation for the Group Matrix."""

from math import isfinite

from app.schemas.group_matrix import GroupMatrixResponse, MatrixStock

TIERS = [
    {"id": "large_mega", "label": "Large/Mega", "min_usd": 10e9, "max_usd": None},
    {"id": "mid", "label": "Mid", "min_usd": 2e9, "max_usd": 10e9},
    {"id": "small", "label": "Small", "min_usd": 300e6, "max_usd": 2e9},
    {"id": "micro", "label": "Micro", "min_usd": 50e6, "max_usd": 300e6},
    {"id": "nano", "label": "Nano", "min_usd": 0, "max_usd": 50e6},
    {"id": "unknown", "label": "Unknown cap", "min_usd": None, "max_usd": None},
]


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if isfinite(value) else None


def cap_tier(value):
    value = finite_number(value)
    if value is None or value <= 0:
        return "unknown"
    return next(tier["id"] for tier in TIERS[:-1] if value >= tier["min_usd"])


def _text(value):
    return value.strip() or None if isinstance(value, str) else None


def _stock(row):
    values = {key: row.get(key) for key in MatrixStock.model_fields}
    for key in (
        "sector",
        "ibd_industry_group",
        "company_name",
        "classification_source",
    ):
        values[key] = _text(values[key])
    for key in (
        "market_cap_usd",
        "price_change_1d",
        "price_change_1w",
        "price_change_1m",
        "rs_rating",
        "classification_confidence",
    ):
        values[key] = finite_number(values[key])
    values["cap_tier"] = cap_tier(values["market_cap_usd"])
    if values["cap_tier"] == "unknown":
        values["market_cap_usd"] = None
    for key, upper in (("rs_rating", 100), ("classification_confidence", 1)):
        if values[key] is not None and not 0 <= values[key] <= upper:
            values[key] = None
    for key in ("classification_updated_at", "fundamentals_updated_at"):
        if hasattr(values[key], "isoformat"):
            values[key] = values[key].isoformat()
    return MatrixStock(**values)


def build_group_matrix_payload(*, rows, metadata, universe_count):
    stocks = sorted((_stock(row) for row in rows), key=lambda stock: stock.symbol)
    if len({stock.symbol for stock in stocks}) != len(stocks) or universe_count < len(
        stocks
    ):
        raise ValueError("Matrix feature membership is inconsistent")
    mapped = sum(stock.ibd_industry_group is not None for stock in stocks)
    reason = (
        "no_feature_rows"
        if not stocks
        else "missing_ibd_mappings"
        if not mapped
        else None
    )
    return GroupMatrixResponse(
        **metadata,
        available=reason is None,
        reason=reason,
        tiers=TIERS,
        stocks=stocks if reason is None else [],
        coverage={
            "universe_count": universe_count,
            "stock_count": len(stocks),
            "missing_feature_count": universe_count - len(stocks),
            "ibd_mapped_count": mapped,
            "unknown_sector_count": sum(stock.sector is None for stock in stocks),
            "unknown_cap_count": sum(stock.cap_tier == "unknown" for stock in stocks),
            "missing_daily_change_count": sum(
                stock.price_change_1d is None for stock in stocks
            ),
            "missing_weekly_change_count": sum(
                stock.price_change_1w is None for stock in stocks
            ),
            "missing_monthly_change_count": sum(
                stock.price_change_1m is None for stock in stocks
            ),
            "missing_rs_count": sum(stock.rs_rating is None for stock in stocks),
        },
    ).model_dump(mode="json")
