"""Strict live/static contracts for published COT data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.cot.models import Participant
from app.domain.cot.registry import PARTICIPANT_LABELS


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, from_attributes=True)


class CotPublicationMetadataResponse(_StrictModel):
    schema_version: Literal["cot-v1"]
    calculation_version: Literal["cot-positions-v1"]
    registry_version: str = Field(min_length=1)
    publication_id: int = Field(gt=0)
    report_date: date
    retrieved_at: datetime
    stale: bool


class CotSourceResponse(_StrictModel):
    dataset_id: Literal["72hh-3qpy", "gpe5-46if"]
    label: str = Field(min_length=1)
    url: str = Field(min_length=1)


class CotParticipantMetadataResponse(_StrictModel):
    value: str
    label: str


class CotCatalogInstrumentResponse(_StrictModel):
    slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    category_order: int = Field(ge=0)
    instrument_order: int = Field(ge=0)
    report_family: Literal["disaggregated_futures_only", "tff_futures_only"]
    focal_participant: str
    participants: list[CotParticipantMetadataResponse]
    price_symbol: str | None
    price_mapping_kind: Literal["exact_future", "etf_proxy", "index_proxy", "unavailable"]
    tradingview_url: str | None


class CotCatalogResponse(_StrictModel):
    publication: CotPublicationMetadataResponse
    default_slug: Literal["sp-500"]
    categories: list[str]
    sources: list[CotSourceResponse]
    instruments: list[CotCatalogInstrumentResponse]

    @classmethod
    def from_view(cls, view: Any) -> "CotCatalogResponse":
        return cls(
            publication=view.publication,
            default_slug=view.default_slug,
            categories=list(view.categories),
            sources=list(view.sources),
            instruments=[
                {
                    **{
                        key: getattr(item, key)
                        for key in (
                            "slug",
                            "display_name",
                            "category",
                            "category_order",
                            "instrument_order",
                            "report_family",
                            "focal_participant",
                            "price_symbol",
                            "price_mapping_kind",
                            "tradingview_url",
                        )
                    },
                    "participants": [
                        {
                            "value": value,
                            "label": PARTICIPANT_LABELS[Participant(value)],
                        }
                        for value in item.participants
                    ],
                }
                for item in view.instruments
            ],
        )

    @model_validator(mode="after")
    def validate_catalog(self):
        slugs = [item.slug for item in self.instruments]
        if len(slugs) != len(set(slugs)):
            raise ValueError("duplicate COT instrument slug")
        orders = [item.instrument_order for item in self.instruments]
        if orders != sorted(orders):
            raise ValueError("COT instruments must remain in curated order")
        if self.default_slug not in slugs:
            raise ValueError("default COT instrument is absent")
        return self


class CotPositionResponse(_StrictModel):
    participant: str
    label: str
    long: int = Field(ge=0)
    short: int = Field(ge=0)
    spreading: int = Field(ge=0)
    net: int
    delta_long: int | None
    delta_short: int | None
    delta_net: int | None
    net_pct_open_interest: float | None
    percentile_3y: float | None = Field(default=None, ge=0, le=100)
    percentile_status: Literal["available", "insufficient_history"]

    @model_validator(mode="after")
    def validate_position(self):
        try:
            participant = Participant(self.participant)
        except ValueError as exc:
            raise ValueError("unknown COT participant") from exc
        if self.label != PARTICIPANT_LABELS[participant]:
            raise ValueError("participant label mismatch")
        if (self.percentile_3y is not None) != (self.percentile_status == "available"):
            raise ValueError("percentile availability mismatch")
        return self


class CotHistoryWeekResponse(_StrictModel):
    report_date: date
    open_interest: int = Field(ge=0)
    price_date: date | None
    price_close: float | None
    price_change_pct: float | None
    positions: list[CotPositionResponse]

    @model_validator(mode="after")
    def validate_week(self):
        participants = [position.participant for position in self.positions]
        if len(participants) != len(set(participants)):
            raise ValueError("duplicate participant in COT week")
        if (self.price_date is None) != (self.price_close is None):
            raise ValueError("price date/value availability mismatch")
        if self.price_date is not None and self.price_date > self.report_date:
            raise ValueError("price date cannot follow report date")
        return self


class CotHistoryResponse(_StrictModel):
    publication: CotPublicationMetadataResponse
    range: Literal["1y", "3y", "5y"]
    slug: str
    display_name: str
    category: str
    report_family: Literal["disaggregated_futures_only", "tff_futures_only"]
    source_dataset_id: Literal["72hh-3qpy", "gpe5-46if"]
    focal_participant: str
    price_symbol: str | None
    price_mapping_kind: Literal["exact_future", "etf_proxy", "index_proxy", "unavailable"]
    price_coverage_state: Literal["complete", "partial", "unavailable"]
    price_history_start: date | None
    tradingview_url: str | None
    weeks: list[CotHistoryWeekResponse]

    @classmethod
    def from_view(cls, view: Any) -> "CotHistoryResponse":
        return cls.model_validate(view, from_attributes=True)

    @model_validator(mode="after")
    def validate_history(self):
        dates = [week.report_date for week in self.weeks]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("COT report weeks must be unique and ascending")
        if self.price_mapping_kind == "unavailable" and self.price_symbol is not None:
            raise ValueError("unavailable price mapping cannot have a symbol")
        if self.price_coverage_state == "unavailable" and any(
            week.price_close is not None for week in self.weeks
        ):
            raise ValueError("unavailable price coverage cannot contain values")
        if self.price_coverage_state == "complete" and any(
            week.price_close is None for week in self.weeks
        ):
            raise ValueError("complete price coverage requires every value")
        return self


class CotSnapshotRowResponse(_StrictModel):
    slug: str
    display_name: str
    category: str
    instrument_order: int = Field(ge=0)
    focal_participant: str
    focal_label: str
    report_date: date
    long: int = Field(ge=0)
    short: int = Field(ge=0)
    net: int
    delta_long: int | None
    delta_short: int | None
    delta_net: int | None
    net_pct_open_interest: float | None
    percentile_3y: float | None = Field(default=None, ge=0, le=100)
    percentile_status: Literal["available", "insufficient_history"]
    net_trend: list[int] = Field(max_length=12)
    price_change_pct: float | None
    price_mapping_kind: Literal["exact_future", "etf_proxy", "index_proxy", "unavailable"]
    price_coverage_state: Literal["complete", "partial", "unavailable"]


class CotSnapshotResponse(_StrictModel):
    publication: CotPublicationMetadataResponse
    rows: list[CotSnapshotRowResponse]

    @classmethod
    def from_view(cls, view: Any) -> "CotSnapshotResponse":
        return cls.model_validate(view, from_attributes=True)

    @model_validator(mode="after")
    def validate_rows(self):
        slugs = [row.slug for row in self.rows]
        if len(slugs) != len(set(slugs)):
            raise ValueError("duplicate COT snapshot row")
        if [row.instrument_order for row in self.rows] != sorted(
            row.instrument_order for row in self.rows
        ):
            raise ValueError("COT snapshot rows must remain in curated order")
        return self
