# COT Positioning Thermo-Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the shipped COT behavior while replacing its unbatched reads, incomplete version identity, weak ports, duplicated metadata, and copy-pasted static/provider mechanics with focused typed components.

**Architecture:** Domain-owned dataset and instrument definitions feed provider, validation, query, and schema layers. A complete publication signature controls refresh reuse, the snapshot uses a batch read model, and shared global-artifact/request helpers remove duplicated orchestration without generalizing product-specific composition.

**Tech Stack:** Python 3.11, dataclasses/Protocols, SQLAlchemy, Pydantic 2, FastAPI, Pytest, React 18, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-16-cot-positioning-thermo-remediation-design.md`

## Global Constraints

- Preserve the existing public API and static JSON contracts exactly.
- Preserve the curated 31 instruments and their current order.
- Preserve CFTC Futures Only source filtering and all calculation formulas.
- Preserve best-effort Yahoo pricing; price failure cannot block publication.
- Do not change the database schema or migration history.
- Every production behavior change starts with a focused failing test.

---

### Task 1: Canonicalize COT dataset and instrument metadata

**Files:**
- Modify: `backend/app/domain/cot/models.py`
- Modify: `backend/app/domain/cot/registry.py`
- Modify: `backend/app/domain/cot/validation.py`
- Modify: `backend/app/infra/providers/cftc_cot.py`
- Modify: `backend/app/use_cases/cot/queries.py`
- Modify: `backend/app/schemas/cot.py`
- Modify: `backend/app/services/static_cot_contract.py`
- Test: `backend/tests/unit/test_cot_registry.py`
- Test: `backend/tests/unit/test_cot_validation.py`
- Test: `backend/tests/unit/test_cftc_cot_provider.py`

**Interfaces:**
- Produces: `CotDatasetDefinition`, `dataset_for_family(family)`, and typed `CotInstrumentSpec` entries.
- Removes: duplicated dataset maps, positional registry strings, slug conditionals, and duplicate static schema constants.

- [ ] **Step 1: Write failing ownership tests**

```python
def test_each_report_family_has_one_complete_dataset_definition():
    assert dataset_for_family(ReportFamily.TFF_FUTURES_ONLY).dataset_id == "gpe5-46if"
    assert dataset_for_family(ReportFamily.DISAGGREGATED_FUTURES_ONLY).dataset_id == "72hh-3qpy"

def test_canola_price_metadata_is_declared_in_its_spec():
    assert instrument_by_slug("canola").price.tradingview_url.endswith("/contracts/")
```

- [ ] **Step 2: Run tests and verify missing-definition failures**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cot_registry.py tests/unit/test_cot_validation.py tests/unit/test_cftc_cot_provider.py`

- [ ] **Step 3: Implement typed definitions and route every backend consumer through them**

Use enum fields directly in `CotInstrumentSpec`; keep provider field mappings on `CotDatasetDefinition`; import `STATIC_COT_SCHEMA_VERSION` from domain models.

- [ ] **Step 4: Run focused tests and commit**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cot_registry.py tests/unit/test_cot_validation.py tests/unit/test_cftc_cot_provider.py tests/unit/test_cot_queries.py tests/unit/test_cot_schemas.py`

Commit: `refactor: centralize COT metadata`

---

### Task 2: Make refresh boundaries typed and publication reuse version-aware

**Files:**
- Modify: `backend/app/use_cases/cot/ports.py`
- Modify: `backend/app/use_cases/cot/refresh.py`
- Modify: `backend/app/infra/db/repositories/cot_repository.py`
- Modify: `backend/app/services/cot_price_hydrator.py`
- Test: `backend/tests/unit/test_cot_refresh.py`
- Test: `backend/tests/unit/test_cot_repository.py`

**Interfaces:**
- Produces: `CotPublicationSignature`, `CotWriteRepository`, `CotPriceHydrationResultPort`, and `CotPriceHydratorPort`.
- `CotWriteRepository.publication_signature() -> CotPublicationSignature | None` is the only no-change input.

- [ ] **Step 1: Write a failing version-only republish test**

```python
def test_refresh_republishes_when_calculation_version_changes():
    first = use_case.execute(CotRefreshCommand(origin="test"))
    repository.signature = replace(repository.signature, calculation_version="old")
    second = use_case.execute(CotRefreshCommand(origin="test"))
    assert first.status == second.status == "published"
```

- [ ] **Step 2: Run refresh/repository tests and verify the second run incorrectly reports no-change**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cot_refresh.py tests/unit/test_cot_repository.py`

- [ ] **Step 3: Implement the complete signature and exact protocols**

Build the requested signature from source fingerprints plus the command's run-request versions. Build the stored signature from the published run and persisted rows. Replace constructor `Any` annotations with protocols.

- [ ] **Step 4: Run focused tests and commit**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cot_refresh.py tests/unit/test_cot_repository.py tests/unit/test_cot_price_hydrator.py`

Commit: `fix: version COT publication identity`

---

### Task 3: Batch the live snapshot read

**Files:**
- Modify: `backend/app/use_cases/cot/ports.py`
- Modify: `backend/app/use_cases/cot/queries.py`
- Modify: `backend/app/infra/db/repositories/cot_repository.py`
- Modify: `backend/app/infra/query/cot_prices.py`
- Test: `backend/tests/unit/test_cot_queries.py`
- Test: `backend/tests/unit/test_cot_repository.py`

**Interfaces:**
- Produces: `CotSnapshotPositionRecord`, `CotReadRepository.get_snapshot_history(weeks=52)`, and `CotPriceReader.closes_many(requests)`.
- Removes: `CotQueryService.external_calls` and snapshot recursion through `history()`.

- [ ] **Step 1: Write a failing bounded-call test**

```python
def test_snapshot_uses_one_repository_batch_and_one_price_batch():
    snapshot = query_service.snapshot()
    assert len(snapshot.rows) == 31
    assert repository.history_calls == []
    assert repository.snapshot_history_calls == [52]
    assert price_reader.batch_calls == 1
```

- [ ] **Step 2: Run query tests and verify current per-instrument history calls fail the assertion**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cot_queries.py`

- [ ] **Step 3: Add the SQL/read DTO batch and assemble rows once**

Use a window-ranked subquery to select the last 52 dates per instrument, filtered to each instrument's focal participant. Batch price requests by symbol and align each instrument independently; expose only the last 12 net values as the trend.

- [ ] **Step 4: Run API/query/repository tests and commit**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cot_queries.py tests/unit/test_cot_repository.py tests/unit/test_cot_api.py`

Commit: `perf: batch COT snapshot reads`

---

### Task 4: Consolidate CFTC request retry handling

**Files:**
- Modify: `backend/app/infra/providers/cftc_cot.py`
- Test: `backend/tests/unit/test_cftc_cot_provider.py`

**Interfaces:**
- Produces: private `_request_json(dataset_id, params, operation) -> tuple[Any, int]`.
- Page and count methods retain distinct schema decoders and error messages.

- [ ] **Step 1: Add a failing parity test for count and page retry behavior**

```python
@pytest.mark.parametrize("operation", ["page", "count"])
def test_transient_retry_budget_is_shared(operation):
    result = invoke(operation, statuses=[503, 503, 200])
    assert result.retry_count == 2
    assert sleeps == [1.0, 2.0]
```

- [ ] **Step 2: Run provider tests and verify the wished-for shared seam is absent**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cftc_cot_provider.py`

- [ ] **Step 3: Extract one retry operation and keep decoder validation separate**

- [ ] **Step 4: Run provider tests and commit**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_cftc_cot_provider.py`

Commit: `refactor: unify CFTC request retries`

---

### Task 5: Parameterize global static artifact mechanics

**Files:**
- Create: `backend/app/services/static_global_artifacts.py`
- Create: `backend/app/services/static_artifact_io.py`
- Modify: `backend/app/services/static_cot_contract.py`
- Modify: `backend/app/services/static_options_contract.py`
- Modify: `backend/app/services/static_cot_exporter.py`
- Modify: `backend/app/services/static_options_exporter.py`
- Modify: `backend/app/scripts/download_static_market_fallbacks.py`
- Modify: `backend/app/scripts/validate_static_market_artifacts.py`
- Test: `backend/tests/unit/test_static_cot_pipeline.py`
- Test: `backend/tests/unit/test_static_options_exporter.py`
- Test: `backend/tests/unit/test_static_site_workflow.py`

**Interfaces:**
- Produces: `StaticGlobalArtifactSpec`, `GLOBAL_STATIC_ARTIFACTS`, `find_global_artifact`, `global_artifact_as_of_date`, `load_finite_json`, `safe_artifact_path`, and `write_static_json`.
- Product-specific COT and Options validators remain responsible for semantic contracts.

- [ ] **Step 1: Write failing parameterized discovery/validation tests for both artifact kinds**

```python
@pytest.mark.parametrize("key", ["options", "cot"])
def test_global_artifact_spec_finds_a_nested_valid_bundle(key, artifact_fixture):
    spec = GLOBAL_STATIC_ARTIFACTS[key]
    assert find_global_artifact(spec, artifact_fixture).is_dir()
```

- [ ] **Step 2: Run static tests and verify the common API is missing**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_static_cot_pipeline.py tests/unit/test_static_options_exporter.py tests/unit/test_static_site_workflow.py`

- [ ] **Step 3: Implement the descriptors and replace dedicated script branches with loops**

Keep CLI flags and GitHub artifact names backward-compatible. Use common finite JSON/path/write helpers without weakening either semantic validator.

- [ ] **Step 4: Run static/export tests and commit**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_static_cot_pipeline.py tests/unit/test_static_cot_exporter.py tests/unit/test_static_options_exporter.py tests/unit/test_export_static_site_script.py tests/unit/test_static_site_workflow.py tests/unit/test_static_site_export_service.py`

Commit: `refactor: share global static artifact mechanics`

---

### Task 6: Remove the thin RRG wrapper and complete verification

**Files:**
- Modify: `backend/app/services/static_groups_rrg_export.py`
- Modify: `backend/app/services/static_site_export_service.py`
- Delete: `backend/app/services/static_groups_rrg_section.py`
- Modify: `backend/tests/unit/test_static_site_export_service.py`
- Modify: `docs/runbooks/cot-positioning.md`

**Interfaces:**
- `_build_optional_section_payload` translates `StaticGroupsRRGUnavailableError` into the existing unavailable payload path.
- Removes: `build_static_groups_rrg_section` and the pass-through `_build_groups_rrg_payload` method when callers can invoke the source directly.

- [ ] **Step 1: Write a failing source-boundary translation test**

```python
def test_optional_section_translates_rrg_source_failure():
    payload = exporter._build_optional_section_payload(build=raising_rrg_source, ...)
    assert payload["available"] is False
```

- [ ] **Step 2: Run the static exporter test and verify the source error currently requires the wrapper**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_static_site_export_service.py`

- [ ] **Step 3: Move translation into the optional-section handler, delete the wrapper, and update the runbook ownership notes**

- [ ] **Step 4: Run all verification gates**

Run:

```bash
cd backend && ./venv/bin/pytest -q tests/unit/test_cot_registry.py tests/unit/test_cftc_cot_provider.py tests/unit/test_cot_validation.py tests/unit/test_cot_refresh.py tests/unit/test_cot_repository.py tests/unit/test_cot_queries.py tests/unit/test_cot_api.py tests/unit/test_static_cot_exporter.py tests/unit/test_static_cot_pipeline.py tests/unit/test_static_cot_section.py tests/unit/test_static_site_export_service.py tests/unit/test_export_static_site_script.py tests/unit/test_static_site_workflow.py
cd backend && ./venv/bin/pytest -q
cd frontend && npm run test:run
cd frontend && npm run lint
cd frontend && npm run build
git diff --check
```

- [ ] **Step 5: Commit**

Commit: `refactor: finish COT thermo remediation`
