"""Relational persistence models for canonical COT history."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class CotInstrument(Base):
    __tablename__ = "cot_instruments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(80), nullable=False, unique=True)
    cftc_code = Column(String(16), nullable=False, unique=True)
    display_name = Column(String(120), nullable=False)
    category = Column(String(40), nullable=False)
    category_order = Column(Integer, nullable=False)
    instrument_order = Column(Integer, nullable=False)
    report_family = Column(String(48), nullable=False)
    focal_participant = Column(String(40), nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    registry_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CotImportRun(Base):
    __tablename__ = "cot_import_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    origin = Column(String(48), nullable=False)
    status = Column(String(32), nullable=False, index=True)
    requested_report_date = Column(Date, nullable=True)
    observed_report_date = Column(Date, nullable=True, index=True)
    expected_instrument_count = Column(Integer, nullable=False, default=0)
    observed_instrument_count = Column(Integer, nullable=False, default=0)
    coverage_json = Column(JSON, nullable=True)
    diagnostics_json = Column(JSON, nullable=True)
    source_metadata_json = Column(JSON, nullable=True)
    registry_version = Column(String(64), nullable=False)
    calculation_version = Column(String(64), nullable=False)
    schema_version = Column(String(64), nullable=False)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)


class CotWeeklyPosition(Base):
    __tablename__ = "cot_weekly_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instrument_id = Column(
        Integer,
        ForeignKey("cot_instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    report_date = Column(Date, nullable=False)
    participant = Column(String(40), nullable=False)
    long = Column(BigInteger, nullable=False)
    short = Column(BigInteger, nullable=False)
    spreading = Column(BigInteger, nullable=False)
    open_interest = Column(BigInteger, nullable=False)
    net = Column(BigInteger, nullable=False)
    delta_long = Column(BigInteger, nullable=True)
    delta_short = Column(BigInteger, nullable=True)
    delta_net = Column(BigInteger, nullable=True)
    net_pct_open_interest = Column(Float, nullable=True)
    percentile_3y = Column(Float, nullable=True)
    percentile_status = Column(String(32), nullable=False)
    source_dataset_id = Column(String(16), nullable=False)
    source_row_id = Column(String(160), nullable=False)
    source_fingerprint = Column(String(64), nullable=False)
    import_run_id = Column(
        Integer,
        ForeignKey("cot_import_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "report_date",
            "participant",
            name="uq_cot_weekly_position",
        ),
        Index("ix_cot_weekly_instrument_date", "instrument_id", "report_date"),
    )


class CotPublicationPointer(Base):
    __tablename__ = "cot_publication_pointers"

    key = Column(String(64), primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("cot_import_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    report_date = Column(Date, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
