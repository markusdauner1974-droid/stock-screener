# COT Positioning Operations

The COT feature publishes a curated 31-market view of weekly CFTC positioning for both the live application and the static Daily page.

## Data contracts and sources

- Official CFTC Disaggregated Futures Only dataset: `72hh-3qpy`
- Official CFTC Traders in Financial Futures — Futures Only dataset: `gpe5-46if`
- Registry version: `cot-curated-v1`
- Calculation version: `cot-positions-v1`
- Live data schema: `cot-v1`
- Static bundle schema: `static-cot-v1`

CFTC history is canonical. Cached Yahoo prices provide best-effort context only; price failure never blocks a valid CFTC publication. Canola is intentionally link-only and may show its TradingView contract link without making a TradingView request.

The 3Y percentile is calculated from the trailing 156 weekly CFTC observations. Changing the visible chart range between 1Y, 3Y, and 5Y does not recalculate or change percentile values.

## Implementation ownership

- `app.domain.cot.registry` is the canonical owner of the curated instrument order, CFTC dataset definitions, participant mappings, and price metadata. Consumers must not duplicate those maps.
- A publication is reusable only when its source fingerprints and registry, calculation, and schema versions all match the requested refresh.
- The live snapshot reads the focal-participant history and available prices in batches. Per-instrument history or price queries do not belong in snapshot assembly.
- `app.services.static_global_artifacts` owns discovery and last-good selection mechanics shared by the root-global COT and Options artifacts. Their product-specific modules continue to own semantic validation.
- The static site exporter owns optional-section fallback behavior, including translation of unavailable RRG source data. It calls the RRG payload source directly; no adapter wrapper is required.

## Initial backfill and manual recovery

Run the initial or forced administrative backfill:

```bash
cd backend
./venv/bin/python -m app.scripts.backfill_cot
```

Publication is atomic. A CFTC fetch, validation, or persistence failure leaves the prior publication pointer active, so users continue to see the last valid dataset.

The first publication requires at least 156 weekly observations for every curated instrument, the fetched row totals must match authoritative CFTC counts for the exact curated queries, and every report family must share one latest Tuesday. These guards prevent a truncated initial backfill or mixed-date commodities/financials snapshot from becoming current.

If a refresh fails:

1. Inspect the most recent failed row in `cot_import_runs`, including its status, validation reasons, dataset IDs, and registry/calculation versions.
2. Correct the source or registry issue. Do not manually advance `cot_publication_pointers`.
3. Rerun the backfill command.
4. Confirm the latest publication pointer advanced and the operations endpoint is healthy.
5. Confirm the next static export contains the COT index and all 31 histories.

## Health and freshness

The protected health endpoint is:

```text
GET /api/v1/operations/cot
```

It reports the latest successful and failed runs, source report and retrieval dates, observed instrument counts, validation reasons, price coverage counts, duration, retries, publication age, and stale state. A publication is stale when its latest Tuesday report is more than 10 calendar days behind the current New York date.

The scheduled refresh runs on weekdays at 17:00 America/New_York. An unchanged source creates a `no_change` audit run and leaves the publication pointer unchanged.

## Static publication checks

Verify this chain after a static build:

```text
manifest.json
  assets.cot.path = cot/index.json
    histories = 31 entries
      cot/<slug>.json = live-equivalent 5Y history
```

The COT asset is root-global and must not appear inside `manifest.markets[market].assets`. Static pages fetch only the advertised COT index and selected history file. The live-only 31-row table is not included on the static page.

The GitHub workflow publishes the independent artifact `static-cot-global`. If the current artifact is missing or invalid, combine mode selects the newest valid last-good COT artifact by report date and then generation time.
