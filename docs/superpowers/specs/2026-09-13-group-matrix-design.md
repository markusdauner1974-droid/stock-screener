# Group Matrix Design

Date: 2026-09-13

Status: Implemented on `feat/group-matrix`. Functional verification is recorded in the implementation plan; the 200ms stress-performance target remains unmet.

## Goal and decisions

Add a **Matrix** tab beside Table and RRG on the Group page. Show individual stocks organized by sector, IBD industry group, and market-cap tier. Help users see whether strength is broad across an industry or concentrated in particular company sizes.

The user confirmed **both Grid and Clusters layouts with individual stock tiles**. This design assumes both live and static pages, published daily data, and all existing Group markets with actual IBD coverage. The user subsequently authorized inline implementation on a new feature branch; these defaults were carried into the implementation.

This is a native visualization using application data. Finviz supplies visual inspiration, not prices, classifications, embedded content, or assets.

## Reference inspection

- [Finviz Matrix / Grid](https://finviz.com/map?t=sec_all&view=matrix&ref=finviz.com): visually inspected in the browser. Sector bands contain industry rows, five market-cap columns contain compact stock tiles, and crowded cells expose a remaining-stock count. Controls include sector, industry, cap tiers, ticker search, and color metric. The legend shows daily performance from negative to positive.
- [Finviz Matrix / Clusters](https://finviz.com/map?t=sec_all&view=matrix&ref=finviz.com&render=clusters): the browser confirmed Clusters selected, the same filters, and five cap headings without the Grid industry heading. Screenshot capture failed, so exact cluster geometry and hover behavior were not verified. The deterministic cluster arrangement below is a proposed adaptation, not a claim of pixel-identical Finviz behavior.

## Existing implementation and implications

| Existing file | Relevant finding |
|---|---|
| `frontend/src/pages/GroupRankingsPage.jsx` | Live page owns Table/RRG state, bootstrap data, market selection, and group dialog. Table queries currently run whenever the view is not RRG. Matrix must have its own query and error boundary. |
| `frontend/src/static/pages/StaticGroupsPage.jsx` | Static page reads groups and RRG assets; early ranking failures currently block the whole page. Matrix must remain accessible independently. |
| `frontend/src/components/Charts/RRGViewToggle.jsx` | Shared Table/RRG toggle forces Table when RRG is unavailable. Introduce a Group-specific three-tab control instead of coupling Matrix availability to RRG. |
| `frontend/src/components/Charts/useRRGScopeSelection.js` | Scope correction already applies only to RRG; preserve that behavior. |
| `backend/app/services/group_detail_payloads.py` | Intermediate rows contain market caps and daily change, but serialized constituent payloads omit caps and sectors. Do not fetch every group detail to reconstruct the matrix. |
| `backend/app/infra/db/models/feature_store.py` | Published runs and per-run symbol membership support a coherent daily stock universe. |
| `backend/app/infra/db/repositories/feature_store_repo.py` | Stock output combines daily features with mutable universe/fundamental metadata; `market_cap_usd` comes from a joined fundamental row. |
| `backend/app/services/feature_run_group_enrichment.py` | Non-US `ibd_industry_group` values can actually be market-local taxonomy. Never label this field as IBD without verifying its origin. |
| `backend/app/models/industry.py` | `IBDIndustryGroup` stores explicit market, group name, source, confidence, and update timestamp. Read this table for actual IBD mappings. |
| `backend/app/services/static_site_export_service.py` | Exports separate per-market assets and a manifest; Matrix belongs in its own optional asset. |
| `backend/app/services/static_artifact_combiner.py` | Combined exports validate advertised assets; add validation for Matrix too. |

## Approaches considered

1. **Recommended: one compact stock payload, shared React presentation.** Dedicated read endpoint plus equivalent static asset; CSS Grid for aligned rows and CSS flow for clusters. Uses installed MUI and TanStack Virtual. Keeps data rules consistent and interactions accessible.
2. Reconstruct from existing group details. Smaller initial API change, but requires many requests or large chart-bearing payloads, omits needed fields, and risks truncating the universe. Rejected.
3. Canvas or a general charting engine. Useful for very large continuously zoomable maps, but adds hit testing, keyboard navigation, and layout complexity. Defer unless the measured performance targets cannot be met with bounded DOM rendering.

## Scope

Included:

- Matrix as a third top-level Group tab, with Grid as its default layout.
- Sector sections → actual IBD groups → individual stocks, split across cap tiers.
- Grid and Clusters, sector/IBD/tier filters, ticker/company search, daily-change and stock-RS coloring.
- Stock detail drawer, industry constituent list, coverage and freshness information.
- Existing market selector; one market at a time. No cross-market aggregate RS comparison.
- Both live and static paths using the same response shape and components.

Excluded from this release: intraday quotes, new data providers, classifier runs triggered by viewing, historical replay, custom cap boundaries, market-cap-sized tiles, force simulation, correlation clustering, logos, portfolio actions, and additional return horizons.

## Layout and controls

```text
US Group Rankings                                  [existing market selector]
[ Table ] [ RRG ] [ Matrix ]

[ Grid | Clusters ]  Color [1-Day Change v]          [Reset filters]
[Sector: All v] [IBD group: All v] [Search symbol/company........]
Tiers: [Large/Mega] [Mid] [Small] [Micro] [Nano] [Unknown]
Daily data: Sep 11   Metadata read: Sep 13   4,812 shown / 5,120
IBD coverage: 94%    [red ... neutral ... green legend]   [Data coverage]

GRID
Sector / IBD group     Large/Mega       Mid         Small        ...
Technology (count) ──────────────────────────────────────────────────
Computer Sftwr-...     [AAA +1.2%]      [BBB -0.8%] [CCC —]
                      [DDD +0.4%]      [+18 more]  [EEE +2.1%]
Elec-Semiconductor    [FFF +1.0%]       [GGG +2.0%] ...

CLUSTERS
Large/Mega             Mid                     Small              ...
[Technology]           [Technology]            [Technology]
┌ Computer Sftwr... ┐  ┌ Elec-Semiconductor ┐   ┌ Computer Sftwr... ┐
│ AAA  DDD  ...     │  │ GGG ...            │   │ CCC  EEE ...      │
└──────────────────┘  └────────────────────┘   └───────────────────┘
```

The examples are illustrative, not real stock data. Use existing theme surfaces, typography, borders, and dark/light modes. Sector headings use restrained accents, never performance coloring. Tile area is constant; color represents the selected metric. Cap is encoded only by column membership.

### Grid

Columns have a minimum width of 200px; the label column is 220px. Use one scroll container with sticky column headings and a sticky left label column. Industry rows are aligned across tiers. Sector order and IBD name order are alphabetical, with Unknown/Unclassified last. Row key is `(market, sector, ibd_group)` because one IBD group can have constituents in more than one sector.

Each cell initially shows up to 12 stocks sorted by finite USD market cap descending, then symbol ascending; null caps sort last. Tiles have at least a 72px width and 28px height. A `+N more` button opens the complete cell constituent list. Keep row height bounded by four tile lines; sector headers and industry rows are virtualized. All stocks remain accessible even when not initially drawn.

### Clusters

Keep the same cap columns. Within each column, stack sector sections and then labeled IBD cluster cards alphabetically. Cards pack constant-size tiles using CSS Grid; height follows the number of visible tiles, so industries do not need to line up horizontally across tiers. Empty industry/tier combinations disappear. Show up to 24 stocks per cluster plus `+N more` opening the full list. Virtualize the vertical card stream separately per cap column, with a fixed-height shared viewport and independent column scrolling; keep headers visible. This deliberate UI difference gives clusters more compact packing while Grid supports direct row comparison.

No random positioning or inferred relationships. Switching layouts preserves metric, filters, and selection, but resets scroll position. Both layouts show identical matching stock sets and counts.

### Filters and selection

- Sector and IBD group filters intersect; IBD options are constrained by selected sector. Changing sector clears an incompatible selected group.
- Tier selection defaults to all, including Unknown. Zero selected tiers yields an empty result with Reset available; do not silently reselect all.
- Search is case-insensitive substring matching against symbol and company name. It filters both layouts, and updates the matching count. No network request for each keystroke.
- Market change clears sector, group, search, stock selection, and drawer state; preserve layout, color metric, and tier preferences for the mounted page. Do not render the previous market while the new one loads.
- Version 1 has no URL-state contract or cross-session persistence.

### Drilldowns

Hover or keyboard focus shows symbol, company, market, sector, IBD group, classification source, USD cap, daily change, RS, and relevant dates. Click/Enter/Space opens a shared stock drawer showing the same data and an explicit group-constituents action. This works without chart data or live APIs.

Industry heading click opens a Matrix constituent drawer for that `(sector, IBD group)` across selected tiers and search results. The drawer title includes the current filter context. Do not route non-US IBD selections into the existing local-taxonomy ranking dialog. A future chart integration is outside this release.

Escape closes drawers and restores focus to the trigger. Full constituent lists use existing virtualization for large groups. Tooltips are supplementary; all information is available by click/touch.

## Data semantics

### Universe and taxonomy

Use all per-stock feature rows belonging to one published feature run for the selected market, regardless of CANSLIM/Minervini pass status, ranking eligibility, or current scan filters. Count run membership separately from available feature rows. Never use a top-197 group response as the stock universe.

Sector is the feature row's `gics_sector` when present, otherwise stored `StockUniverse.sector`, otherwise `Unknown sector`. Read the IBD mapping from `IBDIndustryGroup` joined by namespaced symbol **and market**, not from non-US feature group labels. Preserve mapping source/confidence; auto-classified entries are labeled as such, not represented as official IBD assignments. Trim names but do not infer taxonomy from free-form provider industry strings.

Missing IBD mappings belong to `Unclassified IBD`. Stocks remain visible, with coverage shown. If a market has zero explicitly mapped IBD stocks, return an unavailable matrix with reason `missing_ibd_mappings`; do not substitute local taxonomy. An IBD group spanning sectors appears once in each relevant sector with only that sector's stocks; never duplicate a stock globally.

### Market-cap tiers

Use finite, positive `StockFundamental.market_cap_usd` in whole USD. Do not interpret `StockUniverse.market_cap` or local-currency values as USD, and do not perform request-time FX conversion.

| ID | Display | Lower inclusive | Upper exclusive |
|---|---|---:|---:|
| large_mega | Large/Mega | $10B | none |
| mid | Mid | $2B | $10B |
| small | Small | $300M | $2B |
| micro | Micro | $50M | $300M |
| nano | Nano | greater than $0 | $50M |
| unknown | Unknown cap | missing, nonpositive or nonfinite | — |

These are application-defined thresholds inspired by the reference categories; exact Finviz thresholds were not verified. The backend assigns the tier and returns the tier definitions. The frontend must not duplicate boundary calculations.

### Metrics and colors

- Default: persisted `price_change_1d`, expressed as percentage points, not a fraction. The source producer's unit and previous-trading-session meaning must be checked with a known price fixture before implementation is accepted. Do not calculate change from compressed sparklines.
- Daily scale: clamp only the color at −3%/+3%, show exact values in text. Use seven stops at −3, −2, −1, 0, +1, +2, +3, with smooth interpolation or fixed documented bins. Zero is neutral, absent is gray/hatched with `—`.
- Alternative: persisted stock `rs_rating`, valid within 0–100, labeled `Stock RS`. Reuse Group RS tone semantics (`<=20`, `<=30`, neutral, `>=70`, `>=80`) and show their ranges in the legend. Never color stocks with group rank or treat RS as return percentage.
- Missing/invalid metrics remain on the map. Stock tiles show symbol plus the selected value when space permits; exact values always appear in the drawer.

### Dates and provenance

Feature membership, return, and RS come from the same published run and its resolved RS identity. Resolve that identity using `resolve_feature_run_rs_identity`. Static export uses its already-selected run; live uses the newest compatible published run for that market. Reject partial/mismatched identity rather than mixing runs. No historical date selector in version 1.

IBD mapping, fallback sector, company name, and USD cap are **latest stored metadata read at payload assembly**, not guaranteed to be historical as of the feature date. Explicitly expose `metadata_read_at`, per-stock fundamental update time and classification update time, and `metadata_basis: latest_stored`. `metadata_read_at` is not the quote time. Static export freezes these values at build time; later live responses may move a stock between tiers after metadata updates. Live/static parity means identical input rows produce identical output, not that exports refresh after publication.

Use the existing market calendar/freshness machinery where available to compare the feature date against the latest completed session; weekends alone do not make Friday data stale. Until that determination is available, show the explicit data date without claiming freshness. No intraday refresh claim.

## Shared response contract

New live route: `GET /api/v1/groups/matrix?market=US`. No `as_of_date` or user-selected run ID for this release. Normalize and validate the market using Group capability conventions. Declare the literal `/matrix` route before any competing dynamic route.

```json
{
  "schema_version": "group-matrix-v1",
  "available": true,
  "reason": null,
  "market": "US",
  "feature_run_id": 123,
  "as_of_date": "2026-09-11",
  "rs_formula_version": "<resolved stored formula>",
  "market_rs_run_id": 456,
  "rs_universe_size": 5120,
  "generated_at": "2026-09-13T06:00:00Z",
  "metadata_read_at": "2026-09-13T06:00:00Z",
  "metadata_basis": "latest_stored",
  "taxonomy": "ibd",
  "coverage": {
    "universe_count": 5120, "stock_count": 5000,
    "missing_feature_count": 120, "ibd_mapped_count": 4700,
    "unknown_sector_count": 30, "unknown_cap_count": 100,
    "missing_daily_change_count": 40, "missing_rs_count": 50
  },
  "tiers": [
    {"id": "large_mega", "label": "Large/Mega", "min_usd": 10000000000, "max_usd": null},
    {"id": "mid", "label": "Mid", "min_usd": 2000000000, "max_usd": 10000000000},
    {"id": "small", "label": "Small", "min_usd": 300000000, "max_usd": 2000000000},
    {"id": "micro", "label": "Micro", "min_usd": 50000000, "max_usd": 300000000},
    {"id": "nano", "label": "Nano", "min_usd": 0, "max_usd": 50000000},
    {"id": "unknown", "label": "Unknown cap", "min_usd": null, "max_usd": null}
  ],
  "stocks": [{
    "symbol": "EXAMPLE", "company_name": "Illustrative company",
    "sector": "Technology", "ibd_industry_group": "Computer Sftwr-Enterprise",
    "classification_source": "csv", "classification_confidence": null,
    "classification_updated_at": "2026-09-10T00:00:00Z",
    "market_cap_usd": 2500000000, "cap_tier": "mid",
    "fundamentals_updated_at": "2026-09-11T22:00:00Z",
    "price_change_1d": 1.25, "rs_rating": 87.4
  }]
}
```

Example values illustrate the shape; coverage describes a larger omitted stock set. Actual payload includes every stock once. All numeric values must be finite or null. Unknown sector/group serialize as null; presentation supplies labels. Coverage counts overlap and are not additive exclusions. IBD coverage denominator is `stock_count`; display missing feature rows separately.

For no publication, invalid publication identity, or absent IBD coverage, return HTTP 200 with `available:false`, a stable reason (`no_published_run`, `no_feature_rows`, `publication_identity_mismatch`, `missing_ibd_mappings`), empty stocks, and whatever coverage can safely be reported. Missing identity fields are nullable in unavailable envelopes. Unsupported market is 400; malformed query validation follows FastAPI; unexpected failures are 500. Do not disguise database errors as empty coverage.

## Architecture and performance

One bulk repository projection loads feature rows and metadata, scoped to a validated run and market. Avoid one query per stock or industry. A pure builder normalizes fields, assigns tiers, calculates coverage, and serializes the response. Live service and static export both invoke that builder; no schema migration or new scheduler is required.

Cache live assembled responses for 60 seconds using the existing Group cache, including market, feature-run identity and schema version in the key. Resolve the selected run before response-cache lookup so a new publication is not served behind an old run key. Metadata can lag by that TTL; this is consistent with the daily UI. Endpoint is read-only and must not invoke providers, bootstrap, classification, or calculation tasks.

Export `markets/<market>/groups_matrix.json`, advertised through optional `assets.groups_matrix.path`. Build it using the static export's selected feature run; keep it separate from `groups.json`. Missing Matrix data must not fail otherwise-valid Table/RRG exports. An advertised missing, malformed, wrong-market, or wrong-run asset must fail artifact validation. Older manifests without the asset remain supported.

Lazy-load Matrix and fetch only when selected. Live query key includes market; static key includes market and resolved asset path. Neither rankings nor RRG errors block Matrix. Market switches clear old visual data. Keep caching and source selection out of presentation components.

Performance acceptance targets, measured rather than assumed: at 10,000 fixture stocks and 200 IBD groups, visible-map DOM remains under 2,000 stock buttons; filter/layout update p95 under 200ms on the recorded developer machine after data load; compressed asset under 2MB. No sparkline arrays in the matrix asset. Measure three warmed runs and report fixture/browser/machine. If targets fail, optimize row/card virtualization and payload fields before adopting canvas.

## Accessibility and responsive behavior

Use MUI Tabs with linked tab panels. Use semantic buttons for stocks, overflow controls, and group headings. Provide a labeled region describing row/column semantics; do not claim an ARIA grid unless implementing its full keyboard navigation. Each stock accessible name includes symbol, metric, sector, group, and tier. Support keyboard focus, Enter/Space, Escape, and focus restoration.

At narrow widths, controls wrap, filters can collapse behind a labeled button, and the map scrolls horizontally within its own region. Page body does not overflow. Minimum interactive target on touch is 44px; increase tile height there. Provide a `View matching stocks` list action on mobile and desktop as an accessible alternative. Distinguish missing values from zero and retain numeric labels so color is not the sole encoding.

## Acceptance criteria

1. Table, RRG, and Matrix remain independently usable in live and static modes; Matrix is never gated by RRG availability.
2. Both layouts contain the same filtered stock set and use sector, actual IBD mappings, and USD tiers.
3. Stocks with missing metrics, cap, sector, or some missing mappings are visible; coverage and missing-feature counts are correct.
4. Non-US local-taxonomy values cannot silently appear as IBD names; same-symbol wrong-market mappings cannot join.
5. Each stock appears exactly once in a layout's underlying model; every overflow stock is reachable through a complete constituent list.
6. All tier boundaries, percent units, RS colors, filters, drawer focus, and market-switch races are tested.
7. Daily features have one publication identity; mutable metadata is separately dated and described.
8. Loading/error/empty states stay within the active panel; older static exports remain usable without live requests.
9. Performance, keyboard, dark/light theme, and 390px/1440px width checks meet the stated criteria.

## Review points

User-confirmed: both layouts and individual stock tiles. The subsequent request authorized inline implementation on a new feature branch with no subagents. Implementation uses all eligible markets, both delivery modes, daily change/RS, and the deterministic Clusters arrangement. See the accompanying plan’s execution record for delivered files, validation and deviations.

## Measured implementation limits

The feature is implemented. The 10,000-stock live production fixture compressed to 131,000 bytes and kept both retained layout windows together below 2,000 stock buttons. Three layout-switch click-to-next-frame samples were 1,595.9ms, 210.8ms and 1,113.1ms on this macOS arm64 host using Chrome 152.0.7977.83. These measurements improve on the initial per-tile MUI implementation but do **not** meet the proposed 200ms target. Filter latency was not separately benchmarked. Treat acceptance criterion 9's performance portion as an open optimization item; functional stock reachability and rendering bounds are verified.

Native button tiles and memoized retained layouts avoid rebuilding stock components on each switch. Inactive layouts remain bounded, inert, and hidden from assistive technology. Browser style/layout work still needs profiling before claiming the original latency target.

Static mode measured 2,817.5ms, 561.1ms and 510.6ms with the same fixture; it also misses the original latency target.
