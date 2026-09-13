# Group Matrix Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task after design review. Steps use checkbox syntax for tracking. The user subsequently authorized inline implementation on a new feature branch, without subagents. Implementation uses `feat/group-matrix`; the execution record below supersedes the original documentation-only scope.

**Implementation status:** Functional feature delivered on `feat/group-matrix`; the original 200ms stress-latency target remains open. See the [execution record](#execution-record--2026-09-13) for actual results.

**Goal:** Add a sector/IBD industry stock Matrix tab with Grid and Clusters views to live and static Group pages.

**Architecture:** A bulk reader selects one published feature run and reads actual IBD mappings and stored USD caps. A pure payload builder feeds a dedicated API and optional static asset. Shared React components filter and display the payload with bounded, virtualized rendering.

**Tech Stack:** Existing FastAPI, SQLAlchemy, Pydantic, React 18, MUI 5, TanStack Query/Virtual, pytest, Vitest/Testing Library, and Playwright. No new runtime dependency planned.

**Spec:** [Group Matrix design](../specs/2026-09-13-group-matrix-design.md).

## Global constraints

- Both Grid and Clusters with individual stock tiles are user-confirmed.
- Proposed default: both live and static pages; all Group markets with actual IBD coverage.
- Sector sections → actual IBD groups → individual stocks, split across cap tiers.
- Use `IBDIndustryGroup` by symbol and market; non-US feature group labels may contain local taxonomy.
- USD tiers: Large/Mega ≥10B; Mid ≥2B; Small ≥300M; Micro ≥50M; Nano >0; invalid/missing cap → Unknown.
- Read one published feature run; no request-time providers, classification, bootstrap, calculation, or FX conversion.
- Daily features share a publication identity. Cap/classification metadata is latest stored, separately dated, and frozen only when exported.
- Default color is daily percentage-point change; alternate is stock RS 0–100. Missing values are not zero.
- The compact payload contains all eligible per-run feature rows, no chart/sparkline arrays and no scan-pass filter.
- Matrix must work independently of Table/RRG data availability.
- Implementation was subsequently authorized; no migration or deployment is required.

## File and interface map

All paths below are relative to the repository root. New paths are proposals; existing paths were inspected on 2026-09-13.

| File | Responsibility |
|---|---|
| Create `backend/app/schemas/group_matrix.py` | Pydantic envelope, stock, tier, coverage schemas |
| Create `backend/app/services/group_matrix_payloads.py` | Pure numeric normalization, tiers, coverage, serialization |
| Create `backend/app/services/group_matrix_repository.py` | Published-run resolution and bulk row/metadata read |
| Create `backend/app/services/group_matrix_service.py` | Identity validation and orchestration |
| Modify `backend/app/api/v1/groups.py` | Literal read-only `/matrix` route and cache wrapper |
| Modify `backend/app/services/static_site_export_service.py` | Build separate asset from selected run |
| Modify `backend/app/services/static_artifact_combiner.py` | Validate advertised asset identity and presence |
| Modify `frontend/src/api/groups.js` | `getGroupMatrix(market)` |
| Modify `frontend/src/static/dataClient.js` | `useStaticGroupMatrix(marketEntry, enabled)` |
| Create `frontend/src/features/groups/GroupViewTabs.jsx` | Table/RRG/Matrix navigation, independent availability |
| Create `frontend/src/features/groups/matrix/groupMatrixModel.js` | Filtering, grouping, ordering; no I/O |
| Create `frontend/src/features/groups/matrix/groupMatrixColors.js` | Daily colors, missing values, existing RS tone reuse |
| Create `frontend/src/features/groups/matrix/GroupMatrixPanel.jsx` | Controls, legend, counts, state and drawers |
| Create `frontend/src/features/groups/matrix/GroupMatrixGrid.jsx` | Sticky aligned rows and virtualization |
| Create `frontend/src/features/groups/matrix/GroupMatrixClusters.jsx` | Cap-column cluster streams and virtualization |
| Create `frontend/src/features/groups/matrix/GroupMatrixStockTile.jsx` | Accessible stock trigger and tooltip |
| Create `frontend/src/features/groups/matrix/GroupMatrixDetails.jsx` | Stock detail and complete constituent list drawer |
| Modify both Group page files | Query/view integration and panel-local failures |

Backend interfaces to implement:

```python
# group_matrix_payloads.py
def cap_tier(value: float | None) -> str: ...
def build_group_matrix_payload(*, rows: list[dict], metadata: dict,
                               universe_count: int) -> dict: ...

# group_matrix_repository.py
class GroupMatrixRepository:
    def latest_published_run(self, db, *, market: str): ...  # FeatureRun | None
    def load_rows(self, db, *, run_id: int, market: str) -> list[dict]: ...
    def universe_count(self, db, *, run_id: int) -> int: ...

# group_matrix_service.py
class GroupMatrixService:
    def __init__(self, repository=None): ...
    def build(self, db, *, market: str, feature_run_id: int | None = None,
              generated_at: str) -> dict: ...
```

The ellipses above denote interface declarations, not incomplete implementation tasks. `rows` has exactly the stock fields in the spec except `cap_tier`, plus `fundamentals_updated_at` and `classification_updated_at`. `metadata` contains the spec's envelope identity, dates, taxonomy and metadata basis. Builder returns the complete validated envelope including all six tiers. Service's optional run ID is for internal export only; API never accepts arbitrary run IDs.

Frontend interfaces:

```js
getGroupMatrix(market) // Promise<GroupMatrixEnvelope>
useStaticGroupMatrix(marketEntry, enabled) // TanStack query result
buildMatrixModel(stocks, { sector, group, tiers, search })
// => { stocks, sectors, gridRows, clustersByTier, stockCount }
matrixColor(value, metric, theme) // => { backgroundColor, color, missing }
// metric: 'price_change_1d' | 'rs_rating'

// GroupMatrixPanel props:
// { data, isLoading, error, onRetry, preferences, onPreferencesChange }
// preferences: { layout: 'grid' | 'clusters', metric, tiers: string[] }
// Page owns preferences; Panel owns sector/group/search/drawer state.
// GroupMatrixGrid / GroupMatrixClusters props:
// { model, tiers, metric, onSelectStock, onSelectStocks }
// onSelectStock(stock); onSelectStocks({ title, stocks })
// GroupMatrixDetails props:
// { selection, onClose }; selection is null, {stock}, or {title, stocks}
```

## Task 1: Define and test the compact payload

**Files:** Create schema and payload builder above; create `backend/tests/unit/test_group_matrix_payloads.py`.

**Consumes:** Plain source rows and metadata. **Produces:** `cap_tier` and `build_group_matrix_payload`.

- [ ] Add executable tier-boundary tests before implementing the builder:

```python
import pytest
from app.services.group_matrix_payloads import cap_tier

@pytest.mark.parametrize('value,expected', [
    (None, 'unknown'), (0, 'unknown'), (-1, 'unknown'),
    (float('nan'), 'unknown'), (float('inf'), 'unknown'),
    (1, 'nano'), (49_999_999, 'nano'), (50_000_000, 'micro'),
    (299_999_999, 'micro'), (300_000_000, 'small'),
    (1_999_999_999, 'small'), (2_000_000_000, 'mid'),
    (9_999_999_999, 'mid'), (10_000_000_000, 'large_mega'),
])
def test_cap_tier(value, expected):
    assert cap_tier(value) == expected
```

- [ ] Run `cd backend && ./venv/bin/python -m pytest tests/unit/test_group_matrix_payloads.py -q`; initially expect missing module/function.
- [ ] Implement the six tier definitions from the spec and finite-value normalization. Use this boundary logic:

```python
from math import isfinite

def cap_tier(value):
    if value is None or isinstance(value, bool):
        return 'unknown'
    if not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        return 'unknown'
    for threshold, name in ((10e9, 'large_mega'), (2e9, 'mid'),
                            (300e6, 'small'), (50e6, 'micro')):
        if value >= threshold:
            return name
    return 'nano'
```

- [ ] Add builder fixtures for three feature rows/four universe members: one mapped valid stock; one missing IBD/cap; one mapped stock with null return, out-of-range RS and unknown sector. Assert stock count 3, missing feature count 1, mapped count 2, invalid RS normalized to null, no NaN/Infinity JSON, all six tiers, and no duplicated symbol. Reject contradictory duplicate rows or universe count smaller than rows instead of returning misleading coverage.
- [ ] Implement Pydantic validation and the builder with the exact contract in the spec. Unknown sector/group are null. At the builder layer, return unavailable for no feature rows or no mapped IBD stocks; use `no_feature_rows` or `missing_ibd_mappings` respectively. The service separately handles publication availability. Unavailable output retains safe metadata/coverage.
- [ ] Verify the daily-change producer with a fixture representing prior close 100/current close 102: persisted value must be 2, not 0.02. Locate with `rg -n 'price_change_1d' backend/app`; test the producer or its existing fixture rather than hard-code an unverified unit conversion into Matrix.
- [ ] Run focused tests to green and commit only the schema/builder/tests when implementation is authorized.

## Task 2: Read one publication and expose the endpoint

**Files:** Create repository/service above; modify `backend/app/api/v1/groups.py`; create `backend/tests/unit/test_group_matrix_repository.py`, `test_group_matrix_service.py`, and `test_groups_matrix_api.py`.

**Consumes:** Task 1 builder and `resolve_feature_run_rs_identity`. **Produces:** Live envelope and internal selected-run export entry point.

- [ ] Create test database fixtures with published US/HK runs, a newer unfinished run, a wrong-market IBD row, missing fundamental metadata, a non-US local-taxonomy feature label, and actual IBD mappings. Follow adjacent repository tests for database/session setup.
- [ ] Assert selection ignores unfinished runs and other markets; internal selected run must be published and match requested market. Assert partial RS identity returns unavailable rather than silently selecting another run.
- [ ] Implement one bulk projection anchored on `StockFeatureDaily.run_id`; validate membership against `FeatureRunUniverseSymbol`. Outer join `StockUniverse`, `StockFundamental`, and `IBDIndustryGroup` by symbol with market-scoped conditions. Missing joins must not remove feature rows. Select only required fields. Do not loop through `get_constituent_items` per group.
- [ ] Source feature date/change/RS and preferred sector from the run; take IBD name/provenance from the explicit mapping table; take USD cap/update time from fundamentals. Assert a missing cap remains Unknown even when local cap is available. Assert HK local industry text never wins over an actual IBD mapping.
- [ ] Resolve live run using the established market metadata resolver and published-status ordering, not a global latest run. Resolve RS identity with the selected run's date. Build `metadata_read_at` from the assembly clock, retaining source timestamps; no historical metadata claim.
- [ ] Add API tests for supported market normalization, unsupported market 400, unavailable reason envelopes, unexpected service exception 500, and no provider/task calls. Implement literal `/matrix` before dynamic group routes. Use existing cache wrapper for 60 seconds and key by market/run/formula/schema; resolve run before cache lookup. Static callers bypass response cache.

```python
# Required regression assertions within fixtures using the real reader:
assert hk_payload['market'] == 'HK'
assert hk_payload['stocks'][0]['ibd_industry_group'] == 'Actual IBD fixture group'
assert hk_payload['stocks'][0]['cap_tier'] == 'unknown'
assert payload['feature_run_id'] == expected_published_run.id
```

- [ ] Run `cd backend && ./venv/bin/python -m pytest tests/unit/test_group_matrix_repository.py tests/unit/test_group_matrix_service.py tests/unit/test_groups_matrix_api.py tests/unit/test_groups_api_no_data.py -q`. Add a query-count assertion that does not grow with industry count, then commit the passing slice.

## Task 3: Publish and validate the static asset

**Files:** Modify `backend/app/services/static_site_export_service.py`, `backend/app/services/static_artifact_combiner.py`, `backend/tests/unit/test_static_site_export_service.py`, and `backend/tests/unit/services/test_static_artifact_combiner.py`.

**Consumes:** `GroupMatrixService.build(..., feature_run_id=selected_run.id)`. **Produces:** Optional `assets.groups_matrix.path` with the same envelope as live.

- [ ] Add failing export tests: same feature-run ID as export; no chart arrays; unavailable matrix does not break groups/RRG; old bundle without Matrix still combines; advertised missing/wrong-market/wrong-run/unsupported-schema asset is rejected.
- [ ] Assemble from `_export_market_bundle` after selected-run resolution, using the exact same run rather than fetching latest again. Write the asset and advertise it only when available:

```python
matrix_path = path_prefix / 'groups_matrix.json'
if matrix_payload['available']:
    self._write_json(output_dir / matrix_path, matrix_payload)
    assets['groups_matrix'] = {'path': matrix_path.as_posix()}
```

- [ ] Build unavailable messages through optional-section conventions. Do not swallow unrelated export failures. Keep Matrix out of `groups.json` and scan defaults/filtering. Preserve returned descriptor in per-market metadata and combined manifest.
- [ ] Add a validator in `_validate_advertised_assets` for Matrix path containment, JSON schema, market, feature run, date and RS identity against the market artifact metadata. No Matrix descriptor is a supported old-export case.
- [ ] Add a parity fixture: call the shared builder for identical live/static rows and clock, assert whole envelopes equal; separately assert later metadata updates can intentionally differ when clocks/input rows differ.
- [ ] Run the two modified test files and `backend/tests/unit/test_static_site_workflow.py`; commit this export slice.

## Task 4: Implement filtering and visual encoding

**Files:** Create `groupMatrixModel.js`, `groupMatrixColors.js` and matching `.test.js` files under `frontend/src/features/groups/matrix/`.

**Consumes:** Envelope stocks with backend-assigned tier. **Produces:** Model and color functions listed above.

- [ ] Add tests for sector+IBD+tier+search intersection, empty tier selection, case-insensitive name search, cross-sector group names, missing fields, stable ordering and duplicate protection. Include this independent behavior fixture:

```js
import { expect, it } from 'vitest';
import { buildMatrixModel } from './groupMatrixModel';

it('filters company names without losing tier membership', () => {
  const stocks = [
    { symbol: 'A', company_name: 'Alpha', sector: 'Tech', ibd_industry_group: 'Software', cap_tier: 'mid', market_cap_usd: 3e9 },
    { symbol: 'B', company_name: 'Beta', sector: 'Tech', ibd_industry_group: 'Software', cap_tier: 'small', market_cap_usd: 5e8 },
  ];
  const model = buildMatrixModel(stocks, {
    sector: null, group: null, tiers: ['mid', 'small'], search: 'ALPH',
  });
  expect(model.stocks.map(s => s.symbol)).toEqual(['A']);
  expect(model.stockCount).toBe(1);
});
```

- [ ] Implement filtering first, then grouping from the filtered set. Represent `gridRows` as sector headers and industry rows with `stocksByTier`; represent `clustersByTier[tier]` as sector headers and industry cards. Use compound sector/group keys, sort names alphabetically and stocks by finite cap descending then symbol. Do not drop overflow stocks from this model.
- [ ] Implement missing-value patterns separately from zero. Reuse `groupRsTone` from `../groupRsVisualEncoding.js`; use the spec's seven daily-change stops and clamp color only. Test exact −3/0/+3, extreme ±30, null/NaN, RS 20/30/70/80, and light/dark contrast.
- [ ] Run `cd frontend && npx vitest run src/features/groups/matrix/groupMatrixModel.test.js src/features/groups/matrix/groupMatrixColors.test.js`; commit the passing model slice.

## Task 5: Build the two layouts and drilldowns

**Files:** Create the five Matrix JSX files in the map above, plus `GroupMatrixPanel.test.jsx`, `GroupMatrixGrid.test.jsx`, `GroupMatrixClusters.test.jsx`, and `GroupMatrixDetails.test.jsx`.

**Consumes:** Task 4 model/colors. **Produces:** API-independent Matrix panel.

- [ ] Write user-interaction tests first: Grid default; layout switch retains filter/metric; stock selection opens detail; `+N more` exposes every hidden stock; group heading lists only matching constituents; Escape restores focus; null metric displays `—` while zero displays `0.00%`.
- [ ] Build controls, coverage summary and legend in Panel. Memoize filtering/grouping. Render drawers outside virtualized rows to avoid disappearing when the trigger scrolls offscreen. If a trigger is unmounted when closing, restore focus to the matching-list action.
- [ ] Implement Grid with a 220px label column and 200px minimum tier columns. Use sticky header/labels and `useVirtualizer` from installed `@tanstack/react-virtual` for the row stream. Render up to 12 stocks per cell plus overflow; bounded four-line cells prevent large industries from inflating every row.
- [ ] Implement Clusters as cap columns containing independently virtualized sector/header/card streams. Cards render up to 24 stocks then overflow, with measured heights. Use stable compound keys and reset scroll after filter/layout changes. No force simulation or new chart library.

```jsx
// Preserve the complete list for overflow; only the rendered preview is bounded.
const preview = stocks.slice(0, limit);
const remaining = stocks.length - preview.length;
// Render preview with GroupMatrixStockTile; then:
{remaining > 0 && (
  <Button onClick={() => onSelectStocks({ title, stocks })}>
    +{remaining} more
  </Button>
)}
```

- [ ] Make StockTile a real button with a complete accessible name and tooltip. Use a shared MUI Drawer for stock metadata or virtualized full constituent list. No navigation to non-US local-taxonomy group dialogs. Add `View matching stocks` alongside controls for an accessible full-list alternative.
- [ ] Implement wrapped controls, map-only horizontal overflow, minimum 44px touch targets, reduced-motion behavior, loading skeleton, unavailable/retry/no-match states, and explicit dates. Never generate “live” freshness wording.
- [ ] Run `cd frontend && npx vitest run src/features/groups/matrix`; commit this usable fixture-driven panel.

## Task 6: Integrate into both Group pages

**Files:** Modify both Group pages, `frontend/src/api/groups.js`, `frontend/src/static/dataClient.js`; create `frontend/src/features/groups/GroupViewTabs.jsx` and `.test.jsx`; modify `GroupRankingsPage.test.jsx`, `StaticGroupsPage.test.jsx`, and `frontend/src/api/groups.test.js`.

**Consumes:** Dedicated live/static envelope and shared Panel. **Produces:** New top-level Matrix tab in both modes.

- [ ] Add failing navigation/query tests: Matrix works with no RRG; failing rankings do not hide Matrix; inactive Matrix does not request data; static Matrix never requests live endpoints; old manifest has no Matrix fetch; market switch cannot display previous-market stock tiles.
- [ ] Add `getGroupMatrix(market)` following existing API client conventions and `useStaticGroupMatrix(marketEntry, enabled)` with query key `["staticGroupMatrix", marketEntry.market, path]`, `enabled: enabled && Boolean(path)`, and `staleTime: Infinity`.
- [ ] Add GroupViewTabs with actual MUI Tabs/Tab panels and independent Matrix/RRG availability. Keep the existing RRG scope selector visible only in RRG. Leave `RRGViewToggle` untouched for other consumers; remove its use from these two pages only.
- [ ] Replace live `!isRrgView` table-query gates with `view === 'table'`. Matrix's query is enabled by runtime readiness and Matrix selection, independent of Groups bootstrap success. Live query key is `["groupMatrix", selectedMarket]`, with 60-second staleness and polling only while active. Lazy-load Panel through React lazy/Suspense.
- [ ] Move Table-only loading/error/no-rank returns inside the Table panel in both pages. Manifest errors still block static market resolution, but groups asset errors cannot block an available Matrix asset. Preserve existing bootstrap seeding, calculation controls, and RRG scope fallback.

```jsx
// Integration shape; use the page's actual query variable names.
{view === 'matrix' && (
  <Suspense fallback={<CircularProgress />}>
    <GroupMatrixPanel
      key={selectedMarket}
      data={matrixQuery.data}
      isLoading={matrixQuery.isLoading}
      error={matrixQuery.error}
      onRetry={() => matrixQuery.refetch()}
      preferences={matrixPreferences}
      onPreferencesChange={setMatrixPreferences}
    />
  </Suspense>
)}
```

- [ ] Initialize page-owned `matrixPreferences` with `{ layout: 'grid', metric: 'price_change_1d', tiers: ['large_mega', 'mid', 'small', 'micro', 'nano', 'unknown'] }` using `useState`. Pass preferences and its setter as above. The keyed Panel resets sector/group/search/drawer state on market change; page preferences survive. Test this distinction explicitly.
- [ ] Run `cd frontend && npx vitest run src/pages/GroupRankingsPage.test.jsx src/static/pages/StaticGroupsPage.test.jsx src/api/groups.test.js src/features/groups/GroupViewTabs.test.jsx src/components/Charts/GroupChartsGrid.test.jsx`; commit integration after the Matrix component suite also remains green.

## Task 7: Verify full behavior and document release readiness

**Files:** Create `frontend/tests/smoke/group-matrix.spec.js` and `groupMatrixFixtures.js`; update these two documents with actual verification results during implementation.

**Consumes:** Integrated pages. **Produces:** Evidence against acceptance criteria, not a deployment.

- [ ] Use existing Playwright smoke configuration. Add deterministic live/static fixture routes with US and non-US actual-IBD data, empty/unavailable response, unknown cap, partial classifications, large groups, and a delayed response from the previously selected market.
- [ ] Verify both layouts, metric/filter changes, complete overflow lists, keyboard drawer open/close/focus, accessible full list, market switching, and failure isolation. Assert a non-US local group label never renders as an IBD heading.
- [ ] Capture browser screenshots at 1440px and 390px in both themes. Inspect tile labels, focus indicators, header alignment, map-contained horizontal scrolling, column scrolling in Clusters, and missing-value appearance. Test a touch-sized target and keyboard-only path.
- [ ] Measure 10,000-stock/200-group fixtures in three warmed runs: DOM stock buttons <2,000; filter/layout p95 <200ms; gzip asset <2MB. Record machine/browser and actual measurements. Optimize measured bottlenecks before declaring readiness.
- [ ] Run `cd frontend && npm run build`, `npm run lint`, and `npx playwright test tests/smoke/group-matrix.spec.js`. Run the new backend Matrix suites plus modified static export/combiner suites. Report pre-existing unrelated failures separately; do not claim they passed.
- [ ] Review spec acceptance criteria 1–9 against evidence. Confirm final diff contains no data-provider calls, taxonomy rewrites, scan-universe filter changes, or unrelated Group refactoring. Commit the final verification slice; implementation remains undeployed unless deployment is separately requested.

## Implementation order and review checkpoints

Tasks 1–3 establish reliable data; Task 4 establishes presentation rules; Task 5 yields a fixture-driven panel; Task 6 integrates both modes; Task 7 validates the complete flow. Review the payload/taxonomy contract after Task 2 and the two visual layouts after Task 5 before widening integration.

No database migration, provider subscription, new worker queue, or historical backfill is expected. Missing classifications and metadata are visible availability/coverage states, not a reason to add data acquisition to this feature.

## Execution record — 2026-09-13

Implemented inline on `feat/group-matrix` from the current checkout (`c68f2ee2`). No subagents, new runtime dependencies, database migration, provider calls, or deployment. The original task checklists above describe the planned sequence; this record tracks the delivered implementation rather than claiming every proposed file or intermediate commit was used verbatim.

| Task | Implementation and evidence |
|---|---|
| 1–2: Data contract and read service | Typed envelope, pure normalization and coverage builder, bulk SQL repository, published-run identity validation; real SQLite integration fixtures verify market, run, taxonomy, and bounded query count. |
| 3: Live and static delivery | Read-only cached API; optional static asset emitted from the export's selected run; combiner validates schema, path, duplicate symbols, coverage and publication identity. Legacy manifests remain supported. |
| 4–5: Presentation | Shared pure filter/group model, color utilities, Grid and Clusters, bounded tile previews, virtualized complete lists, accessible stock drawer and coverage. |
| 6: Integration | Independent Matrix tab on live/static Group pages, lazy queries and components, per-market filter reset with preserved layout/metric/tier preferences. Table/RRG regression checks pass. |
| 7: Verification | 152 backend tests and 42 frontend tests passed (37 feature/integration checks plus five navigation checks). Production browser results and the unmet stress-latency target are recorded below. |

Implementation details that refine the plan:

- `static_group_matrix.py` contains the optional export and validation helpers; `MatrixStockPreview.jsx` shares bounded previews between layouts. Tab behavior is tested through the two Group page suites rather than a separate tab-only test.
- Grid has a 220px sticky industry column (140px on mobile), with 238px minimum cap columns; Clusters uses independent 270px minimum columns. Horizontal scrolling stays inside the visualization.
- `playwright.matrix.config.js` builds and serves both production variants on isolated ports, using installed Chrome. The static fixture uses the application's hash route.
- Production testing exposed a circular React/query vendor split. React adapters now share the React vendor chunk in `vite.config.js`; this removes the startup failure.
- The live navigation toolbar now scrolls horizontally within its own bounds on narrow screens, avoiding page-wide overflow.
- A 10,000-stock benchmark exposed excessive per-tile MUI Tooltip/Button overhead. The initial implementation switched to native buttons and shared CSS with retained layout windows. The review follow-up below supersedes the native-title and retained-layout choices; cap formatting continues to reuse one formatter.
- Local native build packages needed repair for the installed Node architectures. Neither package manifest nor lockfile changed.

Validation commands:

```sh
./backend/venv/bin/python -m pytest backend/tests/unit/test_group_matrix_payloads.py backend/tests/unit/test_group_matrix_service.py backend/tests/unit/test_groups_matrix_api.py backend/tests/unit/test_static_group_matrix.py backend/tests/unit/test_group_rankings_cache.py backend/tests/unit/test_static_site_export_service.py backend/tests/unit/services/test_static_artifact_combiner.py backend/tests/unit/test_groups_api_no_data.py -q
cd frontend
npm run test:run -- src/features/groups/matrix src/pages/GroupRankingsPage.test.jsx src/static/pages/StaticGroupsPage.test.jsx src/api/groups.test.js src/components/Charts/GroupChartsGrid.test.jsx src/components/Charts/GroupChartsLayout.test.jsx
npm run lint
npx playwright test -c playwright.matrix.config.js
```

Backend Ruff checks passed. Frontend lint has no errors and four existing warnings in StockDetails, MarketContext and StaticMarketContext. Production builds succeed for both variants through the browser test configuration.

### Stress benchmark and remaining optimization

Fixture: 10,000 stocks / 200 IBD groups, six cap tiers; macOS arm64 host, installed Chrome 152.0.7977.83, production bundles. Compressed payload: **131,000 bytes**. DOM assertion includes both retained layout windows and passes **<2,000 stock buttons**. The full matching list reaches stock `US09999`.

Live click-to-next-animation-frame samples after optimization: **1,595.9ms, 210.8ms, 1,113.1ms**. These are three observed samples, not a statistically established p95. The initial implementation measured 5,506.3ms, 2,230.0ms and 5,110.1ms. Native tiles, shared formatting and retained memoized layouts improved switching, but the original **200ms target remains unmet**. Filter latency has not been independently benchmarked. Further browser style/layout profiling is a follow-up; no canvas or new rendering dependency was added speculatively.

Static layout-switch samples: **2,817.5ms, 561.1ms, 510.6ms**, with the same 131,000-byte fixture and DOM bound. The 200ms target is unmet in static mode as well.

### Final verification

- Backend: **152 passed** across the Matrix, cache, static export/combiner and Groups availability suites.
- Frontend: **42 passed** across eight suites on the final component implementation, including both Group pages and live navigation.
- Production browser: **6 passed**, covering live/static layouts, filter retention, keyboard drawer and focus restoration, 390px/1440px screenshots, light/dark themes, market switching and the 10,000-stock fixture. Static tests assert no live API requests. No uncaught page errors.
- Both production build variants passed through the browser configuration. Frontend lint: zero errors, four existing warnings; the changed Matrix files also pass targeted lint. Backend new-file Ruff checks and final whitespace checks passed.
- Functional acceptance is verified; the stress-latency target is explicitly not met. No deployment, push or merge was performed.

### Docker build correction

Reproduced the reported `vite/modulepreload-polyfill` source-phase error with the frontend Docker build. Compose uses `frontend/` as its build context, so the root ignore file did not exclude host dependencies. `COPY . .` overwrote Linux-installed JavaScript packages with local versions (local Rollup 4.63.2 versus locked 4.54.0; local Vite 6.4.3 versus locked 6.4.1), leaving an inconsistent installation.

Added `frontend/.dockerignore` to exclude host dependencies, generated build/test output and local environment files. The full image build then passed using locked Vite 6.4.1: `docker build --build-arg VITE_API_URL=/api -t stock-matrix-frontend-build-check ./frontend`. No dependency or application-code changes were needed. The running stack was not restarted.

## Review follow-up — 2026-09-14

Verified the PR findings against implementation and regression tests:

- Metadata provenance: `metadata_read_at` is now captured immediately after the metadata query, independently of the export-wide `generated_at`. A clock-controlled test exercises a metadata read later than export startup.
- Invalid manifests: non-mapping `assets` values raise the artifact validator's expected `ValueError`, which the combiner converts to `StaticArtifactFormulaError`. Tests include truthy and falsey invalid values.
- Refresh: completed calculations invalidate the market-specific Matrix query immediately.
- Rendering: each layout mounts on first selection. Visited inactive layouts keep their last props and do not render when filters change; their props update when selected again. This avoids rebuilding visited layouts on every switch while eliminating inactive filter work. A regression test verifies the hidden markup stays unchanged during filtering and catches up on activation.
- Inspection: one delegated Popper exposes the same complete metadata rows as the stock drawer on hover and keyboard focus; Escape dismisses it. Native stock buttons remain lightweight.

Validation: 183 backend regression tests and 44 frontend tests pass. The five panel tests also pass after adding a regression for pointer exit to a non-node target.

The proposed active-only mounting approach was tested and rejected as the final rendering solution: live switch samples were 3,542.0ms, 1,361.5ms and 2,036.8ms; static samples were 3,261.9ms, 1,255.5ms and 631.1ms. Retaining visited layouts with frozen inactive props addresses the review's alternative of preventing hidden-tree render work without paying remount cost on every switch. The first visit still creates that layout.

Final cached-layout click-to-next-frame samples: live **4,415.7ms, 260.8ms, 1,011.6ms**; static **5,446.5ms, 475.7ms, 314.0ms**. Chrome 152.0.7977.83, 10,000-stock fixture, 131,000 compressed bytes, fewer than 2,000 rendered stock buttons. These are three observations per mode, not p95 measurements. Repeat visits improved relative to active-only mounting in this run, while first visits became slower. The **200ms target remains unmet**; filter latency is not independently benchmarked.

The [reported row overflow](https://github.com/xang1234/stock-screener/pull/365#discussion_r3999697583) did not reproduce: a fixture with 50 stocks in one cap bucket keeps the 12 preview tiles and overflow button inside the row at 1440px and 390px, in both live and static builds. The existing 190px/238px row sizes remain unchanged, with a browser geometry regression added. No speculative variable-height implementation was added.

Final production browser verification: **8 passed**, covering both build variants, inspector hover/focus and Escape, stock drawers, filters, market switching, responsive rows and the large universe. The inspector screenshot was visually checked. Both production builds, targeted frontend lint, backend Ruff and whitespace checks passed. The final non-node pointer-exit guard was verified by the panel test after the browser builds.
