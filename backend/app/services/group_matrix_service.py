"""Read-only publication selection and Group Matrix assembly."""

from app.domain.feature_store.run_metadata import feature_run_market
from app.infra.db.models.feature_store import FeatureRun
from app.schemas.group_matrix import GroupMatrixResponse
from app.services.feature_run_rs_identity import (
    FeatureRunRsIdentityError,
    resolve_feature_run_rs_identity,
)
from app.services.group_matrix_payloads import TIERS, build_group_matrix_payload
from app.services.group_matrix_repository import GroupMatrixRepository


class GroupMatrixService:
    def __init__(self, repository=None):
        self.repository = repository or GroupMatrixRepository()

    def build(self, db, *, market, generated_at, feature_run_id=None):
        run = (
            self.repository.latest_published_run(db, market=market)
            if feature_run_id is None
            else db.get(FeatureRun, feature_run_id)
        )
        metadata = {
            "market": market, "generated_at": generated_at, "metadata_read_at": generated_at
        }
        if run is None:
            return GroupMatrixResponse(
                **metadata, available=False, reason="no_published_run", tiers=TIERS
            ).model_dump(mode="json")
        try:
            if run.status != "published" or feature_run_market(run) != market:
                raise FeatureRunRsIdentityError(
                    "Publication is not published for this market"
                )
            identity = resolve_feature_run_rs_identity(run, ranking_date=run.as_of_date)
            rows = self.repository.load_rows(db, run_id=run.id, market=market)
            if any(row["feature_as_of_date"] != run.as_of_date for row in rows):
                raise FeatureRunRsIdentityError(
                    "Feature dates do not match publication"
                )
            metadata.update(
                feature_run_id=run.id,
                as_of_date=run.as_of_date.isoformat(),
                rs_formula_version=identity.identity.formula_version,
                market_rs_run_id=identity.market_rs_run_id,
                rs_universe_size=identity.universe_size,
            )
            return build_group_matrix_payload(
                rows=rows,
                metadata=metadata,
                universe_count=self.repository.universe_count(db, run_id=run.id),
            )
        except (FeatureRunRsIdentityError, ValueError):
            return GroupMatrixResponse(
                **metadata,
                available=False,
                reason="publication_identity_mismatch",
                tiers=TIERS,
            ).model_dump(mode="json")
