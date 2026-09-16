# COT Positioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add official CFTC Commitments of Traders history, derived positioning metrics, best-effort Yahoo price context, a live Daily tab with chart and table, and a chart-only Static Daily section.

**Architecture:** A versioned registry and pure domain calculator normalize the two official CFTC Futures Only datasets into one canonical PostgreSQL history. A staged refresh validates the full curated source selection, hydrates the existing Yahoo price cache independently, and advances one publication pointer atomically; live API responses and static artifacts are built from the same read models and Pydantic serializers. Shared React components render those contracts, while thin live and static containers provide their respective data clients.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, Celery, Redis, httpx, pandas, pytest, React 18, TanStack Query, Material UI, Recharts, Vitest, React Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-16-cot-positioning-design.md`

## Global Constraints

- Positioning source is CFTC Disaggregated Futures Only `72hh-3qpy` for physical commodities and TFF Futures Only `gpe5-46if` for financial futures.
- Never mix Futures-and-Options-Combined or Legacy COT rows into the feature.
- Backfill and retain complete official history from 2006 or each contract's later official inception; limit only served chart payloads to five years.
- The curated universe is exactly the 31 instruments and fixed category order in the specification.
- Focal participant is Managed Money for Disaggregated instruments and Leveraged Funds for TFF instruments.
- Store and expose long, short, spreading, open interest, net, weekly changes, net/open-interest percentage, and the three-year percentile.
- The percentile uses exactly 156 non-null weekly net observations, includes the current observation, applies the mid-rank tie formula, and reports `insufficient_history` before observation 156.
- Machine-readable prices come only from the existing Yahoo/price-cache boundary. TradingView is a display link only.
- Price failure never blocks a valid COT publication and missing values never render as zero.
- Align each price to the latest Yahoo close on or before the Tuesday CFTC report date; weekly price change is report Tuesday to report Tuesday.
- Live and static page reads never call CFTC, Yahoo, or TradingView.
- Live and static serializers must produce identical values for the same publication and range.
- Static mode remains valid when `assets.cot` is absent and never calls `/api`.
- Live placement is after Key Markets and before Themes in the vertical Daily rail. Static placement is after Market Health and before Top Scan Candidates.
- Default instrument is S&P 500, default chart range is 1Y, available ranges are 1Y/3Y/5Y, and the percentile methodology always remains three years.
- Preserve all unrelated working-tree changes. Each task stages only the files listed in its commit step.

## Scope and Dependency Order

This remains one plan because publication identity, serializer parity, and the shared chart contract cross all layers. Tasks 1-8 build a deployable backend and static artifact pipeline; Tasks 9-12 add the shared and mode-specific UI; Task 13 performs the release gate.

## File Map

### Domain and source ingestion

- Create `backend/app/domain/cot/models.py`: provider-neutral enums and immutable COT value objects.
- Create `backend/app/domain/cot/registry.py`: the exact 31-instrument registry, category ordering, participants, and price mappings.
- Create `backend/app/domain/cot/calculations.py`: net, deltas, percentile, and Tuesday price-alignment math.
- Create `backend/app/domain/cot/validation.py`: dataset identity, coverage, uniqueness, nonnegative-value, reconciliation, and truncation gates.
- Create `backend/app/use_cases/cot/ports.py`: source, repository, price-hydrator, and read-side protocols.
- Create `backend/app/infra/providers/cftc_cot.py`: paginated Socrata adapter and dataset-specific field maps.

### Persistence, refresh, and operations

- Create `backend/app/infra/db/models/cot.py`: instrument, weekly-position, import-run, and publication-pointer tables.
- Create `backend/app/infra/db/repositories/cot_repository.py`: registry synchronization, fingerprints, atomic upsert/publication, and published reads.
- Create `backend/alembic/versions/20260916_0045_add_cot_positioning.py`: database migration after `20260912_0044`.
- Create `backend/app/use_cases/cot/refresh.py`: fetch, normalize, validate, derive, hydrate, and publish orchestration.
- Create `backend/app/services/cot_price_hydrator.py`: best-effort use of the existing `PriceCacheService`.
- Create `backend/app/interfaces/tasks/cot_tasks.py`: Celery delivery boundary.
- Create `backend/app/scripts/backfill_cot.py`: initial administrative backfill command.
- Create `backend/app/services/cot_operations_service.py`: redacted import and publication health.
- Modify `backend/app/celery_app.py`: include, route, and schedule the COT refresh at 17:00 America/New_York on weekdays.
- Modify `backend/app/api/v1/operations.py`: expose `GET /api/v1/operations/cot`.
- Modify `backend/app/models/__init__.py` and `backend/app/infra/db/models/__init__.py`: register COT tables.
- Modify `backend/app/wiring/use_case_factories.py` and `backend/app/wiring/bootstrap.py`: compose refresh and query use cases.

### Read contracts and APIs

- Create `backend/app/use_cases/cot/queries.py`: published catalog, history, snapshot, and cached-price read models.
- Create `backend/app/schemas/cot.py`: strict Pydantic live/static contracts.
- Create `backend/app/services/cot_response_cache.py`: bounded memory/Redis JSON response cache keyed by publication.
- Create `backend/app/api/v1/cot.py`: protected catalog, history, and snapshot endpoints.
- Modify `backend/app/api/v1/router.py`: register `/v1/cot`.

### Static artifacts and publication workflow

- Create `backend/app/services/static_cot_contract.py`: static index validation and safe-path checks.
- Create `backend/app/services/static_cot_exporter.py`: atomic `cot/index.json` plus per-instrument history files.
- Create `backend/app/services/static_cot_artifact_selector.py`: current/last-good selection.
- Create `backend/app/services/static_cot_section.py`: direct and combined export composition.
- Modify `backend/app/services/static_site_manifest.py` and `backend/app/services/static_site_export_service.py`: advertise only root `assets.cot`.
- Modify `backend/app/tasks/static_export_tasks.py`: preserve the last-good `cot/` directory for server exports.
- Modify `backend/app/scripts/export_static_site.py`, `backend/app/scripts/download_static_market_fallbacks.py`, and `backend/app/scripts/validate_static_market_artifacts.py`: support current and fallback COT artifacts.
- Modify `.github/workflows/static-site.yml`: upload, download, validate, and combine the global COT artifact.

### Frontend

- Create `frontend/src/features/cot/cotContract.js`: semantic validation, range slicing, labels, and query keys.
- Create `frontend/src/api/cot.js`: live API client.
- Create `frontend/src/static/cotClient.js`: manifest-advertised static index/history client.
- Create `frontend/src/features/cot/CotSummaryStrip.jsx`: latest focal positioning summary.
- Create `frontend/src/features/cot/CotPositioningChart.jsx`: net and long/short modes, price overlay, and open-interest chart.
- Create `frontend/src/features/cot/CotPositioningView.jsx`: shared controls and chart composition.
- Create `frontend/src/features/cot/CotSnapshotTable.jsx`: sortable/filterable live table and net trend.
- Create `frontend/src/features/cot/CotPositioningTab.jsx`: live React Query container.
- Create `frontend/src/static/components/StaticCotSection.jsx`: static React Query container.
- Modify `frontend/src/pages/MarketScanPage.jsx`: lazy live tab placement.
- Modify `frontend/src/static/pages/StaticHomePage.jsx`: static section placement.

---

### Task 1: Pure COT Domain, Registry, and Calculations

**Files:**
- Create: `backend/app/domain/cot/__init__.py`
- Create: `backend/app/domain/cot/models.py`
- Create: `backend/app/domain/cot/registry.py`
- Create: `backend/app/domain/cot/calculations.py`
- Test: `backend/tests/unit/test_cot_registry.py`
- Test: `backend/tests/unit/test_cot_calculations.py`

**Interfaces:**
- Produces: `COT_INSTRUMENTS: tuple[CotInstrumentDefinition, ...]`, `instrument_by_slug(slug)`, `participants_for(report_family)`, `derive_position_series(weeks)`, `derive_all_instrument_series(weeks)`, `rolling_net_percentiles(values, window=156)`, and `align_prices_to_report_dates(report_dates, closes)`.
- Consumes: no database, provider, Celery, Redis, pandas, FastAPI, or frontend imports.

- [ ] **Step 1: Write the failing registry test**

```python
def test_registry_is_the_exact_curated_universe():
    assert len(COT_INSTRUMENTS) == 31
    assert [item.category.value for item in COT_INSTRUMENTS[:10]] == [
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "equity_volatility",
        "rates",
        "rates",
        "rates",
    ]
    assert [item.cftc_code for item in COT_INSTRUMENTS] == [
        "13874+", "20974+", "239742", "244041", "244042", "240743", "1170E1",
        "134742", "134741", "043602",
        "067651", "06765T", "023651", "111659", "022651",
        "098662", "097741", "133741", "146021",
        "088691", "084691", "085692", "076651", "075651",
        "002602", "001602", "005602", "135731", "083731", "073732", "058644",
    ]
    assert instrument_by_slug("sp-500").focal_participant is Participant.LEVERAGED_FUNDS
    assert instrument_by_slug("gold").focal_participant is Participant.MANAGED_MONEY
    assert instrument_by_slug("canola").price.yahoo_symbol is None
    assert instrument_by_slug("lumber").price.yahoo_symbol == "LBR=F"
```

- [ ] **Step 2: Run the registry test and verify the missing module failure**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_registry.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.cot'`.

- [ ] **Step 3: Add the domain enums and immutable records**

```python
COT_SCHEMA_VERSION = "cot-v1"
COT_CALCULATION_VERSION = "cot-positions-v1"
COT_REGISTRY_VERSION = "cot-curated-v1"
STATIC_COT_SCHEMA_VERSION = "static-cot-v1"


class ReportFamily(str, Enum):
    DISAGGREGATED_FUTURES_ONLY = "disaggregated_futures_only"
    TFF_FUTURES_ONLY = "tff_futures_only"


class Participant(str, Enum):
    PRODUCER_MERCHANT = "producer_merchant"
    SWAP_DEALER = "swap_dealer"
    MANAGED_MONEY = "managed_money"
    DEALER_INTERMEDIARY = "dealer_intermediary"
    ASSET_MANAGER = "asset_manager"
    LEVERAGED_FUNDS = "leveraged_funds"
    OTHER_REPORTABLES = "other_reportables"
    NONREPORTABLES = "nonreportables"


class PriceMappingKind(str, Enum):
    EXACT_FUTURE = "exact_future"
    ETF_PROXY = "etf_proxy"
    INDEX_PROXY = "index_proxy"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RawParticipantPosition:
    participant: Participant
    long: int
    short: int
    spreading: int


@dataclass(frozen=True)
class NormalizedCotWeek:
    source_dataset_id: str
    source_row_id: str
    source_fingerprint: str
    instrument_slug: str
    report_date: date
    open_interest: int
    reported_long_total: int
    reported_short_total: int
    positions: tuple[RawParticipantPosition, ...]
```

Add `Category`, `PriceMapping`, `CotInstrumentDefinition`, `DerivedParticipantPosition`, `DerivedCotWeek`, `AlignedPrice`, and `PriceCoverageState` in the same file. Enforce non-empty slugs/codes and nonnegative contract counts in `__post_init__`.

- [ ] **Step 4: Add the complete registry**

Use `CATEGORY_ORDER = (EQUITY_VOLATILITY, RATES, ENERGY, CURRENCIES, DIGITAL_ASSETS, METALS, GRAINS_OILSEEDS, SOFTS, LUMBER)` and define all entries in this exact order:

```python
_SPECS = (
    ("sp-500", "S&P 500", "13874+", "equity_volatility", "tff", "ES=F", "exact_future"),
    ("nasdaq-100", "Nasdaq-100", "20974+", "equity_volatility", "tff", "NQ=F", "exact_future"),
    ("russell-2000", "Russell 2000", "239742", "equity_volatility", "tff", "RTY=F", "exact_future"),
    ("msci-eafe", "MSCI EAFE", "244041", "equity_volatility", "tff", "EFA", "etf_proxy"),
    ("msci-em", "MSCI Emerging Markets", "244042", "equity_volatility", "tff", "EEM", "etf_proxy"),
    ("nikkei", "Nikkei", "240743", "equity_volatility", "tff", "NKD=F", "exact_future"),
    ("vix", "VIX", "1170E1", "equity_volatility", "tff", "^VIX", "index_proxy"),
    ("sofr-1m", "1-Month SOFR", "134742", "rates", "tff", "SGOV", "etf_proxy"),
    ("sofr-3m", "3-Month SOFR", "134741", "rates", "tff", "BIL", "etf_proxy"),
    ("ust-10y", "US Treasury 10-Year", "043602", "rates", "tff", "ZN=F", "exact_future"),
    ("wti-crude", "WTI Crude", "067651", "energy", "disaggregated", "CL=F", "exact_future"),
    ("brent-crude", "Brent Crude", "06765T", "energy", "disaggregated", "BZ=F", "exact_future"),
    ("henry-hub-natural-gas", "Henry Hub Natural Gas", "023651", "energy", "disaggregated", "NG=F", "exact_future"),
    ("rbob-gasoline", "RBOB Gasoline", "111659", "energy", "disaggregated", "RB=F", "exact_future"),
    ("ulsd-heating-oil", "ULSD / Heating Oil", "022651", "energy", "disaggregated", "HO=F", "exact_future"),
    ("usd-index", "US Dollar Index", "098662", "currencies", "tff", "DX-Y.NYB", "index_proxy"),
    ("japanese-yen", "Japanese Yen", "097741", "currencies", "tff", "6J=F", "exact_future"),
    ("bitcoin", "Bitcoin", "133741", "digital_assets", "tff", "BTC=F", "exact_future"),
    ("ether", "Ether", "146021", "digital_assets", "tff", "ETH=F", "exact_future"),
    ("gold", "Gold", "088691", "metals", "disaggregated", "GC=F", "exact_future"),
    ("silver", "Silver", "084691", "metals", "disaggregated", "SI=F", "exact_future"),
    ("copper", "Copper", "085692", "metals", "disaggregated", "HG=F", "exact_future"),
    ("platinum", "Platinum", "076651", "metals", "disaggregated", "PL=F", "exact_future"),
    ("palladium", "Palladium", "075651", "metals", "disaggregated", "PA=F", "exact_future"),
    ("corn", "Corn", "002602", "grains_oilseeds", "disaggregated", "ZC=F", "exact_future"),
    ("wheat-srw", "Wheat", "001602", "grains_oilseeds", "disaggregated", "ZW=F", "exact_future"),
    ("soybeans", "Soybeans", "005602", "grains_oilseeds", "disaggregated", "ZS=F", "exact_future"),
    ("canola", "Canola", "135731", "grains_oilseeds", "disaggregated", None, "unavailable"),
    ("coffee", "Coffee", "083731", "softs", "disaggregated", "KC=F", "exact_future"),
    ("cocoa", "Cocoa", "073732", "softs", "disaggregated", "CC=F", "exact_future"),
    ("lumber", "Lumber", "058644", "lumber", "disaggregated", "LBR=F", "exact_future"),
)
```

Set Canola's optional TradingView URL to `https://www.tradingview.com/symbols/ICEUS-RS1%21/contracts/`. Derive focal participant and participant list from report family, not from 31 repeated literals.

Use the exact display labels `Producer/Merchant/Processor/User`, `Swap Dealer`, `Managed Money`, `Dealer/Intermediary`, `Asset Manager/Institutional`, `Leveraged Funds`, `Other Reportables`, and `Non-reportables` from one `PARTICIPANT_LABELS` mapping.

- [ ] **Step 5: Run the registry test to verify it passes**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_registry.py -q`

Expected: PASS.

- [ ] **Step 6: Write failing calculation tests**

```python
def test_midrank_percentile_requires_exactly_156_values():
    values = tuple(range(155)) + (100,)
    result = rolling_net_percentiles(values)
    assert result[154] is None
    assert result[155] == pytest.approx(100 * (100 + 0.5 * 2) / 156)


def test_derivation_uses_long_minus_short_and_previous_report_week():
    weeks = (
        make_week("2026-09-01", long=120, short=80, open_interest=1000),
        make_week("2026-09-08", long=150, short=90, open_interest=1200),
    )
    current = derive_position_series(weeks)[1].positions[0]
    assert current.net == 60
    assert current.delta_long == 30
    assert current.delta_short == 10
    assert current.delta_net == 20
    assert current.net_pct_open_interest == pytest.approx(5.0)


def test_price_alignment_uses_latest_close_on_or_before_tuesday():
    aligned = align_prices_to_report_dates(
        (date(2026, 9, 1), date(2026, 9, 8)),
        {date(2026, 8, 31): 100.0, date(2026, 9, 8): 105.0},
    )
    assert aligned[0].price_date == date(2026, 8, 31)
    assert aligned[1].weekly_change_pct == pytest.approx(5.0)
```

- [ ] **Step 7: Run the calculation tests and verify the missing-function failures**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_calculations.py -q`

Expected: FAIL because the calculation functions do not exist.

- [ ] **Step 8: Implement the pure calculation functions**

```python
PERCENTILE_WINDOW = 156


def midrank_percentile(window: Sequence[int], current: int) -> float:
    below = sum(value < current for value in window)
    equal = sum(value == current for value in window)
    return 100.0 * (below + 0.5 * equal) / len(window)


def rolling_net_percentiles(
    values: Sequence[int | None],
    *,
    window: int = PERCENTILE_WINDOW,
) -> tuple[float | None, ...]:
    usable: deque[int] = deque(maxlen=window)
    output: list[float | None] = []
    for value in values:
        if value is not None:
            usable.append(value)
        output.append(
            midrank_percentile(tuple(usable), value)
            if value is not None and len(usable) == window
            else None
        )
    return tuple(output)
```

Implement `derive_position_series` by sorting one instrument's weeks by report date and maintaining previous values per participant. Implement `derive_all_instrument_series` by grouping on `instrument_slug`, calling that single-instrument function, and returning one date-sorted tuple. Implement `align_prices_to_report_dates` with a sorted price-date cursor and return `None` values when no earlier close exists.

- [ ] **Step 9: Run all Task 1 tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_registry.py tests/unit/test_cot_calculations.py -q`

Expected: PASS.

- [ ] **Step 10: Commit Task 1**

```bash
git add backend/app/domain/cot backend/tests/unit/test_cot_registry.py backend/tests/unit/test_cot_calculations.py
git commit -m "feat: add COT domain registry and calculations"
```

### Task 2: Official CFTC Adapters and Quality Gates

**Files:**
- Create: `backend/app/use_cases/cot/__init__.py`
- Create: `backend/app/use_cases/cot/ports.py`
- Create: `backend/app/infra/providers/cftc_cot.py`
- Create: `backend/app/domain/cot/validation.py`
- Create: `backend/tests/fixtures/cot/disaggregated_wheat.json`
- Create: `backend/tests/fixtures/cot/tff_ust10y.json`
- Test: `backend/tests/unit/test_cftc_cot_provider.py`
- Test: `backend/tests/unit/test_cot_validation.py`

**Interfaces:**
- Consumes: `CotInstrumentDefinition`, `NormalizedCotWeek`, and report-family participant lists from Task 1.
- Produces: `CftcCotSource.fetch(instruments) -> CotSourceSnapshot`, where the snapshot carries normalized weeks plus retrieval/retry metadata, and `validate_cot_snapshot(snapshot, instruments, existing_keys) -> CotValidationResult`.

- [ ] **Step 1: Save minimal official source fixtures**

The Disaggregated fixture contains the CFTC fields `id`, `report_date_as_yyyy_mm_dd`, `cftc_contract_market_code`, `open_interest_all`, `prod_merc_positions_long`, `prod_merc_positions_short`, `swap_positions_long_all`, `swap__positions_short_all`, `swap__positions_spread_all`, `m_money_positions_long_all`, `m_money_positions_short_all`, `m_money_positions_spread`, `other_rept_positions_long`, `other_rept_positions_short`, `other_rept_positions_spread`, `tot_rept_positions_long_all`, `tot_rept_positions_short`, `nonrept_positions_long_all`, `nonrept_positions_short_all`, and `futonly_or_combined`.

The TFF fixture contains the corresponding `dealer_positions_*`, `asset_mgr_positions_*`, `lev_money_positions_*`, `other_rept_positions_*`, total-reportable, nonreportable, and identity fields. Keep the original string-encoded numbers so parsing is tested.

- [ ] **Step 2: Write failing normalization and pagination tests**

```python
def test_disaggregated_fields_normalize_to_five_participants(load_fixture):
    source = source_with_rows(load_fixture("cot/disaggregated_wheat.json"))
    week = source.fetch((instrument_by_slug("wheat-srw"),)).weeks[0]
    assert week.source_dataset_id == "72hh-3qpy"
    assert week.open_interest == 316244
    assert [(p.participant.value, p.long, p.short, p.spreading) for p in week.positions] == [
        ("producer_merchant", 37353, 85943, 0),
        ("swap_dealer", 76373, 16895, 14058),
        ("managed_money", 65114, 84004, 38692),
        ("other_reportables", 30693, 12528, 25980),
        ("nonreportables", 27981, 38144, 0),
    ]


def test_source_paginates_until_a_short_page():
    source, requested_offsets = paginated_source(page_size=2, page_lengths=(2, 2, 1))
    assert len(source.fetch((instrument_by_slug("gold"),)).weeks) == 5
    assert requested_offsets == [0, 2, 4]


def test_full_history_query_has_no_report_date_cutoff():
    source, requests = recording_source()
    source.fetch((instrument_by_slug("gold"),))
    assert "report_date_as_yyyy_mm_dd" not in requests[0].params["$where"]


def test_source_retries_transient_responses_and_records_retry_count():
    source = source_with_statuses((503, 200))
    result = source.fetch((instrument_by_slug("gold"),))
    assert result.metadata.retry_count == 1


def test_source_rejects_a_combined_row_even_if_the_provider_returns_it(load_fixture):
    row = load_fixture("cot/tff_ust10y.json")[0]
    row["futonly_or_combined"] = "Combined"
    with pytest.raises(CftcCotSchemaError, match="FutOnly"):
        source_with_rows([row]).fetch((instrument_by_slug("ust-10y"),))
```

- [ ] **Step 3: Run the provider tests and verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cftc_cot_provider.py -q`

Expected: FAIL because `CftcCotSource` is undefined.

- [ ] **Step 4: Implement the source protocol and Socrata adapter**

```python
DATASET_BY_FAMILY = {
    ReportFamily.DISAGGREGATED_FUTURES_ONLY: "72hh-3qpy",
    ReportFamily.TFF_FUTURES_ONLY: "gpe5-46if",
}

DISAGGREGATED_FIELDS = {
    Participant.PRODUCER_MERCHANT: ("prod_merc_positions_long", "prod_merc_positions_short", None),
    Participant.SWAP_DEALER: ("swap_positions_long_all", "swap__positions_short_all", "swap__positions_spread_all"),
    Participant.MANAGED_MONEY: ("m_money_positions_long_all", "m_money_positions_short_all", "m_money_positions_spread"),
    Participant.OTHER_REPORTABLES: ("other_rept_positions_long", "other_rept_positions_short", "other_rept_positions_spread"),
    Participant.NONREPORTABLES: ("nonrept_positions_long_all", "nonrept_positions_short_all", None),
}

TFF_FIELDS = {
    Participant.DEALER_INTERMEDIARY: ("dealer_positions_long_all", "dealer_positions_short_all", "dealer_positions_spread_all"),
    Participant.ASSET_MANAGER: ("asset_mgr_positions_long", "asset_mgr_positions_short", "asset_mgr_positions_spread"),
    Participant.LEVERAGED_FUNDS: ("lev_money_positions_long", "lev_money_positions_short", "lev_money_positions_spread"),
    Participant.OTHER_REPORTABLES: ("other_rept_positions_long", "other_rept_positions_short", "other_rept_positions_spread"),
    Participant.NONREPORTABLES: ("nonrept_positions_long_all", "nonrept_positions_short_all", None),
}
```

Use `httpx.Client(timeout=30.0)` and request only the fields needed for normalization and reconciliation. The SoQL request must include exact code filtering, `futonly_or_combined = 'FutOnly'`, ascending report-date/code ordering, `$limit`, and `$offset`, with no report-date lower bound so initial and revision checks see the complete official history. Build the SHA-256 fingerprint from sorted canonical JSON containing dataset ID, source row ID, report date, code, open interest, CFTC reported totals, and normalized participant counts.

Return a `CotSourceSnapshot` containing `weeks` and `CotSourceMetadata(retrieved_at, retry_count, dataset_row_counts)`. Retry at most three times for HTTP 429/502/503/504 and `httpx.TimeoutException`, honoring a numeric `Retry-After` value capped at 60 seconds; inject the sleeper in tests. Do not retry schema or quality failures.

- [ ] **Step 5: Run the provider tests to verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cftc_cot_provider.py -q`

Expected: PASS with no network access.

- [ ] **Step 6: Write failing validation tests**

```python
def test_validation_rejects_duplicate_instrument_week(valid_snapshot):
    duplicated = valid_snapshot + (valid_snapshot[0],)
    result = validate_cot_snapshot(duplicated, instruments_for_snapshot(duplicated), ())
    assert result.valid is False
    assert "duplicate_instrument_report_date" in result.reason_codes


def test_validation_rejects_reportable_reconciliation_failure(valid_week):
    broken = replace_position(valid_week, Participant.MANAGED_MONEY, long_delta=1)
    result = validate_cot_snapshot((broken,), (definition_for(broken),), ())
    assert result.valid is False
    assert "reported_long_reconciliation_failed" in result.reason_codes


def test_validation_rejects_source_history_truncation(valid_snapshot):
    existing = frozenset((row.instrument_slug, row.report_date) for row in valid_snapshot)
    result = validate_cot_snapshot(valid_snapshot[1:], instruments_for_snapshot(valid_snapshot), existing)
    assert result.valid is False
    assert "source_history_truncated" in result.reason_codes
```

- [ ] **Step 7: Run the validation tests and verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_validation.py -q`

Expected: FAIL because the validation module does not exist.

- [ ] **Step 8: Implement deterministic quality gates**

For each family, require one common latest report date and every active registry instrument in that family's latest report. For each row, require exactly the family participant set, nonnegative counts, unique `(instrument_slug, report_date)`, and:

```python
computed_reported_long = sum(position.long + position.spreading for position in reportables)
computed_reported_short = sum(position.short + position.spreading for position in reportables)
expected_nonreportable_long = week.open_interest - week.reported_long_total
expected_nonreportable_short = week.open_interest - week.reported_short_total
```

Require the computed totals to equal CFTC's `reported_long_total` and `reported_short_total`, then compare the expected values to the normalized Nonreportables row. Compare all previously stored `(instrument_slug, report_date)` keys to the newly fetched full curated selection so a shortened response cannot publish. Return structured counts and reason codes rather than raising for data-quality failures.

- [ ] **Step 9: Run all Task 2 tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cftc_cot_provider.py tests/unit/test_cot_validation.py -q`

Expected: PASS.

- [ ] **Step 10: Commit Task 2**

```bash
git add backend/app/domain/cot/validation.py backend/app/use_cases/cot backend/app/infra/providers/cftc_cot.py backend/tests/fixtures/cot backend/tests/unit/test_cftc_cot_provider.py backend/tests/unit/test_cot_validation.py
git commit -m "feat: normalize and validate official CFTC data"
```

### Task 3: COT Persistence and Atomic Publication

**Files:**
- Create: `backend/app/infra/db/models/cot.py`
- Create: `backend/app/infra/db/repositories/cot_repository.py`
- Create: `backend/alembic/versions/20260916_0045_add_cot_positioning.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/infra/db/models/__init__.py`
- Test: `backend/tests/integration/test_cot_migration.py`
- Test: `backend/tests/unit/test_cot_repository.py`

**Interfaces:**
- Consumes: normalized and derived records from Tasks 1-2.
- Produces: `SqlCotRepository.start_run`, `existing_week_keys`, `stored_fingerprints`, `publish`, `mark_no_change`, `mark_failed`, `get_publication`, `get_instruments`, `get_history`, and `get_snapshot`.

- [ ] **Step 1: Write the failing migration test**

Assert the migration creates `cot_instruments`, `cot_weekly_positions`, `cot_import_runs`, and `cot_publication_pointers`; enforces the natural weekly uniqueness constraint; and cleanly downgrades in the integration test's isolated database.

- [ ] **Step 2: Run the migration test and verify the missing revision failure**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_cot_migration.py -q`

Expected: FAIL because revision `20260916_0045` does not exist.

- [ ] **Step 3: Add the SQLAlchemy models and Alembic revision**

Use these keys and constraints:

```python
class CotInstrument(Base):
    __tablename__ = "cot_instruments"
    id = Column(Integer, primary_key=True)
    slug = Column(String(80), nullable=False, unique=True)
    cftc_code = Column(String(16), nullable=False, unique=True)
    display_name = Column(String(120), nullable=False)
    category = Column(String(40), nullable=False)
    category_order = Column(Integer, nullable=False)
    instrument_order = Column(Integer, nullable=False)
    report_family = Column(String(48), nullable=False)
    focal_participant = Column(String(40), nullable=False)
    active = Column(Boolean, nullable=False, server_default=sa.true())
    registry_version = Column(String(64), nullable=False)


class CotWeeklyPosition(Base):
    __tablename__ = "cot_weekly_positions"
    __table_args__ = (
        UniqueConstraint("instrument_id", "report_date", "participant", name="uq_cot_weekly_position"),
        Index("ix_cot_weekly_instrument_date", "instrument_id", "report_date"),
    )
```

`CotWeeklyPosition` also stores participant, long, short, spreading, open interest, net, all three deltas, net/open-interest percentage, nullable three-year percentile, percentile status, source dataset ID, source row ID, source fingerprint, import-run ID, and timestamps. `CotImportRun` stores lifecycle status, requested/observed dates, coverage/diagnostics/source metadata JSON, registry/calculation/schema versions, failure reason, and timestamps. `CotPublicationPointer` uses key `latest_published` and a restrictive run foreign key.

- [ ] **Step 4: Run the migration test to verify it passes**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_cot_migration.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing repository publication tests**

```python
def test_publish_upserts_history_and_advances_pointer_in_one_commit(repository, session):
    run_id = repository.start_run(run_request())
    repository.publish(run_id, registry=COT_INSTRUMENTS, weeks=derived_weeks())
    pointer = session.get(CotPublicationPointer, "latest_published")
    assert pointer.run_id == run_id
    assert repository.get_publication().run.status == "published"


def test_failed_publish_keeps_previous_pointer(repository, session, first_publication):
    run_id = repository.start_run(run_request())
    with pytest.raises(IntegrityError):
        repository.publish(run_id, registry=COT_INSTRUMENTS, weeks=duplicate_weeks())
    session.rollback()
    assert session.get(CotPublicationPointer, "latest_published").run_id == first_publication
```

- [ ] **Step 6: Run the repository tests and verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_repository.py -q`

Expected: FAIL because the repository is undefined.

- [ ] **Step 7: Implement registry synchronization and publication**

`start_run` commits the audit row before external work. `publish` opens one transaction, synchronizes the registry, bulk-upserts weekly positions on `(instrument_id, report_date, participant)`, marks the run published, and inserts or updates the `latest_published` pointer before the transaction commits. Use dialect-specific PostgreSQL/SQLite `insert(...).on_conflict_do_update(...)` as existing repositories do. `mark_failed` and `mark_no_change` persist terminal audit state without moving the pointer.

- [ ] **Step 8: Run all Task 3 tests**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_cot_migration.py tests/unit/test_cot_repository.py -q`

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add backend/app/infra/db/models/cot.py backend/app/infra/db/repositories/cot_repository.py backend/alembic/versions/20260916_0045_add_cot_positioning.py backend/app/models/__init__.py backend/app/infra/db/models/__init__.py backend/tests/integration/test_cot_migration.py backend/tests/unit/test_cot_repository.py
git commit -m "feat: persist and publish COT history atomically"
```

### Task 4: Refresh Use Case, Yahoo Cache Hydration, and Backfill Command

**Files:**
- Create: `backend/app/use_cases/cot/refresh.py`
- Create: `backend/app/services/cot_price_hydrator.py`
- Create: `backend/app/scripts/backfill_cot.py`
- Modify: `backend/app/wiring/use_case_factories.py`
- Modify: `backend/app/wiring/bootstrap.py`
- Test: `backend/tests/unit/test_cot_refresh.py`
- Test: `backend/tests/unit/test_cot_price_hydrator.py`
- Test: `backend/tests/unit/test_backfill_cot_script.py`
- Test: `backend/tests/integration/test_cot_publication_flow.py`

**Interfaces:**
- Consumes: `CftcCotSource`, `SqlCotRepository`, `derive_position_series`, `validate_cot_snapshot`, registry definitions, and the existing `PriceCacheService`.
- Produces: `RefreshCotUseCase.execute(CotRefreshCommand) -> CotRefreshResult` and CLI `python -m app.scripts.backfill_cot`.

- [ ] **Step 1: Write failing refresh orchestration tests**

```python
def test_refresh_publishes_complete_valid_source_even_when_prices_fail(fakes):
    fakes.price_hydrator.fail_every_symbol = True
    result = fakes.use_case.execute(CotRefreshCommand(origin="test", force=False))
    assert result.status == "published"
    assert result.instrument_count == 31
    assert result.price_unavailable_count == 31
    assert fakes.repository.published_run_id == result.run_id


def test_refresh_no_change_does_not_move_pointer(fakes):
    first = fakes.use_case.execute(CotRefreshCommand(origin="test", force=False))
    second = fakes.use_case.execute(CotRefreshCommand(origin="test", force=False))
    assert second.status == "no_change"
    assert fakes.repository.published_run_id == first.run_id


def test_historical_correction_rebuilds_later_deltas_and_percentiles(fakes):
    fakes.use_case.execute(CotRefreshCommand(origin="test", force=False))
    prior_delta = fakes.repository.position_at(41).delta_net
    fakes.source.correct_week(40, managed_money_long_delta=50)
    second = fakes.use_case.execute(CotRefreshCommand(origin="test", force=False))
    assert second.status == "published"
    assert fakes.repository.position_at(41).delta_net != prior_delta
```

- [ ] **Step 2: Run the refresh tests and verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_refresh.py -q`

Expected: FAIL because the refresh use case is undefined.

- [ ] **Step 3: Implement refresh orchestration**

Use this sequence in `execute`:

```python
run_id = repository.start_run(command.to_run_request())
try:
    source_snapshot = source.fetch(COT_INSTRUMENTS)
    raw_weeks = source_snapshot.weeks
    validation = validate_cot_snapshot(
        raw_weeks,
        COT_INSTRUMENTS,
        repository.existing_week_keys(),
    )
    if not validation.valid:
        repository.mark_failed(run_id, "failed_quality", validation.as_dict())
        return CotRefreshResult.failed(run_id, validation.reason_codes)
    fingerprints = {week.source_row_id: week.source_fingerprint for week in raw_weeks}
    if not command.force and fingerprints == repository.stored_fingerprints():
        repository.mark_no_change(run_id, validation.as_dict())
        return CotRefreshResult.no_change(run_id)
    derived = derive_all_instrument_series(raw_weeks)
    price_result = price_hydrator.hydrate(COT_INSTRUMENTS)
    repository.publish(
        run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived,
        diagnostics={"validation": validation.as_dict(), "prices": price_result.as_dict()},
        source_metadata=source_snapshot.metadata.as_dict(),
    )
    cache_invalidator()
    return CotRefreshResult.published(run_id, derived, price_result)
except Exception as exc:
    repository.mark_failed(run_id, "failed_fetch", {"exception_type": type(exc).__name__})
    raise
```

The source fetch returns the complete curated selection each time so arbitrary CFTC corrections are detectable. The persistence operation is incremental: it compares fingerprints, no-ops unchanged imports, and upserts only new or revised canonical values.

- [ ] **Step 4: Write failing price-hydrator tests**

Assert that the hydrator requests `period="5y"` through `PriceCacheService.get_historical_data`, never calls for Canola, records per-symbol failure without raising, and accepts `LBR=F` with shorter-than-five-year coverage.

- [ ] **Step 5: Run the price-hydrator tests and verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_price_hydrator.py -q`

Expected: FAIL because `CotPriceHydrator` is undefined.

- [ ] **Step 6: Implement best-effort cache hydration**

Call `price_cache.get_historical_data(mapping.yahoo_symbol, period="5y", market="US")` directly. Do not use the public stock-history route or its symbol validator. Return exact counts for attempted, available, partial, and unavailable mappings. Treat no Yahoo symbol as unavailable without performing a provider request.

- [ ] **Step 7: Add the composition factories**

Add `get_refresh_cot_use_case(session)` in `use_case_factories.py`, re-export it through `wiring/bootstrap.py`, and compose `CftcCotSource`, `SqlCotRepository`, and `CotPriceHydrator(runtime.cache_bundle().price)`. Give `RefreshCotUseCase` an injectable cache invalidator whose default is a no-op; Task 6 replaces that default with the concrete COT response-cache invalidator after the cache module exists.

- [ ] **Step 8: Write and implement the backfill CLI test**

The test invokes `main([])` with a fake factory and asserts one `CotRefreshCommand(origin="administrative_backfill", force=True)`. The command exits zero only for `published` or `no_change`, prints run ID/report date/counts, and exits nonzero for failed quality or fetch.

- [ ] **Step 9: Add the publication-flow integration test**

Create `tests/integration/test_cot_publication_flow.py` with the real SQL repository and fixture source. Exercise initial publication, unchanged no-op, and a corrected historical row. Assert pointer progression is `None -> run 1 -> run 1 -> run 3`, the corrected week rebuilds the following delta and affected rolling percentiles, and total Yahoo failure does not prevent run 3 from publishing.

- [ ] **Step 10: Run all Task 4 tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_refresh.py tests/unit/test_cot_price_hydrator.py tests/unit/test_backfill_cot_script.py tests/integration/test_cot_publication_flow.py -q`

Expected: PASS.

- [ ] **Step 11: Commit Task 4**

```bash
git add backend/app/use_cases/cot/refresh.py backend/app/services/cot_price_hydrator.py backend/app/scripts/backfill_cot.py backend/app/wiring/use_case_factories.py backend/app/wiring/bootstrap.py backend/tests/unit/test_cot_refresh.py backend/tests/unit/test_cot_price_hydrator.py backend/tests/unit/test_backfill_cot_script.py backend/tests/integration/test_cot_publication_flow.py
git commit -m "feat: refresh COT history and hydrate price context"
```

### Task 5: Scheduled Delivery and Operational Health

**Files:**
- Create: `backend/app/interfaces/tasks/cot_tasks.py`
- Create: `backend/app/services/cot_operations_service.py`
- Modify: `backend/app/interfaces/tasks/__init__.py`
- Modify: `backend/app/celery_app.py`
- Modify: `backend/app/api/v1/operations.py`
- Test: `backend/tests/unit/test_cot_tasks.py`
- Test: `backend/tests/unit/test_cot_operations.py`
- Test: `backend/tests/unit/test_celery_schedule.py`

**Interfaces:**
- Consumes: `get_refresh_cot_use_case`, `SessionLocal`, COT import runs/pointer, shared data-fetch lock, and Redis response-cache invalidation.
- Produces: Celery task `app.interfaces.tasks.cot_tasks.refresh_cot`, weekday 17:00 ET schedule, and `GET /api/v1/operations/cot`.

- [ ] **Step 1: Write the failing Celery task test**

```python
def test_refresh_task_returns_published_summary(monkeypatch):
    monkeypatch.setattr(module, "get_refresh_cot_use_case", fake_use_case_factory)
    result = module.refresh_cot.run(origin="scheduled")
    assert result == {
        "status": "published",
        "run_id": 42,
        "report_date": "2026-09-08",
        "instrument_count": 31,
        "price_unavailable_count": 1,
    }
```

Also assert failures are logged with dataset IDs, run ID, registry version, calculation version, and report date but never with complete provider payloads.

- [ ] **Step 2: Run the task test and verify it fails**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_tasks.py -q`

Expected: FAIL because the task module is missing.

- [ ] **Step 3: Implement the serialized task boundary**

Decorate `refresh_cot` with `serialized_data_fetch_task(celery_app, "weekly-cot-refresh", name="app.interfaces.tasks.cot_tasks.refresh_cot")`. Open one `SessionLocal`, execute `CotRefreshCommand(origin=origin, force=force)`, return the compact result dictionary, and always close the session. Use the shared data-fetch queue because COT is market-agnostic.

- [ ] **Step 4: Write the failing fixed-timezone schedule test**

```python
def test_cot_schedule_runs_weekdays_at_1700_eastern():
    entry = celery_app.conf.beat_schedule["cot-refresh-weekday"]
    assert entry["task"] == "app.interfaces.tasks.cot_tasks.refresh_cot"
    assert entry["options"]["queue"] == SHARED_DATA_FETCH_QUEUE
    assert str(entry["schedule"].hour) == "17"
    assert str(entry["schedule"].minute) == "0"
    assert str(entry["schedule"].day_of_week) == "1-5"
    assert str(entry["schedule"].app.timezone) == "America/New_York"
```

- [ ] **Step 5: Register, route, and schedule the task**

Add the task module to Celery's include list and route it to `SHARED_DATA_FETCH_QUEUE`. Add `cot-refresh-weekday` to `_shared_entries` using a fixed `ZoneInfo("America/New_York")` schedule app, `hour=17`, `minute=0`, and `day_of_week="1-5"`.

- [ ] **Step 6: Write failing operations health tests**

Assert the service returns latest successful/failed run IDs, source report/retrieval dates, expected and observed instrument counts, validation reasons, exact/proxy/unavailable price counts, duration, retry count, publication age, and `stale`. Define stale as more than 10 calendar days between the current New York date and the latest Tuesday report date.

- [ ] **Step 7: Implement the operations snapshot and endpoint**

Add `CotOperationsService.snapshot(db, now=None) -> dict` and a protected `GET /operations/cot` handler. Return only aggregate diagnostics; do not return raw CFTC rows or Yahoo dataframes.

- [ ] **Step 8: Run all Task 5 tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_tasks.py tests/unit/test_cot_operations.py tests/unit/test_celery_schedule.py -q`

Expected: PASS.

- [ ] **Step 9: Commit Task 5**

```bash
git add backend/app/interfaces/tasks/cot_tasks.py backend/app/interfaces/tasks/__init__.py backend/app/services/cot_operations_service.py backend/app/celery_app.py backend/app/api/v1/operations.py backend/tests/unit/test_cot_tasks.py backend/tests/unit/test_cot_operations.py backend/tests/unit/test_celery_schedule.py
git commit -m "feat: schedule and monitor COT refreshes"
```

### Task 6: Published Read Models, Strict Contracts, Cache, and Live API

**Files:**
- Create: `backend/app/use_cases/cot/queries.py`
- Create: `backend/app/schemas/cot.py`
- Create: `backend/app/services/cot_response_cache.py`
- Create: `backend/app/api/v1/cot.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/wiring/use_case_factories.py`
- Modify: `backend/app/wiring/bootstrap.py`
- Test: `backend/tests/unit/test_cot_queries.py`
- Test: `backend/tests/unit/test_cot_response_cache.py`
- Test: `backend/tests/unit/test_cot_api.py`

**Interfaces:**
- Consumes: published repository reads, `StockPrice` rows, registry metadata, and publication pointer from Tasks 1-4.
- Produces: `CotQueryService.publication()`, `catalog()`, `history(slug, range_name)`, `snapshot()`, strict response classes, and protected `/v1/cot` routes.

- [ ] **Step 1: Write failing query tests for range, price alignment, and table order**

```python
def test_history_uses_week_counts_and_cached_prices_only(query_service):
    history = query_service.history("sp-500", "1y")
    assert len(history.weeks) == 52
    assert history.weeks[-1].report_date.isoformat() == "2026-09-08"
    assert history.weeks[-1].price_date <= history.weeks[-1].report_date
    assert query_service.external_calls == []


def test_snapshot_preserves_registry_order_and_focal_participants(query_service):
    rows = query_service.snapshot().rows
    assert [row.slug for row in rows[:3]] == ["sp-500", "nasdaq-100", "russell-2000"]
    assert row_by_slug(rows, "sp-500").focal_participant == "leveraged_funds"
    assert row_by_slug(rows, "gold").focal_participant == "managed_money"
    assert len(row_by_slug(rows, "gold").net_trend) == 12
```

- [ ] **Step 2: Run the query tests and verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_queries.py -q`

Expected: FAIL because `CotQueryService` is undefined.

- [ ] **Step 3: Implement application read models and cached-price reader**

Use fixed week limits `{"1y": 52, "3y": 156, "5y": 260}`. Query only the publication-selected canonical history and `stock_prices`; never call `PriceCacheService.get_historical_data` from a read path. Build one price map per instrument, align it with `align_prices_to_report_dates`, and assign:

```python
coverage_state = (
    PriceCoverageState.UNAVAILABLE
    if not aligned_closes
    else PriceCoverageState.PARTIAL
    if len(aligned_closes) < len(report_dates)
    else PriceCoverageState.COMPLETE
)
```

The snapshot row uses the instrument's focal participant and the last 12 non-null focal net values for `net_trend`.

- [ ] **Step 4: Write failing Pydantic contract tests**

Assert extra fields, non-finite numbers, unknown participants, invalid range names, duplicate instruments, and `available`/value mismatches are rejected. Assert `CotHistoryResponse.from_view(view).model_dump(mode="json")` preserves integers exactly.

- [ ] **Step 5: Define the strict response shapes**

```python
class CotPublicationMetadataResponse(_StrictModel):
    schema_version: Literal["cot-v1"]
    calculation_version: Literal["cot-positions-v1"]
    registry_version: str
    publication_id: int
    report_date: date
    retrieved_at: datetime
    stale: bool


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


class CotHistoryWeekResponse(_StrictModel):
    report_date: date
    open_interest: int = Field(ge=0)
    price_date: date | None
    price_close: float | None
    price_change_pct: float | None
    positions: list[CotPositionResponse]
```

Add catalog/category/instrument/participant/price-mapping, source, history, snapshot-row, and snapshot response models. `CotCatalogResponse` carries both official dataset IDs, labels, and CFTC URLs plus `default_slug="sp-500"`. `CotHistoryResponse` carries top-level `range`, instrument/report family/dataset identity, `price_mapping_kind`, `price_coverage_state`, `price_history_start`, and optional TradingView URL. `CotSnapshotRowResponse` carries the focal metrics, 12-point net trend, and current price classification.

- [ ] **Step 6: Write failing response-cache tests**

```python
def test_cache_key_changes_with_publication_and_range():
    assert cot_cache_key("history", 7, slug="gold", range_name="1y") != cot_cache_key(
        "history", 8, slug="gold", range_name="1y"
    )
    assert cot_cache_key("history", 8, slug="gold", range_name="1y") != cot_cache_key(
        "history", 8, slug="gold", range_name="5y"
    )


def test_invalidate_clears_memory_and_redis_prefix(cache):
    cache.set("cot:cot-v1:7:catalog", "{}")
    cache.invalidate_all()
    assert cache.get("cot:cot-v1:7:catalog") is None
```

- [ ] **Step 7: Implement bounded memory and Redis JSON caching**

Use a 128-entry ordered in-process cache and a one-hour Redis TTL. Keys include schema version, calculation version, publication ID, endpoint, instrument, and range. `invalidate_all` clears memory and deletes only Redis keys matching `cot:*` via bounded `scan_iter` batches.

- [ ] **Step 8: Write failing API tests**

```python
@pytest.mark.asyncio
async def test_cot_endpoints_are_protected_and_never_fetch_external_data(auth_client):
    catalog = await auth_client.get("/api/v1/cot/instruments")
    history = await auth_client.get("/api/v1/cot/instruments/sp-500/history?range=1y")
    snapshot = await auth_client.get("/api/v1/cot/snapshot")
    assert catalog.status_code == history.status_code == snapshot.status_code == 200
    assert len(catalog.json()["instruments"]) == 31
    assert len(history.json()["weeks"]) == 52
    assert len(snapshot.json()["rows"]) == 31
```

Also assert an invalid slug returns 404 with code `cot_instrument_unavailable`, an invalid range returns 422, no publication returns 404 with code `cot_publication_unavailable`, and an unauthenticated request follows the existing server-session policy.

- [ ] **Step 9: Compose the published query service**

Add `get_cot_queries(session)` to `use_case_factories.py`, re-export it through `wiring/bootstrap.py`, and compose `CotQueryService(SqlCotRepository(session), SqlCotPriceReader(session))` without any external provider dependency. Update `get_refresh_cot_use_case(session)` to inject `invalidate_cot_response_cache` now that the cache module exists.

- [ ] **Step 10: Implement and register the live routes**

Add `GET /instruments`, `GET /instruments/{slug}/history?range=1y|3y|5y`, and `GET /snapshot`. Resolve the current publication before forming cache keys, validate the generated JSON with the matching Pydantic response, and return `Cache-Control: private, max-age=60`.

- [ ] **Step 11: Run all Task 6 tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_queries.py tests/unit/test_cot_response_cache.py tests/unit/test_cot_api.py -q`

Expected: PASS.

- [ ] **Step 12: Commit Task 6**

```bash
git add backend/app/use_cases/cot/queries.py backend/app/schemas/cot.py backend/app/services/cot_response_cache.py backend/app/api/v1/cot.py backend/app/api/v1/router.py backend/app/wiring/use_case_factories.py backend/app/wiring/bootstrap.py backend/tests/unit/test_cot_queries.py backend/tests/unit/test_cot_response_cache.py backend/tests/unit/test_cot_api.py
git commit -m "feat: expose published COT read APIs"
```

### Task 7: Static COT Artifact and Live/Static Parity

**Files:**
- Create: `backend/app/services/static_cot_contract.py`
- Create: `backend/app/services/static_cot_exporter.py`
- Create: `backend/app/services/static_cot_artifact_selector.py`
- Create: `backend/app/services/static_cot_section.py`
- Modify: `backend/app/services/static_site_manifest.py`
- Modify: `backend/app/services/static_site_export_service.py`
- Test: `backend/tests/unit/test_static_cot_exporter.py`
- Test: `backend/tests/unit/test_static_cot_section.py`
- Test: `backend/tests/integration/test_cot_static_live_parity.py`
- Modify test: `backend/tests/unit/test_static_site_export_service.py`

**Interfaces:**
- Consumes: `CotQueryService` and the Task 6 Pydantic responses.
- Produces: `cot/index.json`, `cot/<slug>.json`, static artifact validation, fallback selection, and root `assets.cot.path`.

- [ ] **Step 1: Write the failing atomic exporter test**

```python
def test_static_export_writes_index_and_31_five_year_histories(tmp_path, cot_queries):
    cot_dir = tmp_path / "cot"
    index = StaticCotExporter(cot_queries).export(
        cot_dir,
        generated_at="2026-09-16T09:00:00Z",
    )
    assert index["schema_version"] == "static-cot-v1"
    assert index["default_slug"] == "sp-500"
    assert len(index["histories"]) == 31
    assert json.loads((cot_dir / "sp-500.json").read_text())["range"] == "5y"
    validate_static_cot_artifact(cot_dir)
```

- [ ] **Step 2: Run the exporter test and verify it fails**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_cot_exporter.py -q`

Expected: FAIL because the static exporter is undefined.

- [ ] **Step 3: Implement the static contract and atomic exporter**

The index shape is:

```json
{
  "schema_version": "static-cot-v1",
  "data_schema_version": "cot-v1",
  "calculation_version": "cot-positions-v1",
  "publication_id": 42,
  "report_date": "2026-09-08",
  "generated_at": "2026-09-16T09:00:00Z",
  "default_slug": "sp-500",
  "catalog": {},
  "histories": {
    "sp-500": {"path": "cot/sp-500.json"}
  }
}
```

Populate `catalog` with `CotCatalogResponse.model_dump(mode="json")`. Populate each instrument file with `CotHistoryResponse.from_view(queries.history(slug, "5y"))`. Validate safe relative `cot/` paths, unique paths, complete catalog/history identity, publication/version equality, and finite JSON numbers before `AtomicDirectoryPublisher` swaps the directory.

- [ ] **Step 4: Write and implement the selector tests**

Test selection of a valid current artifact, fallback when current is missing or corrupt, the newer report date when both are valid, and rejection when no compatible artifact exists. The selected directory is copied to the destination atomically and its index is returned.

- [ ] **Step 5: Write the failing parity test**

```python
def test_static_history_is_byte_value_equivalent_to_live_five_year_response(tmp_path, queries):
    StaticCotExporter(queries).export(tmp_path / "cot", generated_at="2026-09-16T09:00:00Z")
    for instrument in queries.catalog().instruments:
        live = CotHistoryResponse.from_view(queries.history(instrument.slug, "5y")).model_dump(mode="json")
        static = json.loads((tmp_path / "cot" / f"{instrument.slug}.json").read_text())
        assert static == live
```

- [ ] **Step 6: Run the parity test and verify it passes after exporter implementation**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_cot_static_live_parity.py -q`

Expected: PASS.

- [ ] **Step 7: Add root-global manifest support**

Change `build_static_site_manifest` to accept `global_assets: Mapping[str, Any] | None = None` and merge those only into top-level `manifest["assets"]`. Keep every `manifest["markets"][market]["assets"]` unchanged. In `StaticSiteExportService.export`, compose COT once per complete export, pass `{"cot": {"path": "cot/index.json"}}` only when selected, and leave older/no-publication exports valid without the key.

- [ ] **Step 8: Test direct static export behavior**

Add tests that root `assets.cot.path` exists when a publication is available, is absent when unavailable, never appears in per-market assets, and does not prevent other market artifacts from exporting.

- [ ] **Step 9: Run all Task 7 tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_cot_exporter.py tests/unit/test_static_cot_section.py tests/integration/test_cot_static_live_parity.py tests/unit/test_static_site_export_service.py -q`

Expected: PASS.

- [ ] **Step 10: Commit Task 7**

```bash
git add backend/app/services/static_cot_contract.py backend/app/services/static_cot_exporter.py backend/app/services/static_cot_artifact_selector.py backend/app/services/static_cot_section.py backend/app/services/static_site_manifest.py backend/app/services/static_site_export_service.py backend/tests/unit/test_static_cot_exporter.py backend/tests/unit/test_static_cot_section.py backend/tests/integration/test_cot_static_live_parity.py backend/tests/unit/test_static_site_export_service.py
git commit -m "feat: export parity-safe static COT artifacts"
```

### Task 8: Static Server and GitHub Publication Pipeline

**Files:**
- Modify: `backend/app/services/static_site_export_service.py`
- Modify: `backend/app/tasks/static_export_tasks.py`
- Modify: `backend/app/scripts/export_static_site.py`
- Modify: `backend/app/scripts/download_static_market_fallbacks.py`
- Modify: `backend/app/scripts/validate_static_market_artifacts.py`
- Modify: `.github/workflows/static-site.yml`
- Test: `backend/tests/unit/test_static_export_tasks.py`
- Test: `backend/tests/unit/test_export_static_site_script.py`
- Test: `backend/tests/unit/test_download_static_market_fallbacks.py`
- Test: `backend/tests/unit/test_validate_static_market_artifacts.py`

**Interfaces:**
- Consumes: the Task 7 `StaticCotSection` selector and artifact contract.
- Produces: last-good server fallback and the `static-cot-global` workflow artifact across partial market builds.

- [ ] **Step 1: Write failing server-export fallback tests**

Assert `export_static_site_data` passes `cot_fallback_dir=target / "cot"`, retains the prior COT artifact if the current refresh cannot produce one, and still swaps the rest of the static bundle atomically.

- [ ] **Step 2: Implement server fallback plumbing**

Add `cot_fallback_dir` to `StaticSiteExportService.export` and `StaticCotSection.compose_live`. The scheduled export passes the currently served `target/cot` as fallback before the directory swap.

- [ ] **Step 3: Write failing CLI argument and combine tests**

Cover `--cot-artifacts-dir` and `--fallback-cot-artifacts-dir`, require combine mode when either is provided, and assert both paths reach `StaticSiteExportService.combine_market_artifacts`.

- [ ] **Step 4: Implement direct refresh and combine CLI support**

During a US `--refresh-daily` build, execute the same COT refresh use case with origin `static_build` and continue to last-good selection if it fails. Add the two combine arguments and pass them to `StaticCotSection.compose_combined`.

- [ ] **Step 5: Write failing fallback download/validation tests**

Assert the fallback downloader recognizes artifact name `static-cot-global`, chooses the newest valid report date, ignores corrupt artifacts, and installs it in the requested fallback directory. Assert the artifact validator checks both current and fallback COT directories with `validate_static_cot_artifact`.

- [ ] **Step 6: Implement fallback download and validation**

Add `--current-cot-dir` and `--fallback-cot-dir` to the downloader and validator scripts. Reuse the COT contract; do not infer validity from file presence alone.

- [ ] **Step 7: Update the GitHub workflow**

For the US matrix job, set `has_cot_artifact=true` when `/tmp/static-data/cot/index.json` exists and upload `/tmp/static-data/cot` as `static-cot-global`. In the combine job, download the current artifact, request last-good fallback download/validation, and pass both COT directories to `export_static_site`. Asia-only runs therefore reuse the latest valid global COT bundle.

- [ ] **Step 8: Run all Task 8 tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_export_tasks.py tests/unit/test_export_static_site_script.py tests/unit/test_download_static_market_fallbacks.py tests/unit/test_validate_static_market_artifacts.py -q`

Expected: PASS.

- [ ] **Step 9: Validate workflow syntax-sensitive paths by inspection test**

Run: `rg -n "static-cot-global|current-cot-dir|fallback-cot-dir|cot-artifacts-dir" .github/workflows/static-site.yml backend/app/scripts`

Expected: every upload, download, validation, and combine phase contains the matching COT path.

- [ ] **Step 10: Commit Task 8**

```bash
git add backend/app/services/static_site_export_service.py backend/app/tasks/static_export_tasks.py backend/app/scripts/export_static_site.py backend/app/scripts/download_static_market_fallbacks.py backend/app/scripts/validate_static_market_artifacts.py .github/workflows/static-site.yml backend/tests/unit/test_static_export_tasks.py backend/tests/unit/test_export_static_site_script.py backend/tests/unit/test_download_static_market_fallbacks.py backend/tests/unit/test_validate_static_market_artifacts.py
git commit -m "feat: publish last-good COT static artifacts"
```

### Task 9: Frontend Contract, Live Client, and Static Client

**Files:**
- Create: `frontend/src/features/cot/cotContract.js`
- Create: `frontend/src/features/cot/cotContract.test.js`
- Create: `frontend/src/api/cot.js`
- Create: `frontend/src/api/cot.test.js`
- Create: `frontend/src/static/cotClient.js`
- Create: `frontend/src/static/cotClient.test.js`

**Interfaces:**
- Consumes: Task 6 live JSON and Task 7 static index/history JSON.
- Produces: `normalizeCotCatalog`, `normalizeCotHistory`, `normalizeCotSnapshot`, `normalizeStaticCotIndex`, `sliceCotHistory`, live fetch functions, static query functions, and stable query keys.

- [ ] **Step 1: Write failing semantic contract tests**

```javascript
it('rejects an available percentile without a value', () => {
  const payload = makeHistory();
  payload.weeks[0].positions[0].percentile_status = 'available';
  payload.weeks[0].positions[0].percentile_3y = null;
  expect(() => normalizeCotHistory(payload)).toThrow(/percentile/i);
});

it('slices static five-year data without changing percentile values', () => {
  const history = makeHistory({ weekCount: 260 });
  const sliced = sliceCotHistory(history, '1y');
  expect(sliced.weeks).toHaveLength(52);
  expect(sliced.weeks.at(-1).positions[0].percentile_3y)
    .toBe(history.weeks.at(-1).positions[0].percentile_3y);
});
```

Also reject unsafe static paths, publication/version mismatches, duplicate slugs, non-finite numbers, unknown range names, and incorrectly ordered catalog entries.

- [ ] **Step 2: Run the contract tests and verify they fail**

Run: `cd frontend && npm run test:run -- src/features/cot/cotContract.test.js`

Expected: FAIL because the contract module is missing.

- [ ] **Step 3: Implement contract normalization and query keys**

Export:

```javascript
export const COT_RANGES = Object.freeze({ '1y': 52, '3y': 156, '5y': 260 });
export const COT_DEFAULT_SLUG = 'sp-500';

export const cotCatalogQueryKey = (mode, publicationId = null, path = null) => [
  'cot', 'catalog', mode, publicationId, path,
];

export const cotHistoryQueryKey = ({ mode, publicationId, slug, range, path = null }) => [
  'cot', 'history', mode, publicationId, slug, range, path,
];

export const sliceCotHistory = (history, range) => ({
  ...history,
  range,
  weeks: history.weeks.slice(-COT_RANGES[range]),
});
```

Validate all required fields, participant uniqueness, ascending report dates, catalog order, publication identity, percentile value/status consistency, and exact/proxy/partial/unavailable price metadata. The backend owns the 156-observation calculation because a live 1Y payload does not contain the earlier observations needed to recompute it. Return the original normalized object without inventing zeroes.

- [ ] **Step 4: Write failing live client tests**

Mock `apiClient.get` and assert exact calls to `/v1/cot/instruments`, `/v1/cot/instruments/gold/history` with `{params: {range: '3y'}}`, and `/v1/cot/snapshot`; assert every response passes the matching normalizer.

- [ ] **Step 5: Implement the live client**

```javascript
export const getCotCatalog = async () => normalizeCotCatalog(
  (await apiClient.get('/v1/cot/instruments')).data,
);

export const getCotHistory = async (slug, range = '1y') => normalizeCotHistory(
  (await apiClient.get(`/v1/cot/instruments/${encodeURIComponent(slug)}/history`, {
    params: { range },
  })).data,
);

export const getCotSnapshot = async () => normalizeCotSnapshot(
  (await apiClient.get('/v1/cot/snapshot')).data,
);
```

- [ ] **Step 6: Write failing static client tests**

Assert the client fetches only the root-manifest-advertised `cot/index.json`, looks up the selected slug's safe path, validates matching publication identity, and slices the five-year file locally. Assert no function contains or requests `/api`.

- [ ] **Step 7: Implement the static client**

Export `useStaticCotIndex(rootManifest)`, `useStaticCotHistory(index, slug, range)`, and pure fetch helpers built only on `fetchStaticJson`. Disable queries when `rootManifest.assets.cot.path` is absent.

- [ ] **Step 8: Run all Task 9 tests**

Run: `cd frontend && npm run test:run -- src/features/cot/cotContract.test.js src/api/cot.test.js src/static/cotClient.test.js`

Expected: PASS.

- [ ] **Step 9: Commit Task 9**

```bash
git add frontend/src/features/cot/cotContract.js frontend/src/features/cot/cotContract.test.js frontend/src/api/cot.js frontend/src/api/cot.test.js frontend/src/static/cotClient.js frontend/src/static/cotClient.test.js
git commit -m "feat: add live and static COT data clients"
```

### Task 10: Shared COT Controls, Summary, and Charts

**Files:**
- Create: `frontend/src/features/cot/CotSummaryStrip.jsx`
- Create: `frontend/src/features/cot/CotPositioningChart.jsx`
- Create: `frontend/src/features/cot/CotPositioningView.jsx`
- Create: `frontend/src/features/cot/CotPositioningView.test.jsx`
- Create: `frontend/src/features/cot/cotPresentation.js`
- Create: `frontend/src/features/cot/cotPresentation.test.js`

**Interfaces:**
- Consumes: normalized catalog/history from Task 9 and callbacks owned by live/static containers.
- Produces: shared chart-only view usable in both application modes.

- [ ] **Step 1: Write failing presentation transformation tests**

```javascript
it('builds net series for every participant', () => {
  const rows = buildCotChartRows(makeHistory(), { mode: 'net', participant: null });
  expect(rows.at(-1)).toMatchObject({
    leveraged_funds: 42,
    dealer_intermediary: -18,
    price: 6520.25,
  });
});

it('renders selected long above zero and short below zero', () => {
  const rows = buildCotChartRows(makeHistory(), {
    mode: 'long_short',
    participant: 'leveraged_funds',
  });
  expect(rows.at(-1)).toMatchObject({ long: 120, short: -78 });
});
```

- [ ] **Step 2: Run the transformation tests and verify they fail**

Run: `cd frontend && npm run test:run -- src/features/cot/cotPresentation.test.js`

Expected: FAIL because the presentation helpers are missing.

- [ ] **Step 3: Implement chart-row and summary helpers**

`buildCotChartRows` maps every week to `reportDate`, participant series or selected long/negative-short values, `price`, and `openInterest`. `latestFocalSummary` resolves the instrument's actual focal participant and returns long, short, net, percentile/status, report date, price change, mapping kind, and coverage state. Formatting functions return an em dash for `null` and never coerce `null` to zero.

- [ ] **Step 4: Write failing shared-view component tests**

Test grouped category options, S&P 500 selection, 1Y/3Y/5Y callbacks, Net and Long & Short modes, participant selector visibility, participant legend toggles, proxy/partial/unavailable text, Canola's optional TradingView link, stale warning, insufficient-history text, and an accessible chart description.

- [ ] **Step 5: Run the component tests and verify they fail**

Run: `cd frontend && npm run test:run -- src/features/cot/CotPositioningView.test.jsx`

Expected: FAIL because the shared components are missing.

- [ ] **Step 6: Implement `CotSummaryStrip`**

Render six labelled values in responsive MUI cards: Report Date, focal Long, focal Short, focal Net, 3Y Percentile, and Tuesday-to-Tuesday Price Change. Include the actual focal label (`Managed Money` or `Leveraged Funds`) and the price state text (`Exact future`, `ETF proxy`, `Index proxy`, `Partial price history`, or `Price unavailable`).

- [ ] **Step 7: Implement `CotPositioningChart`**

Use Recharts `ComposedChart` with a left positioning axis and a right price axis. In Net mode, create one `Bar` per visible participant around a zero reference line. In Long & Short mode, render `long` and negative `short` bars for the selected participant. Add a dashed `Line` for non-null prices and a separate compact `BarChart` for open interest. The custom tooltip shows report date, participant, long, short, net, percentile, open interest, aligned price date/value, and price classification.

Wrap the chart in `role="img"` and connect `aria-describedby` to text such as `S&P 500 net positioning for five CFTC participant groups over 52 report weeks; dashed line is exact futures price context.` Keep every toggle keyboard-operable.

- [ ] **Step 8: Implement `CotPositioningView`**

Render a category-grouped MUI instrument select, mode toggle, range toggle, optional participant select, summary strip, positioning chart, open-interest chart, source/freshness line, and explicit loading/error/empty states. When an unavailable mapping has a TradingView URL, render a labelled external anchor only; never fetch it. Do not accept table data or import the live table into this shared chart component.

- [ ] **Step 9: Run all Task 10 tests**

Run: `cd frontend && npm run test:run -- src/features/cot/cotPresentation.test.js src/features/cot/CotPositioningView.test.jsx`

Expected: PASS.

- [ ] **Step 10: Commit Task 10**

```bash
git add frontend/src/features/cot/CotSummaryStrip.jsx frontend/src/features/cot/CotPositioningChart.jsx frontend/src/features/cot/CotPositioningView.jsx frontend/src/features/cot/CotPositioningView.test.jsx frontend/src/features/cot/cotPresentation.js frontend/src/features/cot/cotPresentation.test.js
git commit -m "feat: render shared COT positioning charts"
```

### Task 11: Live Daily Tab and Complete Positioning Table

**Files:**
- Create: `frontend/src/features/cot/CotSnapshotTable.jsx`
- Create: `frontend/src/features/cot/CotSnapshotTable.test.jsx`
- Create: `frontend/src/features/cot/CotPositioningTab.jsx`
- Create: `frontend/src/features/cot/CotPositioningTab.test.jsx`
- Modify: `frontend/src/pages/MarketScanPage.jsx`
- Modify: `frontend/src/pages/MarketScanPage.test.jsx`

**Interfaces:**
- Consumes: live Task 9 client, Task 10 shared view, and snapshot response.
- Produces: lazy `COT Positioning` vertical tab with chart and live-only table.

- [ ] **Step 1: Write failing table behavior tests**

Test the approved category order, focal participant labels, all required columns, category filter, sortable Market and numeric columns, restore-curated-order action, row-click selection, net trend graphic, and textual price classification.

- [ ] **Step 2: Run the table tests and verify they fail**

Run: `cd frontend && npm run test:run -- src/features/cot/CotSnapshotTable.test.jsx`

Expected: FAIL because the table component is missing.

- [ ] **Step 3: Implement the live table**

Render columns for Market; focal Long and weekly change; focal Short and weekly change; focal Net and weekly change; Net/OI; 3Y Percentile; 12-week net trend; Tuesday-to-Tuesday price change; and price classification. Use `TableSortLabel` on Market and every numeric column, a category select, and a `Restore curated order` button. The visual trend column sorts by its latest net value. Sorting must be stable and place null values last. Make each row keyboard-selectable and call `onSelectInstrument(slug)`.

- [ ] **Step 4: Write failing live-container tests**

Mock the three live client functions. Assert initial queries load catalog, S&P 500 1Y history, and snapshot; selecting Gold requests `gold`; selecting 3Y requests `range=3y`; clicking a table row changes the chart instrument; errors in history do not erase the table; and price-unavailable history still renders COT bars.

- [ ] **Step 5: Implement `CotPositioningTab`**

Own `selectedSlug='sp-500'` and `range='1y'`. Use three bounded TanStack queries with query keys from `cotContract.js`; keep catalog/snapshot at a 60-second stale time and history keyed by slug/range. Render `CotPositioningView` above `CotSnapshotTable` in a scrollable full-height container.

- [ ] **Step 6: Write the failing tab-order/lazy-mount test**

```javascript
it('places COT after Key Markets and before Themes without eager mounting', async () => {
  runtimeState.features = { themes: true, social_signals: false };
  renderPage();
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
    'Daily Snapshot', 'Key Markets', 'COT Positioning', 'Themes', 'Watchlists', 'Stockbee MM',
  ]);
  expect(cotRenderSpy).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('tab', { name: 'COT Positioning' }));
  expect(cotRenderSpy).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 7: Add the live vertical tab**

Lazy-import `CotPositioningTab` in `MarketScanPage.jsx` and insert its fixed entry immediately after Key Markets and before the optional Themes entry. Do not add a top-level route or horizontal navigation.

- [ ] **Step 8: Run all Task 11 tests**

Run: `cd frontend && npm run test:run -- src/features/cot/CotSnapshotTable.test.jsx src/features/cot/CotPositioningTab.test.jsx src/pages/MarketScanPage.test.jsx`

Expected: PASS.

- [ ] **Step 9: Commit Task 11**

```bash
git add frontend/src/features/cot/CotSnapshotTable.jsx frontend/src/features/cot/CotSnapshotTable.test.jsx frontend/src/features/cot/CotPositioningTab.jsx frontend/src/features/cot/CotPositioningTab.test.jsx frontend/src/pages/MarketScanPage.jsx frontend/src/pages/MarketScanPage.test.jsx
git commit -m "feat: add live COT Daily tab and table"
```

### Task 12: Static Daily COT Section

**Files:**
- Create: `frontend/src/static/components/StaticCotSection.jsx`
- Create: `frontend/src/static/components/StaticCotSection.test.jsx`
- Modify: `frontend/src/static/pages/StaticHomePage.jsx`
- Modify: `frontend/src/static/pages/StaticHomePage.test.jsx`
- Create: `frontend/src/static/cotIsolation.test.jsx`

**Interfaces:**
- Consumes: root static manifest, Task 9 static client, and Task 10 shared view.
- Produces: optional chart-only static section after Market Health.

- [ ] **Step 1: Write failing static-container tests**

Assert the section is absent when `manifest.assets.cot` is missing; when present, it fetches `cot/index.json`, prefetches only S&P 500 history, lazy-loads a newly selected instrument, slices 1Y/3Y locally, renders no full table, and displays an artifact-level error without breaking the rest of Daily.

- [ ] **Step 2: Run the static-container tests and verify they fail**

Run: `cd frontend && npm run test:run -- src/static/components/StaticCotSection.test.jsx`

Expected: FAIL because the static section is missing.

- [ ] **Step 3: Implement `StaticCotSection`**

Accept `manifest` rather than a market entry so COT remains global when the stock-market selector changes. Own the same default slug/range state as live mode, load the advertised index, load only the selected history path, and render `CotPositioningView` without importing or rendering `CotSnapshotTable`.

- [ ] **Step 4: Write the failing placement test**

Render `StaticHomePage` with a COT asset and assert DOM order is `market-health-exposure`, `static-cot-section`, then `top-scan-candidates-section`. Switch the selected stock market and assert the COT index path remains the root `cot/index.json`.

- [ ] **Step 5: Insert the static section**

Pass `manifestQuery.data` to `StaticCotSection` immediately after `<MarketHealthExposure>` and before Correction Survivors/Top Scan Candidates. This preserves the requested placement even when optional intermediate panels are absent.

- [ ] **Step 6: Add a static isolation test**

Mock `global.fetch`, exercise index load and two instrument selections, and assert every URL is a safe static-data path and none contains `/api`, `cftc.gov`, `finance.yahoo`, or `tradingview.com`.

- [ ] **Step 7: Run all Task 12 tests**

Run: `cd frontend && npm run test:run -- src/static/components/StaticCotSection.test.jsx src/static/pages/StaticHomePage.test.jsx src/static/cotIsolation.test.jsx`

Expected: PASS.

- [ ] **Step 8: Commit Task 12**

```bash
git add frontend/src/static/components/StaticCotSection.jsx frontend/src/static/components/StaticCotSection.test.jsx frontend/src/static/pages/StaticHomePage.jsx frontend/src/static/pages/StaticHomePage.test.jsx frontend/src/static/cotIsolation.test.jsx
git commit -m "feat: add static Daily COT section"
```

### Task 13: Runbook, Full Verification, and Release Gate

**Files:**
- Create: `docs/runbooks/cot-positioning.md`
- Modify only if verification exposes a defect: files already listed in Tasks 1-12 and their matching tests.

**Interfaces:**
- Consumes: the complete feature.
- Produces: operator instructions and evidence that every acceptance criterion is satisfied.

- [ ] **Step 1: Write the operations runbook**

Document:

```text
Initial backfill: cd backend && ./venv/bin/python -m app.scripts.backfill_cot
Health endpoint: GET /api/v1/operations/cot
Official datasets: 72hh-3qpy and gpe5-46if
Publication rule: prior pointer remains active on CFTC fetch/quality failure
Price rule: Yahoo cache failure is non-blocking; Canola is link-only
Recovery: inspect the failed cot_import_runs row, correct registry/source issues, rerun backfill, confirm pointer and static assets
Static verification: manifest.json assets.cot.path -> cot/index.json -> 31 history files
```

Include the exact registry/calculation/schema versions and explain that percentile values do not change when the chart range changes.

- [ ] **Step 2: Run the focused backend suite**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_registry.py tests/unit/test_cot_calculations.py tests/unit/test_cftc_cot_provider.py tests/unit/test_cot_validation.py tests/unit/test_cot_repository.py tests/unit/test_cot_refresh.py tests/unit/test_cot_price_hydrator.py tests/unit/test_cot_tasks.py tests/unit/test_cot_operations.py tests/unit/test_cot_queries.py tests/unit/test_cot_response_cache.py tests/unit/test_cot_api.py tests/unit/test_static_cot_exporter.py tests/unit/test_static_cot_section.py tests/integration/test_cot_migration.py tests/integration/test_cot_publication_flow.py tests/integration/test_cot_static_live_parity.py -q`

Expected: PASS.

- [ ] **Step 3: Run existing backend regression suites touched by the feature**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_site_export_service.py tests/unit/test_static_export_tasks.py tests/unit/test_export_static_site_script.py tests/unit/test_download_static_market_fallbacks.py tests/unit/test_validate_static_market_artifacts.py tests/unit/test_operations_endpoints.py -q`

Expected: PASS.

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && ./venv/bin/pytest`

Expected: PASS with no new warnings attributable to COT.

- [ ] **Step 5: Run the focused frontend suite**

Run: `cd frontend && npm run test:run -- src/features/cot src/api/cot.test.js src/static/cotClient.test.js src/static/cotIsolation.test.jsx src/pages/MarketScanPage.test.jsx src/static/pages/StaticHomePage.test.jsx`

Expected: PASS.

- [ ] **Step 6: Run frontend lint, full tests, and production build**

Run: `cd frontend && npm run lint`

Expected: PASS.

Run: `cd frontend && npm run test:run`

Expected: PASS.

Run: `cd frontend && npm run build`

Expected: PASS.

- [ ] **Step 7: Exercise three refresh simulations**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_cot_publication_flow.py -q`

Expected: PASS, covering `None -> run 1 -> run 1 -> run 3`, dependent delta/percentile rebuilds, and publication despite total Yahoo failure.

- [ ] **Step 8: Verify static/live parity and external-call isolation**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_cot_static_live_parity.py tests/unit/test_cot_api.py tests/unit/test_static_site_export_service.py -q`

Run: `cd frontend && npm run test:run -- src/static/cotIsolation.test.jsx src/static/cotClient.test.js`

Expected: PASS, including all 31 five-year histories, cache/static-only reads, root `assets.cot.path = "cot/index.json"`, and no per-market COT asset.

- [ ] **Step 9: Verify acceptance counts and UI order**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_cot_registry.py tests/unit/test_cot_validation.py tests/unit/test_cot_api.py -q`

Run: `cd frontend && npm run test:run -- src/features/cot/CotPositioningTab.test.jsx src/pages/MarketScanPage.test.jsx src/static/components/StaticCotSection.test.jsx src/static/pages/StaticHomePage.test.jsx`

Expected: PASS for 31 catalog entries, current-family quality gates, S&P 500/1Y defaults, fixed category order, Key Markets → COT Positioning → Themes, Market Health → COT → Top Scan Candidates, and no static table.

- [ ] **Step 10: Commit the runbook and any verification repairs**

```bash
git add docs/runbooks/cot-positioning.md
git commit -m "docs: add COT operations runbook"
```

If verification required code repairs, commit each repair with its matching regression test before the runbook commit rather than folding unrelated repairs into the documentation commit.

- [ ] **Step 11: Request final code review**

Use `superpowers:requesting-code-review` against the complete branch, resolve every correctness issue, then rerun the focused backend/frontend suites before integration.
