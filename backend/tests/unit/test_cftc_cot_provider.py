from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from app.domain.cot.registry import instrument_by_slug
from app.infra.providers.cftc_cot import CftcCotSchemaError, CftcCotSource

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures"


def load_fixture(name: str) -> list[dict[str, str]]:
    return json.loads((FIXTURE_ROOT / name).read_text())


def source_with_rows(
    rows: list[dict[str, str]],
    *,
    statuses: tuple[int, ...] = (200,),
    page_size: int = 50_000,
    requests: list[httpx.Request] | None = None,
    sleeps: list[float] | None = None,
) -> CftcCotSource:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if requests is not None:
            requests.append(request)
        status = statuses[min(calls, len(statuses) - 1)]
        calls += 1
        payload = (
            [{"count": str(len(rows))}]
            if request.url.params.get("$select") == "count(*) as count"
            else rows
        )
        return httpx.Response(
            status,
            headers={"Retry-After": "120"} if status == 503 else None,
            json=payload if status == 200 else {"error": "temporary"},
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://publicreporting.cftc.gov",
    )
    return CftcCotSource(
        client=client,
        page_size=page_size,
        sleeper=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_disaggregated_fields_normalize_to_five_participants():
    source = source_with_rows(load_fixture("cot/disaggregated_wheat.json"))

    week = source.fetch((instrument_by_slug("wheat-srw"),)).weeks[0]

    assert week.source_dataset_id == "72hh-3qpy"
    assert week.open_interest == 316244
    assert [
        (p.participant.value, p.long, p.short, p.spreading) for p in week.positions
    ] == [
        ("producer_merchant", 37353, 85943, 0),
        ("swap_dealer", 76373, 16895, 14058),
        ("managed_money", 65114, 84004, 38692),
        ("other_reportables", 30693, 12528, 25980),
        ("nonreportables", 27981, 38144, 0),
    ]


def test_tff_fields_normalize_to_five_financial_participants():
    source = source_with_rows(load_fixture("cot/tff_ust10y.json"))

    week = source.fetch((instrument_by_slug("ust-10y"),)).weeks[0]

    assert week.source_dataset_id == "gpe5-46if"
    assert [position.participant.value for position in week.positions] == [
        "dealer_intermediary",
        "asset_manager",
        "leveraged_funds",
        "other_reportables",
        "nonreportables",
    ]
    assert week.positions[2].long == 900000


def test_source_paginates_until_a_short_page():
    base = load_fixture("cot/disaggregated_wheat.json")[0]
    requested_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$select") == "count(*) as count":
            return httpx.Response(200, json=[{"count": "5"}])
        offset = int(request.url.params["$offset"])
        requested_offsets.append(offset)
        length = {0: 2, 2: 2, 4: 1}[offset]
        rows = []
        for index in range(length):
            row = deepcopy(base)
            row["id"] = f"row-{offset + index}"
            row["report_date_as_yyyy_mm_dd"] = (
                f"2026-08-{offset + index + 1:02d}T00:00:00.000"
            )
            row["cftc_contract_market_code"] = "088691"
            rows.append(row)
        return httpx.Response(200, json=rows)

    source = CftcCotSource(
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://publicreporting.cftc.gov",
        ),
        page_size=2,
    )

    assert len(source.fetch((instrument_by_slug("gold"),)).weeks) == 5
    assert requested_offsets == [0, 2, 4]


def test_full_history_query_has_no_report_date_cutoff():
    requests: list[httpx.Request] = []
    source = source_with_rows(
        load_fixture("cot/disaggregated_wheat.json"), requests=requests
    )

    source.fetch((instrument_by_slug("wheat-srw"),))

    where = requests[0].url.params["$where"]
    assert "report_date_as_yyyy_mm_dd" not in where
    assert "futonly_or_combined = 'FutOnly'" in where


def test_source_records_authoritative_count_for_the_exact_curated_query():
    requests: list[httpx.Request] = []
    source = source_with_rows(
        load_fixture("cot/disaggregated_wheat.json"), requests=requests
    )

    result = source.fetch((instrument_by_slug("wheat-srw"),))

    count_request = next(
        request
        for request in requests
        if request.url.params.get("$select") == "count(*) as count"
    )
    assert result.metadata.expected_dataset_row_counts == {"72hh-3qpy": 1}
    assert count_request.url.params["$where"] == requests[0].url.params["$where"]


def test_source_retries_transient_responses_and_records_retry_count():
    sleeps: list[float] = []
    source = source_with_rows(
        load_fixture("cot/disaggregated_wheat.json"),
        statuses=(503, 200),
        sleeps=sleeps,
    )

    result = source.fetch((instrument_by_slug("wheat-srw"),))

    assert result.metadata.retry_count == 1
    assert sleeps == [60.0]


@pytest.mark.parametrize(
    ("select", "expected_payload"),
    [
        ("id", load_fixture("cot/disaggregated_wheat.json")),
        ("count(*) as count", [{"count": "1"}]),
    ],
)
def test_page_and_count_share_one_request_retry_operation(select, expected_payload):
    sleeps: list[float] = []
    source = source_with_rows(
        load_fixture("cot/disaggregated_wheat.json"),
        statuses=(503, 503, 200),
        sleeps=sleeps,
    )

    payload, retries = source._request_json(
        "72hh-3qpy",
        {"$select": select},
        operation="test",
    )

    assert payload == expected_payload
    assert retries == 2
    assert sleeps == [60.0, 60.0]


def test_source_rejects_a_combined_row_even_if_the_provider_returns_it():
    row = load_fixture("cot/tff_ust10y.json")[0]
    row["futonly_or_combined"] = "Combined"

    with pytest.raises(CftcCotSchemaError, match="FutOnly"):
        source_with_rows([row]).fetch((instrument_by_slug("ust-10y"),))
