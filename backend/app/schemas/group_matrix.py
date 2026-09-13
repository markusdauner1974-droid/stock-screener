"""Compact, shared live/static Group Matrix contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CapTier = Literal["large_mega", "mid", "small", "micro", "nano", "unknown"]


class MatrixStock(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    symbol: str
    company_name: str | None = None
    sector: str | None = None
    ibd_industry_group: str | None = None
    classification_source: str | None = None
    classification_confidence: float | None = Field(None, ge=0, le=1)
    classification_updated_at: str | None = None
    market_cap_usd: float | None = Field(None, gt=0)
    cap_tier: CapTier
    fundamentals_updated_at: str | None = None
    price_change_1d: float | None = None
    rs_rating: float | None = Field(None, ge=0, le=100)


class MatrixTier(BaseModel):
    id: CapTier
    label: str
    min_usd: float | None
    max_usd: float | None


class MatrixCoverage(BaseModel):
    universe_count: int = Field(0, ge=0)
    stock_count: int = Field(0, ge=0)
    missing_feature_count: int = Field(0, ge=0)
    ibd_mapped_count: int = Field(0, ge=0)
    unknown_sector_count: int = Field(0, ge=0)
    unknown_cap_count: int = Field(0, ge=0)
    missing_daily_change_count: int = Field(0, ge=0)
    missing_rs_count: int = Field(0, ge=0)


class GroupMatrixResponse(BaseModel):
    schema_version: Literal["group-matrix-v1"] = "group-matrix-v1"
    available: bool
    reason: (
        Literal[
            "no_published_run",
            "no_feature_rows",
            "publication_identity_mismatch",
            "missing_ibd_mappings",
        ]
        | None
    ) = None
    market: str
    feature_run_id: int | None = None
    as_of_date: str | None = None
    rs_formula_version: str | None = None
    market_rs_run_id: int | None = None
    rs_universe_size: int | None = None
    generated_at: str | None = None
    metadata_read_at: str | None = None
    metadata_basis: Literal["latest_stored"] = "latest_stored"
    taxonomy: Literal["ibd"] = "ibd"
    coverage: MatrixCoverage = Field(default_factory=MatrixCoverage)
    tiers: list[MatrixTier] = Field(default_factory=list)
    stocks: list[MatrixStock] = Field(default_factory=list)
