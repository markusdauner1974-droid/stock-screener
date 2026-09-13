"""Bulk read of daily features and explicitly identified IBD metadata."""

from sqlalchemy import and_, func

from app.domain.feature_store.run_metadata import feature_run_market
from app.infra.db.models.feature_store import (
    FeatureRun,
    FeatureRunPointer,
    FeatureRunUniverseSymbol,
    StockFeatureDaily,
)
from app.models.industry import IBDIndustryGroup
from app.models.stock import StockFundamental
from app.models.stock_universe import StockUniverse


class GroupMatrixRepository:
    def latest_published_run(self, db, *, market):
        pointer = db.get(FeatureRunPointer, f"latest_published_market:{market}")
        if pointer:
            run = db.get(FeatureRun, pointer.run_id)
            if run and run.status == "published" and feature_run_market(run) == market:
                return run
        runs = (
            db.query(FeatureRun)
            .filter(FeatureRun.status == "published")
            .order_by(FeatureRun.published_at.desc(), FeatureRun.id.desc())
        )
        return next((run for run in runs if feature_run_market(run) == market), None)

    def universe_count(self, db, *, run_id):
        return (
            db.query(func.count(FeatureRunUniverseSymbol.symbol))
            .filter(FeatureRunUniverseSymbol.run_id == run_id)
            .scalar()
        )

    def load_rows(self, db, *, run_id, market):
        rows = (
            db.query(
                StockFeatureDaily.symbol,
                StockFeatureDaily.as_of_date,
                StockFeatureDaily.details_json,
                FeatureRunUniverseSymbol.symbol.label("member_symbol"),
                StockUniverse.name,
                StockUniverse.sector,
                StockFundamental.market_cap_usd,
                StockFundamental.updated_at,
                IBDIndustryGroup.industry_group,
                IBDIndustryGroup.source,
                IBDIndustryGroup.confidence,
                IBDIndustryGroup.updated_at,
            )
            .outerjoin(
                FeatureRunUniverseSymbol,
                and_(
                    FeatureRunUniverseSymbol.run_id == StockFeatureDaily.run_id,
                    FeatureRunUniverseSymbol.symbol == StockFeatureDaily.symbol,
                ),
            )
            .outerjoin(
                StockUniverse,
                and_(
                    StockUniverse.symbol == StockFeatureDaily.symbol,
                    StockUniverse.market == market,
                ),
            )
            .outerjoin(
                StockFundamental, StockFundamental.symbol == StockFeatureDaily.symbol
            )
            .outerjoin(
                IBDIndustryGroup,
                and_(
                    IBDIndustryGroup.symbol == StockFeatureDaily.symbol,
                    IBDIndustryGroup.market == market,
                ),
            )
            .filter(StockFeatureDaily.run_id == run_id)
            .all()
        )
        result = []
        for (
            symbol,
            as_of,
            details,
            member,
            name,
            sector,
            cap,
            cap_date,
            group,
            source,
            confidence,
            group_date,
        ) in rows:
            if member is None:
                raise ValueError(
                    "Matrix feature row is not a member of its publication"
                )
            details = details if isinstance(details, dict) else {}
            result.append(
                {
                    "symbol": symbol,
                    "feature_as_of_date": as_of,
                    "company_name": name,
                    "sector": details.get("gics_sector") or sector,
                    "ibd_industry_group": group,
                    "classification_source": source,
                    "classification_confidence": confidence,
                    "classification_updated_at": group_date,
                    "market_cap_usd": cap,
                    "fundamentals_updated_at": cap_date,
                    "price_change_1d": details.get("price_change_1d"),
                    "rs_rating": details.get("rs_rating"),
                }
            )
        return result
