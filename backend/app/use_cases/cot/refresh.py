from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.domain.cot.calculations import derive_all_instrument_series
from app.domain.cot.registry import COT_INSTRUMENTS
from app.domain.cot.validation import validate_cot_snapshot
from app.use_cases.cot.ports import CotRunRequest, CotSource


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
    ) -> "CotRefreshResult":
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
        repository: Any,
        price_hydrator: Any,
        cache_invalidator: Callable[[], None] | None = None,
    ) -> None:
        self._source = source
        self._repository = repository
        self._price_hydrator = price_hydrator
        self._cache_invalidator = cache_invalidator or (lambda: None)

    def execute(self, command: CotRefreshCommand) -> CotRefreshResult:
        run_id = self._repository.start_run(command.to_run_request())
        try:
            source_snapshot = self._source.fetch(COT_INSTRUMENTS)
            raw_weeks = source_snapshot.weeks
            validation = validate_cot_snapshot(
                raw_weeks,
                COT_INSTRUMENTS,
                self._repository.existing_week_keys(),
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
            report_date = max((week.report_date for week in raw_weeks), default=None)
            instrument_count = len({week.instrument_slug for week in raw_weeks})
            if (
                not command.force
                and fingerprints == self._repository.stored_fingerprints()
            ):
                self._repository.mark_no_change(run_id, validation.as_dict())
                return CotRefreshResult(
                    status="no_change",
                    run_id=run_id,
                    report_date=report_date,
                    instrument_count=instrument_count,
                    price_unavailable_count=0,
                )

            derived = derive_all_instrument_series(raw_weeks)
            price_result = self._price_hydrator.hydrate(COT_INSTRUMENTS)
            self._repository.publish(
                run_id,
                registry=COT_INSTRUMENTS,
                weeks=derived,
                diagnostics={
                    "validation": validation.as_dict(),
                    "prices": price_result.as_dict(),
                },
                source_metadata=source_snapshot.metadata.as_dict(),
            )
            self._cache_invalidator()
            return CotRefreshResult(
                status="published",
                run_id=run_id,
                report_date=report_date,
                instrument_count=instrument_count,
                price_unavailable_count=int(price_result.unavailable_count),
            )
        except Exception as exc:
            self._repository.mark_failed(
                run_id,
                "failed_fetch",
                {"exception_type": type(exc).__name__},
            )
            raise
