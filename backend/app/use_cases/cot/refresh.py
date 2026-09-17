from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.cot.calculations import derive_all_instrument_series
from app.domain.cot.registry import COT_INSTRUMENTS
from app.domain.cot.validation import validate_cot_snapshot
from app.use_cases.cot.ports import (
    CotPriceHydratorPort,
    CotPublicationSignature,
    CotRunRequest,
    CotSource,
    CotWriteRepository,
)


@dataclass(frozen=True)
class CotRefreshCommand:
    origin: str
    force: bool = False
    requested_report_date: date | None = None

    def to_run_request(self) -> CotRunRequest:
        return CotRunRequest(
            origin=self.origin,
            expected_instrument_count=len(COT_INSTRUMENTS),
            requested_report_date=self.requested_report_date,
        )


@dataclass(frozen=True)
class CotRefreshResult:
    status: str
    run_id: int
    report_date: date | None
    instrument_count: int
    price_unavailable_count: int
    reason_codes: tuple[str, ...] = ()

    @classmethod
    def failed(
        cls,
        run_id: int,
        reason_codes: tuple[str, ...],
    ) -> CotRefreshResult:
        return cls(
            status="failed_quality",
            run_id=run_id,
            report_date=None,
            instrument_count=0,
            price_unavailable_count=0,
            reason_codes=reason_codes,
        )


class RefreshCotUseCase:
    def __init__(
        self,
        *,
        source: CotSource,
        repository: CotWriteRepository,
        price_hydrator: CotPriceHydratorPort,
    ) -> None:
        self._source = source
        self._repository = repository
        self._price_hydrator = price_hydrator

    def execute(self, command: CotRefreshCommand) -> CotRefreshResult:
        run_request = command.to_run_request()
        run_id = self._repository.start_run(run_request)
        failure_status = "failed_fetch"
        try:
            source_snapshot = self._source.fetch(COT_INSTRUMENTS)
            raw_weeks = source_snapshot.weeks
            failure_status = "failed_validation"
            validation = validate_cot_snapshot(
                raw_weeks,
                COT_INSTRUMENTS,
                self._repository.existing_week_keys(
                    tuple(item.slug for item in COT_INSTRUMENTS)
                ),
                source_snapshot.metadata.expected_dataset_row_counts,
            )
            if not validation.valid:
                self._repository.mark_failed(
                    run_id,
                    "failed_quality",
                    validation.as_dict(),
                )
                return CotRefreshResult.failed(run_id, validation.reason_codes)

            fingerprints = {
                week.source_row_id: week.source_fingerprint for week in raw_weeks
            }
            requested_signature = CotPublicationSignature(
                source_fingerprints=fingerprints,
                registry_version=run_request.registry_version,
                calculation_version=run_request.calculation_version,
                schema_version=run_request.schema_version,
            )
            report_date = max((week.report_date for week in raw_weeks), default=None)
            instrument_count = len({week.instrument_slug for week in raw_weeks})
            if (
                not command.force
                and requested_signature == self._repository.publication_signature()
            ):
                failure_status = "failed_price_hydration"
                price_result = self._price_hydrator.hydrate(
                    COT_INSTRUMENTS,
                    report_date=report_date,
                )
                self._repository.mark_no_change(
                    run_id,
                    {
                        "validation": validation.as_dict(),
                        "prices": price_result.as_dict(),
                    },
                )
                return CotRefreshResult(
                    status="no_change",
                    run_id=run_id,
                    report_date=report_date,
                    instrument_count=instrument_count,
                    price_unavailable_count=int(price_result.unavailable_count),
                )

            failure_status = "failed_calculation"
            derived = derive_all_instrument_series(raw_weeks)
            failure_status = "failed_price_hydration"
            price_result = self._price_hydrator.hydrate(
                COT_INSTRUMENTS,
                report_date=report_date,
            )
            failure_status = "failed_publish"
            published = self._repository.publish(
                run_id,
                registry=COT_INSTRUMENTS,
                weeks=derived,
                diagnostics={
                    "validation": validation.as_dict(),
                    "prices": price_result.as_dict(),
                },
                source_metadata=source_snapshot.metadata.as_dict(),
            )
            return CotRefreshResult(
                status="published" if published else "superseded",
                run_id=run_id,
                report_date=report_date,
                instrument_count=instrument_count,
                price_unavailable_count=int(price_result.unavailable_count),
            )
        except Exception as exc:
            self._repository.mark_failed(
                run_id,
                failure_status,
                {"exception_type": type(exc).__name__},
            )
            raise
