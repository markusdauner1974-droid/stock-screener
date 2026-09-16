from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.domain.cot.models import (
    CotInstrumentDefinition,
    NormalizedCotWeek,
    Participant,
    RawParticipantPosition,
    ReportFamily,
)
from app.use_cases.cot.ports import CotSourceMetadata, CotSourceSnapshot


DATASET_BY_FAMILY = {
    ReportFamily.DISAGGREGATED_FUTURES_ONLY: "72hh-3qpy",
    ReportFamily.TFF_FUTURES_ONLY: "gpe5-46if",
}

DISAGGREGATED_FIELDS = {
    Participant.PRODUCER_MERCHANT: (
        "prod_merc_positions_long",
        "prod_merc_positions_short",
        None,
    ),
    Participant.SWAP_DEALER: (
        "swap_positions_long_all",
        "swap__positions_short_all",
        "swap__positions_spread_all",
    ),
    Participant.MANAGED_MONEY: (
        "m_money_positions_long_all",
        "m_money_positions_short_all",
        "m_money_positions_spread",
    ),
    Participant.OTHER_REPORTABLES: (
        "other_rept_positions_long",
        "other_rept_positions_short",
        "other_rept_positions_spread",
    ),
    Participant.NONREPORTABLES: (
        "nonrept_positions_long_all",
        "nonrept_positions_short_all",
        None,
    ),
}

TFF_FIELDS = {
    Participant.DEALER_INTERMEDIARY: (
        "dealer_positions_long_all",
        "dealer_positions_short_all",
        "dealer_positions_spread_all",
    ),
    Participant.ASSET_MANAGER: (
        "asset_mgr_positions_long",
        "asset_mgr_positions_short",
        "asset_mgr_positions_spread",
    ),
    Participant.LEVERAGED_FUNDS: (
        "lev_money_positions_long",
        "lev_money_positions_short",
        "lev_money_positions_spread",
    ),
    Participant.OTHER_REPORTABLES: (
        "other_rept_positions_long",
        "other_rept_positions_short",
        "other_rept_positions_spread",
    ),
    Participant.NONREPORTABLES: (
        "nonrept_positions_long_all",
        "nonrept_positions_short_all",
        None,
    ),
}

_FIELDS_BY_FAMILY = {
    ReportFamily.DISAGGREGATED_FUTURES_ONLY: DISAGGREGATED_FIELDS,
    ReportFamily.TFF_FUTURES_ONLY: TFF_FIELDS,
}
_TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})
_BASE_FIELDS = (
    "id",
    "report_date_as_yyyy_mm_dd",
    "cftc_contract_market_code",
    "open_interest_all",
    "tot_rept_positions_long_all",
    "tot_rept_positions_short",
    "futonly_or_combined",
)


class CftcCotError(RuntimeError):
    """Base error for official CFTC retrieval."""


class CftcCotSchemaError(CftcCotError):
    """The provider returned data outside the expected Futures Only contract."""


class CftcCotSource:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        page_size: int = 50_000,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self._client = client or httpx.Client(
            base_url="https://publicreporting.cftc.gov",
            timeout=30.0,
        )
        self._page_size = page_size
        self._sleep = sleeper
        self._now = now or (lambda: datetime.now(timezone.utc))

    def fetch(
        self,
        instruments: Sequence[CotInstrumentDefinition],
    ) -> CotSourceSnapshot:
        definitions = tuple(instruments)
        by_family: dict[ReportFamily, list[CotInstrumentDefinition]] = defaultdict(list)
        seen_codes: set[str] = set()
        for definition in definitions:
            if definition.cftc_code in seen_codes:
                raise ValueError(f"duplicate CFTC code: {definition.cftc_code}")
            seen_codes.add(definition.cftc_code)
            by_family[definition.report_family].append(definition)

        weeks: list[NormalizedCotWeek] = []
        row_counts: dict[str, int] = {}
        retry_count = 0
        for family in ReportFamily:
            family_instruments = by_family.get(family, [])
            if not family_instruments:
                continue
            dataset_id = DATASET_BY_FAMILY[family]
            rows, family_retries = self._fetch_dataset(
                dataset_id,
                family,
                family_instruments,
            )
            retry_count += family_retries
            row_counts[dataset_id] = len(rows)
            instruments_by_code = {
                definition.cftc_code: definition for definition in family_instruments
            }
            weeks.extend(
                self._normalize_row(
                    row,
                    dataset_id=dataset_id,
                    family=family,
                    instruments_by_code=instruments_by_code,
                )
                for row in rows
            )

        return CotSourceSnapshot(
            weeks=tuple(
                sorted(weeks, key=lambda week: (week.report_date, week.instrument_slug))
            ),
            metadata=CotSourceMetadata(
                retrieved_at=self._now(),
                retry_count=retry_count,
                dataset_row_counts=row_counts,
            ),
        )

    def _fetch_dataset(
        self,
        dataset_id: str,
        family: ReportFamily,
        instruments: Sequence[CotInstrumentDefinition],
    ) -> tuple[list[Mapping[str, Any]], int]:
        rows: list[Mapping[str, Any]] = []
        retries = 0
        offset = 0
        while True:
            page, page_retries = self._request_page(
                dataset_id,
                family,
                instruments,
                offset=offset,
            )
            retries += page_retries
            rows.extend(page)
            if len(page) < self._page_size:
                return rows, retries
            offset += self._page_size

    def _request_page(
        self,
        dataset_id: str,
        family: ReportFamily,
        instruments: Sequence[CotInstrumentDefinition],
        *,
        offset: int,
    ) -> tuple[list[Mapping[str, Any]], int]:
        params = {
            "$select": ",".join(self._selected_fields(family)),
            "$where": self._where_clause(instruments),
            "$order": "report_date_as_yyyy_mm_dd ASC,cftc_contract_market_code ASC",
            "$limit": str(self._page_size),
            "$offset": str(offset),
        }
        retries = 0
        for attempt in range(4):
            try:
                response = self._client.get(f"/resource/{dataset_id}.json", params=params)
            except httpx.TimeoutException as exc:
                if attempt == 3:
                    raise CftcCotError("CFTC request timed out after retries") from exc
                retries += 1
                self._sleep(min(2.0**attempt, 60.0))
                continue

            if response.status_code in _TRANSIENT_STATUSES:
                if attempt == 3:
                    raise CftcCotError(
                        f"CFTC request failed after retries: {response.status_code}"
                    )
                retries += 1
                self._sleep(self._retry_delay(response, attempt))
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise CftcCotError(
                    f"CFTC request failed: {response.status_code}"
                ) from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise CftcCotSchemaError("CFTC response was not valid JSON") from exc
            if not isinstance(payload, list) or not all(
                isinstance(row, dict) for row in payload
            ):
                raise CftcCotSchemaError("CFTC response must be a list of rows")
            return payload, retries
        raise AssertionError("unreachable")

    @staticmethod
    def _selected_fields(family: ReportFamily) -> tuple[str, ...]:
        fields = list(_BASE_FIELDS)
        for long_field, short_field, spreading_field in _FIELDS_BY_FAMILY[family].values():
            fields.extend((long_field, short_field))
            if spreading_field is not None:
                fields.append(spreading_field)
        return tuple(dict.fromkeys(fields))

    @staticmethod
    def _where_clause(instruments: Sequence[CotInstrumentDefinition]) -> str:
        codes = ",".join(f"'{definition.cftc_code}'" for definition in instruments)
        return (
            f"cftc_contract_market_code in ({codes}) "
            "AND futonly_or_combined = 'FutOnly'"
        )

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), 60.0)
            except ValueError:
                pass
        return min(2.0**attempt, 60.0)

    @staticmethod
    def _normalize_row(
        row: Mapping[str, Any],
        *,
        dataset_id: str,
        family: ReportFamily,
        instruments_by_code: Mapping[str, CotInstrumentDefinition],
    ) -> NormalizedCotWeek:
        if row.get("futonly_or_combined") != "FutOnly":
            raise CftcCotSchemaError("CFTC row is not FutOnly")
        code = _required_text(row, "cftc_contract_market_code")
        definition = instruments_by_code.get(code)
        if definition is None:
            raise CftcCotSchemaError(f"unexpected CFTC contract code: {code}")
        positions = tuple(
            RawParticipantPosition(
                participant=participant,
                long=_contract_count(row, long_field),
                short=_contract_count(row, short_field),
                spreading=(
                    _contract_count(row, spreading_field)
                    if spreading_field is not None
                    else 0
                ),
            )
            for participant, (
                long_field,
                short_field,
                spreading_field,
            ) in _FIELDS_BY_FAMILY[family].items()
        )
        report_date = _report_date(row)
        source_row_id = _required_text(row, "id")
        open_interest = _contract_count(row, "open_interest_all")
        reported_long_total = _contract_count(
            row, "tot_rept_positions_long_all"
        )
        reported_short_total = _contract_count(row, "tot_rept_positions_short")
        canonical = {
            "dataset_id": dataset_id,
            "source_row_id": source_row_id,
            "report_date": report_date.isoformat(),
            "cftc_code": code,
            "open_interest": open_interest,
            "reported_long_total": reported_long_total,
            "reported_short_total": reported_short_total,
            "positions": [
                {
                    "participant": position.participant.value,
                    "long": position.long,
                    "short": position.short,
                    "spreading": position.spreading,
                }
                for position in positions
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return NormalizedCotWeek(
            source_dataset_id=dataset_id,
            source_row_id=source_row_id,
            source_fingerprint=fingerprint,
            instrument_slug=definition.slug,
            report_date=report_date,
            open_interest=open_interest,
            reported_long_total=reported_long_total,
            reported_short_total=reported_short_total,
            positions=positions,
        )


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CftcCotSchemaError(f"missing or invalid field: {field}")
    return value.strip()


def _contract_count(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool):
        raise CftcCotSchemaError(f"invalid contract count: {field}")
    try:
        parsed = int(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise CftcCotSchemaError(f"invalid contract count: {field}") from exc
    if parsed < 0:
        raise CftcCotSchemaError(f"negative contract count: {field}")
    return parsed


def _report_date(row: Mapping[str, Any]) -> date:
    value = _required_text(row, "report_date_as_yyyy_mm_dd")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise CftcCotSchemaError("invalid report date") from exc
