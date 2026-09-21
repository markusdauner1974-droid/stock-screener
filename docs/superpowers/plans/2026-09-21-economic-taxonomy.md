# Open Multi-Dimensional Economic Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pipeline-scoped and L1/L2 theme identity with a global Economic Theme taxonomy whose semantic snapshots, accepted evidence interpretations, projections, metrics, and reader pointers are published coherently and can be rolled back safely.

**Architecture:** Build an immutable processing taxonomy beside the legacy Theme Catalog, but expose it only through immutable serving generations. Frozen evidence packets feed immutable classification runs and assignments; each generation selects the accepted run for every source lineage. One publication coordinator prepares all artifacts outside the final lock, then atomically switches taxonomy, interpretation, metrics, and reader pointers under a short producer fence.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, PostgreSQL 16, SQLite unit/migration harness, Celery, existing LLM/embedding and Social-budget services, React, MUI, TanStack Query, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md`

**ADR:** `docs/adr/0005-economic-taxonomy-snapshots-and-interpretations.md`

**Status:** Revised and ready for review; no schema implementation is authorized by this document alone.

## Global Constraints

- `EconomicTheme.semantic_key` is an opaque UUID assigned once; mutable semantic fields live only in version-owned rows.
- Taxonomy versions have only `draft|sealed`; a sealed version cannot reopen, mutate, or receive moved rows.
- `taxonomy_authority.processing_taxonomy_version_id` is not a reader pointer. Readers use only `serving_generation_id`.
- A serving generation binds one sealed taxonomy, interpretation set, evidence manifest, metrics revision, UI/API snapshot bundle, and reader-capability manifest.
- Source-family identity, evidence-packet identity, processing-policy identity, and lens-eligibility identity are separate.
- Successful empty classification is authoritative when selected; failed or partial classification never replaces the last accepted run.
- Similarity retrieves candidates but never authorizes equivalence.
- Proposed-candidate relationship outcomes are directional: proposed `Copper` relative to existing `Copper Miners` is `broader`.
- Migration disposition is one-per-legacy-identity, but destinations and claim allocations are zero-to-many.
- Existing `SocialThemeAssociation` rows and their decisions are preserved. Global Social membership is a separate projection.
- Every content, Social, development, structural, compatibility, and migration writer acquires the shared taxonomy fence and rechecks authority before commit.
- The final publisher acquires the exclusive form of that fence, performs no provider call or worker wait, and aborts if its exact evidence manifest changed.
- Logical outbox event identity excludes authority epoch; targets reject older revisions and mirror-origin events never recurse.
- Evidence-channel eligibility does not itself create a technical, fundamental, or narrative metric observation.
- `security_id` means `stock_universe.id`; ADR-0003 remains unchanged for StockUniverse history.
- Economic mode is impossible until reader capability, frontend contract, compatibility, PostgreSQL concurrency, and zero-skip release gates all pass.

## Review Focus

1. Crash after creating a provisional processing snapshot: retry must yield one identity, one classification run, one logical mirror event, and no reader-visible partial state. Task 7 owns this test.
2. Source correction to empty followed by failed reprocessing: current reads must select the empty accepted run, while a later failed run leaves it unchanged and all three histories remain reproducible. Task 8 owns this test.
3. Legacy split plus Social many-to-one consolidation: claim allocation must preserve historical legacy interpretation and conflicting administrator decisions must remain blocked. Tasks 9 and 12 own these tests.
4. Late producer commit and out-of-order compatibility delivery: old-mode work must not cross cutover, and revision 1 after revision 2 must be a no-op. Tasks 3, 11, and 16 own these tests.
5. One post through legacy and Social with a later lens-only change: it must retain one source family, avoid a second extraction, consume no extra budget, and count as one independent source. Tasks 5 and 12 own this test.

## Delivery Slices

- **Slice A — Contract kernel:** Task 0 freezes the cross-component state machines and counterexamples before any schema is written.
- **Slice B — Immutable storage and fencing:** Tasks 1-3 add semantic snapshots, runtime history, serving generations, manifests, and the shared producer fence.
- **Slice C — Processing:** Tasks 4-8 add governed extraction, frozen admission, resolution, atomic processing-head advancement, assignments, and current-interpretation selection.
- **Slice D — Governance and measurements:** Tasks 9-10 add cardinality-safe restructuring, lifecycle, structured signals, and executable ranking views.
- **Slice E — Producer integration:** Tasks 11-13 add ordered compatibility delivery, Social reconciliation/budgeting, and narrative development authority.
- **Slice F — Read artifacts and migration:** Tasks 14-15 add APIs, versioned reader snapshots, migration, and the contrast benchmark.
- **Slice G — Publication and release:** Tasks 16-19 add the coordinator, cutover/rollback, schedules, authority-aware readers/UI, CI enforcement, and the operator runbook.

## File Map

### Domain and persistence

- `backend/app/domain/economic_taxonomy/contracts.py` — enums, immutable keys, results, and serving-generation contract.
- `backend/app/domain/economic_taxonomy/policy.py` — pure interpretation, mapping, relationship, lifecycle, and reconciliation rules.
- `backend/app/models/economic_taxonomy.py` — stable identities and version-owned semantic snapshot rows.
- `backend/app/models/economic_taxonomy_runtime.py` — source families, packets, runs, assignments, selections, observations, mappings, metrics, outbox, and serving artifacts.
- `backend/app/infra/db/repositories/economic_taxonomy_repo.py` — clone, validate, hash, and seal semantic snapshots.
- `backend/app/infra/db/repositories/economic_taxonomy_work_repo.py` — evidence/work/run idempotency and leases.
- `backend/app/infra/db/repositories/economic_taxonomy_publication_repo.py` — manifests, prepared generations, and atomic pointer changes.

### Services

- `backend/app/services/economic_taxonomy_fence.py` — shared producer and exclusive publisher lock protocol.
- `backend/app/services/economic_source_admission.py` — canonical source families, frozen packets, and lens eligibility.
- `backend/app/services/economic_exposure_extraction.py` — structured exposure extraction.
- `backend/app/services/economic_exposure_claim_review.py` — evidence and composition validation.
- `backend/app/services/economic_theme_candidate_retrieval.py` — bounded retrieval only.
- `backend/app/services/economic_theme_resolution.py` — semantic decisions with explicit direction.
- `backend/app/services/economic_theme_naming.py` — governed normalization and deterministic names.
- `backend/app/services/economic_taxonomy_processor.py` — immutable run persistence and one-shot processing-head advancement.
- `backend/app/services/economic_theme_observation_service.py` — assignment-derived observations, constituents, and signals.
- `backend/app/services/economic_taxonomy_interpretations.py` — accepted interpretation-set construction.
- `backend/app/services/economic_taxonomy_operations.py` — reviewed merge, split, redirect, allocation, and lifecycle operations.
- `backend/app/services/economic_theme_metrics_service.py` — versioned channel and ranking-view calculations.
- `backend/app/services/economic_taxonomy_runtime.py` — fenced legacy/economic routing and compatibility delivery.
- `backend/app/services/economic_taxonomy_migration.py` — migration dispositions, allocations, replay, and benchmark.
- `backend/app/services/economic_taxonomy_publication.py` — prepare, validate, publish, cutover, and rollback recovery.
- `backend/app/services/economic_theme_read_service.py` — generation-scoped reader facade.

### Migrations

- `backend/alembic/versions/20260921_0046_economic_taxonomy_core.py` — identity and sealed semantic snapshots.
- `backend/alembic/versions/20260921_0047_economic_taxonomy_interpretations.py` — evidence packets, runs, assignments, selections, observations, and signals.
- `backend/alembic/versions/20260921_0048_economic_taxonomy_publication.py` — authority, revision log, manifests, generations, and reader capabilities.
- `backend/alembic/versions/20260921_0049_economic_taxonomy_work.py` — leased work, candidates, proposals, and provider attempts.
- `backend/alembic/versions/20260921_0050_economic_taxonomy_mappings.py` — dispositions, destinations, allocations, redirects, and operations.
- `backend/alembic/versions/20260921_0051_economic_taxonomy_outbox.py` — ordered outbox, delivery attempts, and projection checkpoints.
- `backend/alembic/versions/20260921_0052_economic_taxonomy_social.py` — global Social projection and legacy bridge.
- `backend/alembic/versions/20260921_0053_economic_taxonomy_developments.py` — narrative development provenance and economic links.
- `backend/alembic/versions/20260921_0054_economic_taxonomy_reader_snapshots.py` — generation-scoped API/UI snapshot pointers.

### Product, tests, and operations

- `backend/app/api/v1/economic_themes.py` and `backend/app/api/v1/economic_taxonomy.py` — global reads and reviewed writes.
- `backend/app/tasks/economic_taxonomy_tasks.py` — bounded work, delivery, preparation, lifecycle, and metrics tasks.
- `frontend/src/api/economicThemes.js` — generation-aware API client.
- `frontend/src/features/themes/components/EconomicThemeDetailModal.jsx` — identity, evidence, signals, metrics, and constituents.
- `frontend/src/components/Themes/EconomicTaxonomyReview.jsx` — mapping, decision-conflict, and structural review.
- `backend/tests/fixtures/economic_taxonomy/contract_cases.json` — named counterexamples and expected outcomes.
- `backend/tests/required_economic_taxonomy_postgres.txt` — exact non-skippable PostgreSQL node IDs.
- `backend/scripts/run_required_economic_taxonomy_postgres.py` — collection/result gate that rejects missing, skipped, or xfailed nodes.
- `docs/runbooks/economic-taxonomy-cutover.md` — catch-up, barrier, publish, rollback, and recovery commands.

---

### Task 0: Freeze the cross-component contracts and counterexamples

**Files:**
- Create: `backend/app/domain/economic_taxonomy/__init__.py`
- Create: `backend/app/domain/economic_taxonomy/contracts.py`
- Create: `backend/app/domain/economic_taxonomy/policy.py`
- Create: `backend/tests/unit/test_economic_taxonomy_contracts.py`
- Create: `backend/tests/fixtures/economic_taxonomy/contract_cases.json`

**Interfaces:**
- Consumes: the approved design and existing authority names from the legacy Theme/Social domains.
- Produces: `ClassificationRunKey`, `InterpretationChoice`, `PublicationInputs`, `LogicalEventKey`, `MigrationDispositionResult`, `SocialDecisionResult`, `choose_interpretation()`, `relationship_from_proposed()`, `reconcile_social_decisions()`, `validate_split_allocations()`, and all shared enums.

- [ ] **Step 1: Write failing pure contract tests for every blocking counterexample**

```python
def test_successful_empty_supersedes_old_interpretation():
    old = run("old", status="completed", assignment_count=1)
    empty = run("empty", status="completed", assignment_count=0)
    assert choose_interpretation(previous=old, candidate=empty) == empty

def test_failed_reprocessing_retains_previous_interpretation():
    assert choose_interpretation(
        previous=run("accepted", status="completed"),
        candidate=run("failed", status="failed"),
    ).run_key == "accepted"

def test_split_requires_all_claims_to_be_allocated():
    result = validate_split_allocations(
        claim_ids={1, 2}, allocations={1: "petroleum", 2: "metals"}
    )
    assert result.complete is True

def test_social_accept_reject_conflict_blocks_membership():
    result = reconcile_social_decisions(("accepted", "rejected"))
    assert result.state == "conflict_review_required"
    assert result.live is False

def test_logical_event_identity_ignores_attempt_epoch():
    key = LogicalEventKey(
        source="post:1", revision=2, projection="legacy_theme:v1", target="legacy"
    )
    assert "authority_epoch" not in key.__dataclass_fields__
```

- [ ] **Step 2: Run the contract tests and confirm the package is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_contracts.py -q`

Expected: FAIL with `ModuleNotFoundError: app.domain.economic_taxonomy`.

- [ ] **Step 3: Implement the exact shared enums and immutable keys**

```python
class AuthorityMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    DUAL = "dual"
    ECONOMIC = "economic"

class EvidenceChannel(StrEnum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    NARRATIVE = "narrative"

class RankingView(StrEnum):
    TECHNICAL_ATTENTION = "technical_attention"
    FUNDAMENTAL_MOMENTUM = "fundamental_momentum"
    NARRATIVE_ATTENTION = "narrative_attention"
    EMERGING = "emerging"
    BROAD_CONFIRMATION = "broad_confirmation"

class ExposureSupport(StrEnum):
    DIRECT = "direct"
    INFERRED = "inferred"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"

class DevelopmentSupport(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNRESOLVED = "unresolved"
```

Add failure codes `invalid_schema`, `unsupported_composition`, `unknown_dimension`, `requires_naming_review`, `ambiguous_identity`, `stale_processing_head`, `stale_authority_epoch`, `budget_exhausted`, `conflict_review_required`, `compatibility_pending`, `reader_not_ready`, `manifest_changed`, `publication_validation_failed`, `rollback_recovery_required`, `provider_retryable`, and `provider_terminal`. Define the logical outbox key from source logical ID, ordered source revision, projection kind/version, and target representation; do not include epoch as a key field.

- [ ] **Step 4: Implement the pure selection, direction, mapping, and decision rules**

`choose_interpretation()` accepts only completed candidates; completed-empty is valid. `validate_split_allocations()` requires every current claim to have exactly one destination or reviewed exclusion. `reconcile_social_decisions()` returns conflict for mixed administrator accept/reject decisions. `relationship_from_proposed()` returns `broader` for proposed Copper against Copper Miners.

- [ ] **Step 5: Run the contract tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_contracts.py -q`

Expected: PASS with all named counterexamples collected.

- [ ] **Step 6: Commit the contract kernel**

```bash
git add backend/app/domain/economic_taxonomy backend/tests/unit/test_economic_taxonomy_contracts.py backend/tests/fixtures/economic_taxonomy/contract_cases.json
git commit -m "test: freeze economic taxonomy contracts"
```

### Task 1: Add stable identity and sealed semantic snapshots

**Files:**
- Create: `backend/app/models/economic_taxonomy.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/infra/db/repositories/economic_taxonomy_repo.py`
- Create: `backend/alembic/versions/20260921_0046_economic_taxonomy_core.py`
- Test: `backend/tests/unit/test_economic_taxonomy_snapshots.py`
- Test: `backend/tests/integration/test_economic_taxonomy_core_postgres.py`

**Interfaces:**
- Consumes: Task 0 enums.
- Produces: `TaxonomyVersion`, `EconomicTheme`, version-owned semantic rows, `EconomicTaxonomyRepository.clone_draft()`, `seal_draft()`, `load_snapshot()`, and `semantic_hash()`.

- [ ] **Step 1: Write failing snapshot, graph, and hash tests**

```python
def test_semantic_clone_hash_ignores_row_and_version_ids(repo, sealed_version):
    clone = repo.clone_draft(sealed_version.id, actor="test", reason="clone")
    assert repo.semantic_hash(clone) == repo.semantic_hash(sealed_version.id)

def test_sealed_snapshot_cannot_reopen(repo, sealed_version):
    with pytest.raises(ImmutableSnapshot):
        repo.set_status(sealed_version.id, "draft")

def test_specialization_cycle_is_rejected(repo, draft_with_a_to_b):
    repo.add_specialization(draft_with_a_to_b.id, narrower="b", broader="a")
    with pytest.raises(GraphInvariantViolation, match="specialization_cycle"):
        repo.seal_draft(draft_with_a_to_b.id)
```

- [ ] **Step 2: Run the tests and confirm missing models**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_snapshots.py -q`

Expected: FAIL on model import.

- [ ] **Step 3: Implement models, same-snapshot foreign keys, and immutable triggers**

Create stable UUID theme identity and complete version-owned revision, alias, facet, relationship, lifecycle, and policy rows. Use composite foreign keys containing `taxonomy_version_id` so references cannot cross snapshots. PostgreSQL triggers reject insert/update/delete against a sealed version and reject changing a row's version ID.

- [ ] **Step 4: Implement canonical hash and seal validation**

```python
SEMANTIC_HASH_FIELDS = {
    "theme": ("semantic_key", "display_name", "definition", "mechanism", "lifecycle"),
    "alias": ("theme_semantic_key", "normalized_alias"),
    "facet": ("theme_semantic_key", "dimension_key", "normalized_value"),
    "relationship": ("source_semantic_key", "target_semantic_key", "kind"),
}
```

Sort normalized payloads and exclude database IDs, version IDs, timestamps, actors, and comments. Seal while holding a version-scoped lock; validate no cycle and no active `distinct` contradiction with equivalence, redirects, or specialization.

- [ ] **Step 5: Run SQLite and PostgreSQL sealing races**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_snapshots.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_core_postgres.py -q`

Expected: concurrent mutation cannot pass sealing; cross-version references, row moves, cycles, and contradictory assertions fail.

- [ ] **Step 6: Commit sealed snapshots**

```bash
git add backend/app/models/economic_taxonomy.py backend/app/models/__init__.py backend/app/infra/db/repositories/economic_taxonomy_repo.py backend/alembic/versions/20260921_0046_economic_taxonomy_core.py backend/tests/unit/test_economic_taxonomy_snapshots.py backend/tests/integration/test_economic_taxonomy_core_postgres.py
git commit -m "feat: add sealed economic taxonomy snapshots"
```

### Task 2: Persist frozen evidence, classification history, and interpretations

**Files:**
- Create: `backend/app/models/economic_taxonomy_runtime.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260921_0047_economic_taxonomy_interpretations.py`
- Test: `backend/tests/unit/test_economic_taxonomy_interpretation_models.py`
- Test: `backend/tests/integration/test_economic_taxonomy_interpretation_migration.py`

**Interfaces:**
- Consumes: Task 0 contracts and Task 1 theme/version IDs.
- Produces: `SourceFamily`, `EvidencePacket`, `LensEligibilityRevision`, `ClassificationRun`, `ClaimAssignment`, `InterpretationSet`, `InterpretationSelection`, `ThemeObservation`, `ThemeConstituentExposure`, `ThemeSignalObservation`, `MetricsRevision`, and `ThemeMetric`.

- [ ] **Step 1: Write failing uniqueness and immutability tests**

```python
def test_policy_reclassification_can_store_two_runs(db, packet, taxonomy):
    first = classification_run(packet, taxonomy, resolver="v1")
    second = classification_run(packet, taxonomy, resolver="v2")
    db.add_all([first, second])
    db.flush()
    assert first.id != second.id

def test_observation_identity_comes_from_assignment(db, assignment):
    db.add(ThemeObservation(claim_assignment_id=assignment.id, observation_kind="primary"))
    db.flush()
```

- [ ] **Step 2: Run tests and confirm models are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretation_models.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement immutable evidence and run tables**

`EvidencePacket` stores source family, source lineage, evidence revision, packet hash, original/translated text references, admitted attachments, grounding snapshot, preparation version, and observed times. `ClassificationRun` is unique by packet, extraction/resolver/naming/derivation policies, and input processing taxonomy version. `ClaimAssignment` references its run and stable theme identity.

- [ ] **Step 4: Implement interpretation and derived-fact tables**

`InterpretationSelection` is unique by `(interpretation_set_id, source_lineage_key)` and references a completed run. A completed run may have zero assignments. Observation, constituent, and signal uniqueness includes immutable assignment identity; no uniqueness rule attempts to overwrite a prior policy's row. Add immutable `MetricsRevision` and child `ThemeMetric` rows so serving generations created by Task 3 can reference a defined metrics table before Task 10 supplies calculations.

- [ ] **Step 5: Run migration and model tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretation_models.py tests/integration/test_economic_taxonomy_interpretation_migration.py tests/unit/test_main_migrations.py -q`

Expected: PASS and Alembic head `20260921_0047`.

- [ ] **Step 6: Commit interpretation persistence**

```bash
git add backend/app/models/economic_taxonomy_runtime.py backend/app/models/__init__.py backend/alembic/versions/20260921_0047_economic_taxonomy_interpretations.py backend/tests/unit/test_economic_taxonomy_interpretation_models.py backend/tests/integration/test_economic_taxonomy_interpretation_migration.py
git commit -m "feat: persist taxonomy interpretation history"
```

### Task 3: Add serving generations, manifests, and the shared writer fence

**Files:**
- Modify: `backend/app/models/economic_taxonomy_runtime.py`
- Create: `backend/app/services/economic_taxonomy_fence.py`
- Create: `backend/app/infra/db/repositories/economic_taxonomy_publication_repo.py`
- Create: `backend/alembic/versions/20260921_0048_economic_taxonomy_publication.py`
- Test: `backend/tests/unit/test_economic_taxonomy_publication_models.py`
- Test: `backend/tests/integration/test_economic_taxonomy_fence_postgres.py`

**Interfaces:**
- Consumes: sealed versions and interpretation sets.
- Produces: `TaxonomyAuthority`, `TaxonomySourceRevisionLog`, `EvidenceManifest`, `ServingGeneration`, `ReaderSnapshotBundle`, `ReaderCapabilityManifest`, `producer_write()`, and `exclusive_publication()`.

- [ ] **Step 1: Write failing authority and fence tests**

```python
def test_processing_head_is_not_serving_pointer(authority):
    authority.processing_taxonomy_version_id = 22
    assert authority.serving_generation_id != 22

def test_old_writer_cannot_commit_after_exclusive_switch(pg_sessions, fence):
    old_writer, publisher = pg_sessions
    fence.start_shared(old_writer, expected_epoch=7)
    fence.start_exclusive(publisher)
    old_writer.commit()
    publisher.switch_epoch(8)
    assert fence.begin_shared(expected_epoch=7).error == "stale_authority_epoch"
```

- [ ] **Step 2: Run tests and confirm missing publication models**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_publication_models.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement authority, generation, capability, and exact-manifest rows**

Authority contains mode, processing version/revision, serving generation, epoch, write-fence state, and rollback state. A serving generation contains sealed taxonomy, interpretation set, metrics revision, evidence manifest, reader snapshot bundle, capability manifest, and immutable status. Create the immutable `ReaderSnapshotBundle` identity here; Task 14 fills its generation-scoped payload rows and adds the legacy UI pointer columns. Evidence manifests store sorted `(producer_kind, logical_source_key, committed_revision, content_hash)` tuples and their hash. This migration adds nullable `evidence_manifest_id` foreign keys to `interpretation_sets`, `metrics_revisions`, and `reader_snapshot_bundles`; preparation must fill them before a generation can enter `prepared`.

- [ ] **Step 4: Implement the lock-order helper**

```python
@contextmanager
def producer_write(session, *, expected_epoch: int, allowed_modes: set[AuthorityMode]):
    session.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": 78124017})
    authority = publication_repo.lock_authority(session)
    assert_write_allowed(authority, expected_epoch, allowed_modes)
    yield authority

@contextmanager
def exclusive_publication(session):
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 78124017})
    yield publication_repo.lock_authority(session)
```

SQLite substitutes a deterministic process lock for unit tests. Enforce lock order: fence, authority, producer registry/grouping, source/work/domain, outbox.

- [ ] **Step 5: Prove the late-lower-ID race is closed**

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_fence_postgres.py -q`

Expected: exclusive acquisition waits for existing shared writers, blocks new writers, and sees the committed revision from a transaction whose sequence ID was allocated earlier.

- [ ] **Step 6: Commit publication primitives**

```bash
git add backend/app/models/economic_taxonomy_runtime.py backend/app/services/economic_taxonomy_fence.py backend/app/infra/db/repositories/economic_taxonomy_publication_repo.py backend/alembic/versions/20260921_0048_economic_taxonomy_publication.py backend/tests/unit/test_economic_taxonomy_publication_models.py backend/tests/integration/test_economic_taxonomy_fence_postgres.py
git commit -m "feat: add taxonomy serving generations and writer fence"
```

### Task 4: Govern facet normalization, extraction results, and naming

**Files:**
- Create: `backend/app/services/economic_taxonomy_seed.py`
- Create: `backend/app/services/economic_theme_naming.py`
- Test: `backend/tests/unit/test_economic_taxonomy_seed.py`
- Test: `backend/tests/unit/test_economic_theme_naming.py`

**Interfaces:**
- Consumes: Task 0 candidates and Task 1 draft repository.
- Produces: `INITIAL_DIMENSIONS`, `normalize_facet()`, `seed_initial_dimensions()`, and `name_candidate()`.

- [ ] **Step 1: Write failing normalization and review tests**

```python
def test_ai_memory_uses_end_market_and_industry(snapshot):
    result = name_candidate(facets={
        "end_market": "AI", "industry": "Memory", "product": None,
    }, snapshot=snapshot)
    assert result.display_name == "AI Memory"

def test_unknown_dimension_preserves_candidate_and_opens_proposal(snapshot):
    result = name_candidate(facets={"moon_phase": "waxing"}, snapshot=snapshot)
    assert result.candidate is not None
    assert result.failure_code == "unknown_dimension"
    assert result.proposal.dimension_key == "moon_phase"
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_seed.py tests/unit/test_economic_theme_naming.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Seed the exact V1 dimensions and canonical values**

Seed `industry, technology, product, commodity, end_market, customer, supply_chain, geography, policy, regulation, macro, infrastructure`. Normalize AI demand to `end_market=artificial_intelligence`, memory economics to `industry=memory_semiconductors`, and HBM to `product=hbm`; reserve `technology=artificial_intelligence` for AI as the defining mechanism.

- [ ] **Step 4: Implement deterministic naming and guarded provider naming**

Provider naming receives only validated mechanism and approved normalized facets, cannot introduce a facet, and returns `requires_naming_review` when its name implies unsupported specificity.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_seed.py tests/unit/test_economic_theme_naming.py -q`

Expected: PASS.

```bash
git add backend/app/services/economic_taxonomy_seed.py backend/app/services/economic_theme_naming.py backend/tests/unit/test_economic_taxonomy_seed.py backend/tests/unit/test_economic_theme_naming.py
git commit -m "feat: govern economic taxonomy facets and names"
```

### Task 5: Admit frozen evidence and lease idempotent processing work

**Files:**
- Create: `backend/app/services/economic_source_admission.py`
- Create: `backend/app/infra/db/repositories/economic_taxonomy_work_repo.py`
- Modify: `backend/app/models/economic_taxonomy_runtime.py`
- Create: `backend/alembic/versions/20260921_0049_economic_taxonomy_work.py`
- Test: `backend/tests/unit/test_economic_source_admission.py`
- Test: `backend/tests/unit/test_economic_taxonomy_work_repo.py`
- Test: `backend/tests/integration/test_economic_taxonomy_work_postgres.py`

**Interfaces:**
- Consumes: source content, attachments, translation, grounding, provenance routes, Task 3 fence.
- Produces: `admit_content()`, `admit_social_work()`, `revise_lens_eligibility()`, `enqueue_run()`, `claim_next()`, `retry()`, and `complete()`.

- [ ] **Step 1: Write failing source-family, packet, and eligibility tests**

```python
def test_same_provider_post_from_legacy_and_social_shares_family(admission, post):
    legacy = admission.admit_content(post.as_content_item())
    social = admission.admit_social_work(post.as_saved_work())
    assert legacy.source_family_id == social.source_family_id

def test_adding_lens_does_not_create_packet_or_work(admission, admitted):
    revised = admission.revise_lens_eligibility(admitted.packet_id, add="fundamental")
    assert revised.packet_id == admitted.packet_id
    assert revised.enqueued_run_id is None
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_source_admission.py tests/unit/test_economic_taxonomy_work_repo.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement family resolution and packet hashing**

Packet hashes include selected original/translated text, translation version, admitted attachments, grounding snapshot, preparation version, and source metadata. They exclude lens eligibility. Canonical provider post ID wins over route-specific database IDs for the source-family key. The same family may contain multiple packets when admitted text, translation, attachments, grounding, or preparation changes; those packets remain independently reproducible while current selection is still per source lineage.

- [ ] **Step 4: Implement work identity and leases**

Work identity is the `ClassificationRunKey` from Task 0. Persist durable candidate and dimension/naming proposal rows beside work. Claim with `FOR UPDATE SKIP LOCKED`, UUID lease token, five-minute expiry, input processing-head revision, and observed authority epoch. Complete inside `producer_write()`; stale head returns `stale_processing_head`, stale authority returns `stale_authority_epoch`, and neither writes assignments.

- [ ] **Step 5: Run reproducibility and concurrency tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_source_admission.py tests/unit/test_economic_taxonomy_work_repo.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_work_postgres.py -q`

Expected: one claimant per row, old packets retain frozen translation/grounding, and lens-only changes do not enqueue extraction.

- [ ] **Step 6: Commit admission and work**

```bash
git add backend/app/services/economic_source_admission.py backend/app/infra/db/repositories/economic_taxonomy_work_repo.py backend/app/models/economic_taxonomy_runtime.py backend/alembic/versions/20260921_0049_economic_taxonomy_work.py backend/tests/unit/test_economic_source_admission.py backend/tests/unit/test_economic_taxonomy_work_repo.py backend/tests/integration/test_economic_taxonomy_work_postgres.py
git commit -m "feat: admit frozen taxonomy evidence"
```

### Task 6: Extract and review structured exposure candidates

**Files:**
- Create: `backend/app/services/economic_exposure_extraction.py`
- Create: `backend/app/services/economic_exposure_claim_review.py`
- Test: `backend/tests/unit/test_economic_exposure_extraction.py`
- Test: `backend/tests/unit/test_economic_exposure_claim_review.py`

**Interfaces:**
- Consumes: frozen `EvidencePacket`, approved facet catalog, optional provider reservation.
- Produces: `extract_exposures(packet) -> ExtractionResult` and `review_claims(packet, result) -> ClaimReviewResult`.

- [ ] **Step 1: Write failing composition, empty, unknown-dimension, and support-state tests**

```python
def test_ai_and_memory_cooccurrence_without_link_is_not_ai_memory(extractor):
    result = extractor.extract(packet("AI spending rose. Memory pricing rose independently."))
    assert "AI Memory" not in result.accepted_names

def test_unknown_dimension_is_review_required_not_parse_failure(extractor):
    result = extractor.extract(packet_with_dimension("deployment_model", "edge"))
    assert result.status == "review_required"
    assert result.candidates[0].raw_facets["deployment_model"] == "edge"

def test_successful_empty_is_distinct_from_failure(extractor):
    assert extractor.extract(packet("No investable exposure.")).status == "successful_empty"
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement schema-constrained extraction**

Return `accepted_candidates|successful_empty|review_required|failed`. Preserve raw candidates for unknown dimensions and naming review. Separate exposure support from development support and require quoted evidence spans for compound relationships.

- [ ] **Step 4: Implement claim review outside persistence locks**

Reject technical setups as themes, enforce narrowest supported specificity, validate security grounding, and retain provider response hashes. Provider quota/timeout is retryable; schema/composition failure is durable review or terminal according to Task 0 codes.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py -q`

Expected: PASS.

```bash
git add backend/app/services/economic_exposure_extraction.py backend/app/services/economic_exposure_claim_review.py backend/tests/unit/test_economic_exposure_extraction.py backend/tests/unit/test_economic_exposure_claim_review.py
git commit -m "feat: extract reviewed economic exposures"
```

### Task 7: Resolve identities and advance the processing head atomically

**Files:**
- Create: `backend/app/services/economic_theme_candidate_retrieval.py`
- Create: `backend/app/services/economic_theme_resolution.py`
- Create: `backend/app/services/economic_taxonomy_processor.py`
- Test: `backend/tests/unit/test_economic_theme_candidate_retrieval.py`
- Test: `backend/tests/unit/test_economic_theme_resolution.py`
- Test: `backend/tests/unit/test_economic_taxonomy_processor.py`
- Test: `backend/tests/integration/test_economic_processing_publication_postgres.py`

**Interfaces:**
- Consumes: reviewed candidates, processing snapshot, work lease, naming service, fence.
- Produces: `retrieve_candidates()`, `resolve_candidate()`, and `EconomicTaxonomyProcessor.process(work_id, lease_token)`.

- [ ] **Step 1: Write failing direction and crash-idempotency tests**

```python
def test_proposed_copper_is_broader_than_existing_copper_miners(resolver):
    assert resolver.resolve(proposed=copper(), existing=copper_miners()).outcome == "broader"

def test_retry_after_processing_head_crash_reuses_identity(processor, fault, work):
    fault.raise_after("processing_head_commit")
    with pytest.raises(InjectedCrash):
        processor.process(work.id, work.lease_token)
    result = processor.process(work.id, work.lease_token)
    assert result.created_identity_count == 0
    assert result.classification_run_count == 1
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_candidate_retrieval.py tests/unit/test_economic_theme_resolution.py tests/unit/test_economic_taxonomy_processor.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement bounded retrieval and semantic resolution**

Retrieval returns at most 20 candidates from aliases, normalized facets, lexical search, embeddings, constituents, and graph neighbors. Resolution expresses proposed relative to existing and validates that provider output is one allowed outcome with referenced candidate IDs.

- [ ] **Step 4: Implement one processing-head transaction per source run**

Perform provider calls before the write transaction. Under `producer_write()`, lock authority/work, verify processing revision, clone one draft, apply every new provisional identity/edge from the run, seal once, persist the completed classification run and all assignments, append one source revision, update processing head/revision, and complete work. An empty run advances no taxonomy snapshot.

- [ ] **Step 5: Implement stale-head re-resolution**

If the processing head changed, release the transaction, retrieve/resolve again against the new head, and retry persistence with the same run idempotency key. Never loop provider work under a database lock.

- [ ] **Step 6: Run unit and PostgreSQL crash/race tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_candidate_retrieval.py tests/unit/test_economic_theme_resolution.py tests/unit/test_economic_taxonomy_processor.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_processing_publication_postgres.py -q`

Expected: several themes from one source create one sealed processing version; retry creates no duplicate identity, run, assignment, or logical mirror event.

- [ ] **Step 7: Commit processing-head orchestration**

```bash
git add backend/app/services/economic_theme_candidate_retrieval.py backend/app/services/economic_theme_resolution.py backend/app/services/economic_taxonomy_processor.py backend/tests/unit/test_economic_theme_candidate_retrieval.py backend/tests/unit/test_economic_theme_resolution.py backend/tests/unit/test_economic_taxonomy_processor.py backend/tests/integration/test_economic_processing_publication_postgres.py
git commit -m "feat: resolve themes into the processing taxonomy"
```

### Task 8: Build accepted interpretations and assignment-derived facts

**Files:**
- Create: `backend/app/services/economic_taxonomy_interpretations.py`
- Create: `backend/app/services/economic_theme_observation_service.py`
- Test: `backend/tests/unit/test_economic_taxonomy_interpretations.py`
- Test: `backend/tests/unit/test_economic_theme_observations.py`

**Interfaces:**
- Consumes: evidence manifest, completed runs, assignments, reviewed constituent decisions.
- Produces: `build_interpretation_set()`, `materialize_assignment_facts()`, and generation-scoped observation/constituent/signal queries.

- [ ] **Step 1: Write failing correction and historical-read tests**

```python
def test_corrected_to_empty_removes_current_facts(builder, old_run, empty_run):
    first = builder.build({old_run.source_lineage: old_run})
    second = builder.build({empty_run.source_lineage: empty_run})
    assert builder.current_observations(second.id) == []
    assert len(builder.current_observations(first.id)) == 1

def test_failed_run_cannot_replace_selected_run(builder, accepted, failed):
    with pytest.raises(InvalidInterpretation, match="run_not_completed"):
        builder.build({accepted.source_lineage: failed})
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretations.py tests/unit/test_economic_theme_observations.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement immutable selection and fact materialization**

Select zero or one completed run per source lineage in the manifest. The default policy chooses the newest admissible completed evidence revision and policy run; a reviewed override may choose an older completed run. Failed, partial, and review-only runs are ineligible. Materialize primary observations, one-hop derived observations sharing root/source family, constituent exposures, and structured signals from assignments. Current queries always join the requested interpretation set.

- [ ] **Step 4: Pin independence and signal persistence**

One source family counts once per theme/channel/day even when admitted through two routes. Derived facts never increment direct/root counts. Store signal type, normalized payload, security, detected/effective times, source family, assignment, and detector policy.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretations.py tests/unit/test_economic_theme_observations.py -q`

Expected: PASS for old/new reproducibility, successful empty correction, failed reprocessing, and source-family deduplication.

```bash
git add backend/app/services/economic_taxonomy_interpretations.py backend/app/services/economic_theme_observation_service.py backend/tests/unit/test_economic_taxonomy_interpretations.py backend/tests/unit/test_economic_theme_observations.py
git commit -m "feat: select taxonomy interpretations"
```

### Task 9: Add cardinality-safe mappings and reviewed operations

**Files:**
- Modify: `backend/app/models/economic_taxonomy.py`
- Modify: `backend/app/models/economic_taxonomy_runtime.py`
- Create: `backend/app/services/economic_taxonomy_operations.py`
- Create: `backend/alembic/versions/20260921_0050_economic_taxonomy_mappings.py`
- Test: `backend/tests/unit/test_economic_taxonomy_mappings.py`
- Test: `backend/tests/unit/test_economic_taxonomy_operations.py`

**Interfaces:**
- Consumes: draft repository, claim assignments, reviewer identity/reason.
- Produces: `LegacyIdentityDisposition`, `LegacyDestinationMapping`, `LegacyClaimAllocation`, `EconomicThemeRedirect`, `preview_operation()`, and `apply_operation()`.

- [ ] **Step 1: Write failing split, merge, exclusion, and version-copy tests**

```python
def test_refining_split_allocates_each_claim(service, refining):
    result = service.split(refining.id, allocations={
        refining.petroleum_claim: "petroleum-refining",
        refining.metals_claim: "metals-refining",
    })
    assert result.destination_count == 2
    assert result.unallocated_claim_ids == ()

def test_not_a_theme_has_no_destination(service, legacy_signal_cluster):
    result = service.exclude(legacy_signal_cluster.id, disposition="not_a_theme")
    assert result.destinations == ()
```

- [ ] **Step 2: Run tests and confirm models/services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_mappings.py tests/unit/test_economic_taxonomy_operations.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement version-owned mapping rows**

One disposition per `(taxonomy_version_id, legacy_theme_cluster_id)`; zero-to-many destinations; claim/source allocation to a destination or reviewed exclusion; version-owned economic redirects for merges. Clone all four mapping kinds with the semantic snapshot. Extend Task 1's immutability triggers, canonical semantic hash, same-snapshot validation, and contradictory-graph checks to these rows.

- [ ] **Step 4: Implement reviewed preview/apply**

Preview returns before/after semantic hash, affected identities, assignments, mappings, compatibility events, and validation errors. Apply requires unchanged preview hash, reviewer, and reason; under `producer_write()` it creates and seals a new processing version, appends a structural source-revision-log row, and never changes serving authority directly.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_mappings.py tests/unit/test_economic_taxonomy_operations.py -q`

Expected: PASS; historical legacy interpretation remains reproducible after split and later version publication.

```bash
git add backend/app/models/economic_taxonomy.py backend/app/models/economic_taxonomy_runtime.py backend/app/services/economic_taxonomy_operations.py backend/alembic/versions/20260921_0050_economic_taxonomy_mappings.py backend/tests/unit/test_economic_taxonomy_mappings.py backend/tests/unit/test_economic_taxonomy_operations.py
git commit -m "feat: add reviewed taxonomy mappings and operations"
```

### Task 10: Implement lifecycle proposals and executable ranking views

**Files:**
- Create: `backend/app/services/economic_theme_lifecycle_service.py`
- Create: `backend/app/services/economic_theme_metrics_service.py`
- Test: `backend/tests/unit/test_economic_theme_lifecycle.py`
- Test: `backend/tests/unit/test_economic_theme_metrics.py`

**Interfaces:**
- Consumes: sealed processing snapshot, interpretation set, selected observations/signals, as-of time.
- Produces: `propose_lifecycle_snapshot()` and `calculate_metrics() -> MetricsRevision`.

- [ ] **Step 1: Write failing availability and formula tests**

```python
def test_eligibility_without_support_is_unavailable(metrics):
    result = metrics.calculate(theme=eligible_but_unobserved(), as_of=NOW)
    assert result.technical_attention.availability == "unavailable"

def test_broad_confirmation_requires_two_channels(metrics):
    result = metrics.calculate(theme=technical_only_theme(), as_of=NOW)
    assert result.broad_confirmation.availability == "unavailable"
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement exact V1 calculations**

Technical uses direct roots over 30 days with seven-day half-life plus accepted signals with five-day half-life. Fundamental uses 90 days/30-day half-life. Narrative uses 14 days/three-day half-life. Emerging uses `families_7d - families_prior_21d / 3` and requires two families on two dates. Broad confirmation is the arithmetic mean of available channel percentiles and requires two channels and two source families. Ties share a percentile; missing is `unavailable`, never imputed zero.

- [ ] **Step 4: Implement lifecycle as processing proposals**

Apply the exact thresholds from design section 10 using distinct source families. Under `producer_write()`, create a sealed processing snapshot through Task 9 operation machinery and append a lifecycle source-revision-log row; do not update serving pointers.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py -q`

Expected: PASS with deterministic as-of results and policy/version provenance.

```bash
git add backend/app/services/economic_theme_lifecycle_service.py backend/app/services/economic_theme_metrics_service.py backend/tests/unit/test_economic_theme_lifecycle.py backend/tests/unit/test_economic_theme_metrics.py
git commit -m "feat: calculate economic taxonomy lifecycle and metrics"
```

### Task 11: Add ordered outbox delivery and fence legacy producers

**Files:**
- Modify: `backend/app/models/economic_taxonomy_runtime.py`
- Create: `backend/app/services/economic_taxonomy_runtime.py`
- Modify: `backend/app/services/theme_discovery_service.py`
- Modify: `backend/app/tasks/theme_discovery_tasks.py`
- Create: `backend/alembic/versions/20260921_0051_economic_taxonomy_outbox.py`
- Test: `backend/tests/unit/test_economic_taxonomy_outbox.py`
- Test: `backend/tests/unit/test_economic_taxonomy_legacy_adapter.py`
- Test: `backend/tests/integration/test_economic_taxonomy_outbox_postgres.py`

**Interfaces:**
- Consumes: Task 3 fence, logical event key, legacy discovery writes.
- Produces: `emit_projection_event()`, `claim_deliveries()`, `apply_delivery()`, and `ProjectionCheckpoint`.

- [ ] **Step 1: Write failing epoch-retry, ordering, recursion, and writer-race tests**

```python
def test_retry_after_epoch_change_reuses_logical_event(outbox):
    first = outbox.emit(source="post:1", revision=2, epoch=10)
    retry = outbox.emit(source="post:1", revision=2, epoch=11)
    assert retry.id == first.id

def test_older_delivery_cannot_restore_state(target):
    target.apply(revision=2, payload={"name": "new"})
    target.apply(revision=1, payload={"name": "old"})
    assert target.name == "new"
```

- [ ] **Step 2: Run tests and confirm outbox service is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_outbox.py tests/unit/test_economic_taxonomy_legacy_adapter.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement logical events, attempts, and target checkpoints**

Unique logical key excludes epoch. Each attempt records claimed epoch, lease, outcome, and error. Target compare-and-set applies only revisions newer than its checkpoint. Payloads contain `origin_representation`; applying a mirror suppresses reverse event generation.

- [ ] **Step 4: Route legacy producers through the shared fence**

Provider work remains outside transactions. Every legacy theme mutation starts with `producer_write()`, locks existing registry/grouping rows only after authority, writes its source revision and domain change atomically, and emits the appropriate shadow/dual compatibility event.

- [ ] **Step 5: Run PostgreSQL ordering and cutover-race tests**

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_outbox_postgres.py -q`

Expected: out-of-order delivery is harmless, recursive emission is absent, and an old-mode writer cannot commit after epoch switch.

- [ ] **Step 6: Commit fenced compatibility delivery**

```bash
git add backend/app/models/economic_taxonomy_runtime.py backend/app/services/economic_taxonomy_runtime.py backend/app/services/theme_discovery_service.py backend/app/tasks/theme_discovery_tasks.py backend/alembic/versions/20260921_0051_economic_taxonomy_outbox.py backend/tests/unit/test_economic_taxonomy_outbox.py backend/tests/unit/test_economic_taxonomy_legacy_adapter.py backend/tests/integration/test_economic_taxonomy_outbox_postgres.py
git commit -m "feat: fence and order taxonomy compatibility writes"
```

### Task 12: Integrate Social admission, budgeting, and decision reconciliation

**Files:**
- Modify: `backend/app/infra/db/models/social_analysis.py`
- Modify: `backend/app/services/social_theme_projection_service.py`
- Modify: `backend/app/services/social_llm_budget_service.py`
- Modify: `backend/app/services/social_theme_market_service.py`
- Create: `backend/alembic/versions/20260921_0052_economic_taxonomy_social.py`
- Test: `backend/tests/unit/test_economic_taxonomy_social_adapter.py`
- Test: `backend/tests/integration/test_economic_taxonomy_social_postgres.py`
- Test: `backend/tests/unit/services/test_social_llm_budget.py`

**Interfaces:**
- Consumes: existing Social work/association/decision rows, Task 5 admission, Task 11 outbox, Social budget reservation API.
- Produces: `EconomicSocialAssociation`, `EconomicSocialAssociationSource`, live-admission/reconciliation service, and pending legacy mirror state.

- [ ] **Step 1: Write failing consolidation, conflict, admission, and budget tests**

```python
def test_two_legacy_associations_can_bridge_one_global_membership(adapter):
    result = adapter.project(legacy_associations=[accepted_a(), accepted_b()])
    assert result.global_association_count == 1
    assert result.bridge_count == 2

def test_admin_conflict_is_not_live(adapter):
    result = adapter.project(legacy_associations=[accepted_a(), rejected_b()])
    assert result.state == "conflict_review_required"
    assert result.live is False

def test_exhausted_budget_makes_no_provider_call(adapter, exhausted_budget, provider):
    adapter.process(saved_social_work())
    provider.assert_not_called()
```

- [ ] **Step 2: Run tests and confirm global projection is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_social_adapter.py tests/unit/services/test_social_llm_budget.py -q`

Expected: FAIL on global projection import.

- [ ] **Step 3: Implement separate global association and many-to-many bridge**

Do not add economic uniqueness to `SocialThemeAssociation`. Global association is unique by economic theme and `stock_universe.id`; bridge every contributing legacy association/evidence work row. Mixed administrator accept/reject becomes `conflict_review_required` and remains out of accepted membership.

- [ ] **Step 4: Implement live admission and compatibility mirroring**

Only published, succeeded, policy-admitted saved work contributes narrative evidence. Proposed, rejected, unpublished, and exploratory work stays review-only. New global membership begins `pending_legacy_mirror`; an ordered event creates/reuses the legacy compatibility cluster and association, then acknowledgement permits live acceptance.

- [ ] **Step 5: Reserve/reconcile every additional provider call outside projection locks**

Use stable Social LLM attempt keys containing evidence packet and operation kind. Reserve before the call, reconcile success/failure afterward, and only then enter the short fenced projection transaction.

- [ ] **Step 6: Run unit and PostgreSQL Social tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_social_adapter.py tests/unit/services/test_social_llm_budget.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_social_postgres.py tests/integration/test_social_theme_projection.py -q`

Expected: historical rows/decisions remain unchanged; identical decisions consolidate; conflicts and unpublished work remain non-live.

- [ ] **Step 7: Commit Social integration**

```bash
git add backend/app/infra/db/models/social_analysis.py backend/app/services/social_theme_projection_service.py backend/app/services/social_llm_budget_service.py backend/app/services/social_theme_market_service.py backend/alembic/versions/20260921_0052_economic_taxonomy_social.py backend/tests/unit/test_economic_taxonomy_social_adapter.py backend/tests/integration/test_economic_taxonomy_social_postgres.py backend/tests/unit/services/test_social_llm_budget.py
git commit -m "feat: integrate Social with economic taxonomy"
```

### Task 13: Extend development authority with narrative provenance

**Files:**
- Modify: `backend/app/models/theme_intelligence.py`
- Modify: `backend/app/services/theme_development_facts.py`
- Modify: `backend/app/services/theme_development_service.py`
- Modify: `backend/app/services/theme_development_worker.py`
- Create: `backend/alembic/versions/20260921_0053_economic_taxonomy_developments.py`
- Test: `backend/tests/unit/test_economic_taxonomy_developments.py`
- Test: `backend/tests/unit/test_theme_development.py`

**Interfaces:**
- Consumes: existing `record_developments()`, canonical source-family keys, Economic Theme assignments, writer fence.
- Produces: narrative `analysis_channel`, economic development links, and one event identity across dual routes.

- [ ] **Step 1: Write failing Social-native and deduplication tests**

```python
def test_social_native_development_has_narrative_provenance(service):
    row = service.record(source=social_packet(), channel="narrative", themes=[theme_id])
    assert row.analysis_channel == "narrative"
    assert row.economic_theme_links[0].economic_theme_id == theme_id

def test_dual_route_creates_one_event(service, same_post_legacy_and_social):
    rows = service.record_both_routes(same_post_legacy_and_social)
    assert len({row.event_id for row in rows}) == 1
```

- [ ] **Step 2: Run tests and confirm narrative is rejected**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_developments.py tests/unit/test_theme_development.py -q`

Expected: FAIL because existing `record_developments()` accepts only technical/fundamental.

- [ ] **Step 3: Migrate and extend the existing event authority**

Move channel provenance to development observations with `analysis_channel=technical|fundamental|narrative`, backfilled from the existing pipeline value. Make `ThemeDevelopmentEvent.event_key` canonical across channels: migrate duplicate `(pipeline, event_key)` events onto one event, repoint observations/links, then enforce unique `event_key`. Add Economic Theme link rows; compatibility delivery creates legacy links without creating a second event.

- [ ] **Step 4: Fence development writes and use separate support states**

Normalize provider work before the transaction, then persist event/observations/links and source revision under `producer_write()`. Accept development support `present|absent|unresolved`; never pass `absent` as exposure support.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_developments.py tests/unit/test_theme_development.py tests/unit/test_theme_developments.py -q`

Expected: PASS; Social-native development appears once and legacy technical/fundamental behavior is unchanged.

```bash
git add backend/app/models/theme_intelligence.py backend/app/services/theme_development_facts.py backend/app/services/theme_development_service.py backend/app/services/theme_development_worker.py backend/alembic/versions/20260921_0053_economic_taxonomy_developments.py backend/tests/unit/test_economic_taxonomy_developments.py backend/tests/unit/test_theme_development.py
git commit -m "feat: add narrative economic theme developments"
```

### Task 14: Expose generation-scoped APIs and reader snapshots

**Files:**
- Create: `backend/app/api/v1/economic_themes.py`
- Create: `backend/app/api/v1/economic_taxonomy.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/services/ui_snapshot_service.py`
- Create: `backend/alembic/versions/20260921_0054_economic_taxonomy_reader_snapshots.py`
- Test: `backend/tests/unit/test_economic_theme_api.py`
- Test: `backend/tests/unit/test_economic_taxonomy_api.py`
- Test: `backend/tests/unit/test_economic_theme_ui_snapshot.py`

**Interfaces:**
- Consumes: generation, interpretation, metrics, Social reconciliation, operations.
- Produces: read endpoints, review endpoints, and `build_snapshot_bundle(generation_inputs)`.

- [ ] **Step 1: Write failing coherence and historical-read tests**

```python
def test_snapshot_bundle_uses_one_generation(client, prepared_generation):
    payload = client.get("/api/v1/economic-themes").json()
    assert payload["taxonomy_version_id"] == payload["generation"]["taxonomy_version_id"]
    assert payload["evidence_manifest_hash"] == payload["generation"]["evidence_manifest_hash"]

def test_historical_generation_is_reproducible(client, old_generation):
    response = client.get(f"/api/v1/economic-themes?generation_id={old_generation.id}")
    assert response.json()["generation_id"] == old_generation.id
```

- [ ] **Step 2: Run tests and confirm routers are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_api.py tests/unit/test_economic_taxonomy_api.py tests/unit/test_economic_theme_ui_snapshot.py -q`

Expected: FAIL on import or 404.

- [ ] **Step 3: Implement generation-scoped schemas and read endpoints**

Return generation, taxonomy version, interpretation set, manifest hash, metrics revision, availability states, direct/derived counts, signals, constituents, developments, relationships, mappings, and reconciliation state. Default reads resolve one serving generation at request start; explicit historical reads require a generation ID.

- [ ] **Step 4: Build immutable snapshot bundles without switching pointers**

`build_snapshot_bundle()` takes explicit taxonomy/interpretation/manifest/metrics inputs and writes immutable API/UI payloads. It validates every referenced theme/facet exists in the same snapshot. Pointer switching is reserved for Task 16.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_api.py tests/unit/test_economic_taxonomy_api.py tests/unit/test_economic_theme_ui_snapshot.py tests/unit/test_ui_snapshot_service.py -q`

Expected: PASS.

```bash
git add backend/app/api/v1/economic_themes.py backend/app/api/v1/economic_taxonomy.py backend/app/api/v1/router.py backend/app/services/ui_snapshot_service.py backend/alembic/versions/20260921_0054_economic_taxonomy_reader_snapshots.py backend/tests/unit/test_economic_theme_api.py backend/tests/unit/test_economic_taxonomy_api.py backend/tests/unit/test_economic_theme_ui_snapshot.py
git commit -m "feat: expose generation-scoped economic themes"
```

### Task 15: Build reviewed migration, exact replay inputs, and contrast benchmark

**Files:**
- Create: `backend/app/services/economic_taxonomy_migration.py`
- Create: `backend/scripts/run_economic_taxonomy_benchmark.py`
- Expand: `backend/tests/fixtures/economic_taxonomy/contract_cases.json`
- Test: `backend/tests/unit/test_economic_taxonomy_migration.py`
- Test: `backend/tests/unit/test_economic_taxonomy_benchmark.py`

**Interfaces:**
- Consumes: legacy themes/mentions/associations/developments, mapping operations, source revision log.
- Produces: `build_migration()`, `review_disposition()`, `replay_manifest()`, and benchmark report bound to taxonomy and policy hashes.

- [ ] **Step 1: Write failing coverage and split-allocation tests**

```python
def test_complete_coverage_means_disposition_plus_split_allocations(migration, refining):
    run = migration.build(refining.dataset)
    assert run.coverage_complete is False
    migration.review_split(run.id, refining.id, refining.allocations)
    assert migration.get(run.id).coverage_complete is True

def test_max_source_id_is_not_used_as_replay_barrier(migration):
    manifest = migration.replay_manifest()
    assert manifest.entries == tuple(sorted(committed_revision_tuples()))
```

- [ ] **Step 2: Run tests and confirm migration service is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_migration.py tests/unit/test_economic_taxonomy_benchmark.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement resumable migration and reviewed coverage**

Persist run inputs, source hashes, taxonomy/policy hashes, dispositions, destinations, allocations, exclusions, reviewer, and reason. Many-to-one merges reuse one global identity; one-to-many splits stay incomplete until every current claim is allocated. Backfill and replay commits use `producer_write()` and append migration revision-log rows so the final manifest covers migration state.

- [ ] **Step 4: Implement exact manifest replay and benchmark fixtures**

Replay sorted committed revision-log tuples, not sequence maxima. Include AI/Memory co-occurrence, AI Memory/HBM specificity, AI Security mechanism contrast, Copper direction, Refining split, Social consolidation/conflict, successful empty correction, and duplicate-route independence.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_migration.py tests/unit/test_economic_taxonomy_benchmark.py -q`

Expected: PASS and benchmark report includes fixture version, taxonomy hash, policy bundle, and per-case outcome.

```bash
git add backend/app/services/economic_taxonomy_migration.py backend/scripts/run_economic_taxonomy_benchmark.py backend/tests/fixtures/economic_taxonomy/contract_cases.json backend/tests/unit/test_economic_taxonomy_migration.py backend/tests/unit/test_economic_taxonomy_benchmark.py
git commit -m "feat: migrate and benchmark economic taxonomy"
```

### Task 16: Implement the publication coordinator, cutover, and rollback recovery

**Files:**
- Create: `backend/app/services/economic_taxonomy_publication.py`
- Create: `backend/scripts/publish_economic_taxonomy.py`
- Test: `backend/tests/unit/test_economic_taxonomy_publication.py`
- Test: `backend/tests/integration/test_economic_taxonomy_publication_postgres.py`

**Interfaces:**
- Consumes: processing head, interpretation builder, metrics, snapshot builder, manifest, capability, compatibility checkpoints, exclusive fence.
- Produces: `prepare_generation()`, `publish_generation()`, `prepare_cutover()`, `publish_cutover()`, and `rollback()`.

- [ ] **Step 1: Write failing preparation, manifest-change, and rollback tests**

```python
def test_prepare_builds_all_artifacts_from_one_manifest(coordinator):
    generation = coordinator.prepare_generation()
    assert generation.interpretation_set.evidence_manifest_id == generation.evidence_manifest_id
    assert generation.metrics.evidence_manifest_id == generation.evidence_manifest_id
    assert generation.snapshot_bundle.evidence_manifest_id == generation.evidence_manifest_id

def test_manifest_change_aborts_without_switch(coordinator, new_revision):
    prepared = coordinator.prepare_generation()
    new_revision.commit()
    with pytest.raises(ManifestChanged):
        coordinator.publish_generation(prepared.id)
    assert coordinator.authority().serving_generation_id != prepared.id
```

- [ ] **Step 2: Run tests and confirm coordinator is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_publication.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement preparation outside the exclusive lock**

Choose a sealed processing version; build exact manifest, interpretation set, metrics, snapshots, compatibility validation, benchmark validation, and reader capability; persist `prepared`. No authority pointer changes here.

- [ ] **Step 4: Implement the short final barrier**

Under `exclusive_publication()`, reread the committed manifest after shared writers drain. Verify manifest hash, processing revision, compatibility checkpoints, outbox requirements, capability, and snapshot hashes. If any differ, roll back immediately. Otherwise switch serving generation and all UI/API pointers, optionally mode, increment epoch, and mark published in one transaction.

- [ ] **Step 5: Implement catch-up and rollback recovery outside the barrier**

Replay and drain outside publication. If compatibility is unhealthy, set durable `rollback_recovery`, restrict authoritative writes, rebuild ordered legacy projections from the current interpretation, verify checkpoints, prepare a legacy generation, then use the normal final barrier.

- [ ] **Step 6: Run PostgreSQL race matrix**

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_publication_postgres.py -q`

Expected: existing source change, late lower-ID commit, blocked outbox, evidence after snapshot build, old writer race, injected crash, and unhealthy rollback all end with one coherent old or new generation and no deadlock.

- [ ] **Step 7: Run unit tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_publication.py -q`

Expected: PASS.

```bash
git add backend/app/services/economic_taxonomy_publication.py backend/scripts/publish_economic_taxonomy.py backend/tests/unit/test_economic_taxonomy_publication.py backend/tests/integration/test_economic_taxonomy_publication_postgres.py
git commit -m "feat: coordinate economic taxonomy publication"
```

### Task 17: Schedule bounded processing, delivery, preparation, lifecycle, and metrics

**Files:**
- Create: `backend/app/tasks/economic_taxonomy_tasks.py`
- Modify: `backend/app/celery_app.py`
- Test: `backend/tests/unit/test_economic_taxonomy_tasks.py`
- Test: `backend/tests/unit/test_economic_taxonomy_celery_contract.py`

**Interfaces:**
- Consumes: Tasks 5-16 services.
- Produces: Celery tasks `discover_economic_taxonomy_work`, `process_economic_taxonomy_work`, `deliver_taxonomy_outbox`, `prepare_taxonomy_generation`, `apply_economic_theme_lifecycle`, and `calculate_economic_theme_metrics`.

- [ ] **Step 1: Write failing mode, budget, and bounded-batch tests**

```python
def test_legacy_mode_processing_is_noop(task, authority):
    authority.mode = "legacy"
    assert task.run(limit=50) == {"status": "skipped", "reason": "legacy_mode"}

def test_batch_never_exceeds_limit(task, queued_work):
    assert task.run(limit=10)["claimed"] <= 10
```

- [ ] **Step 2: Run tests and confirm tasks are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_taxonomy_celery_contract.py -q`

Expected: FAIL on task import/registration.

- [ ] **Step 3: Implement bounded entry points**

Provider work uses no publication lock; persistence uses the shared fence. Discovery/processing runs in shadow, dual, and economic modes. Delivery retries ordered logical events. Lifecycle and metrics target explicit processing/interpretation inputs. Generation preparation never publishes automatically.

- [ ] **Step 4: Register existing queues and schedules**

Use the existing `celery` queue: discovery every five minutes, delivery every minute, lifecycle daily at 02:10 configured timezone, metrics after current theme metrics, and preparation only by explicit operator command or reviewed release workflow. Add no worker process.

- [ ] **Step 5: Run task contracts and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_taxonomy_celery_contract.py tests/unit/test_theme_discovery_ingestion_tasks.py tests/unit/test_social_worker_compose_contract.py -q`

Expected: PASS.

```bash
git add backend/app/tasks/economic_taxonomy_tasks.py backend/app/celery_app.py backend/tests/unit/test_economic_taxonomy_tasks.py backend/tests/unit/test_economic_taxonomy_celery_contract.py
git commit -m "feat: schedule economic taxonomy processing"
```

### Task 18: Cut all readers over and register reader capability

**Files:**
- Create: `backend/app/services/economic_theme_read_service.py`
- Modify: `backend/app/api/v1/themes_queries.py`
- Modify: `backend/app/api/v1/themes_taxonomy.py`
- Modify: `backend/app/api/v1/stocks.py`
- Modify: `backend/app/services/digest_service.py`
- Modify: `backend/app/services/social_confirmation_reader.py`
- Modify: `backend/app/services/social_theme_market_service.py`
- Modify: `backend/app/interfaces/mcp/market_copilot.py`
- Modify: `backend/app/services/ui_snapshot_service.py`
- Create: `frontend/src/api/economicThemes.js`
- Create: `frontend/src/features/themes/components/EconomicThemeDetailModal.jsx`
- Create: `frontend/src/components/Themes/EconomicTaxonomyReview.jsx`
- Modify: `frontend/src/features/themes/pages/ThemesPageContainer.jsx`
- Test: `backend/tests/unit/test_economic_theme_read_service.py`
- Test: `backend/tests/unit/test_economic_theme_consumer_cutover.py`
- Test: `frontend/src/api/economicThemes.test.js`
- Test: `frontend/src/features/themes/components/EconomicThemeDetailModal.test.jsx`
- Test: `frontend/src/components/Themes/EconomicTaxonomyReview.test.jsx`

**Interfaces:**
- Consumes: one serving generation resolved at request/job start.
- Produces: authority-aware backend facade, generation-aware UI, and a signed/tested `ReaderCapabilityManifest` input.

- [ ] **Step 1: Write failing backend bypass and generation-consistency tests**

```python
@pytest.mark.parametrize(("mode", "source"), [
    ("legacy", "legacy"), ("shadow", "legacy"),
    ("dual", "legacy"), ("economic", "economic"),
])
def test_reader_follows_authority(mode, source, reader):
    assert reader.for_mode(mode).source_name == source

def test_economic_request_uses_one_generation(reader, query_spy):
    reader.list_themes()
    assert query_spy.resolved_generation_count == 1
```

- [ ] **Step 2: Inventory consumers and make bypass detection executable**

Run: `rg -l 'ThemeCluster|ThemeMention|ThemeMetrics|ThemeConstituent|parent_cluster_id|is_l1|taxonomy_level' backend/app --glob '*.py'`

Encode the allowed legacy adapter modules in `test_economic_theme_consumer_cutover.py`; fail if any economic-mode consumer directly reads legacy semantic tables.

- [ ] **Step 3: Implement the backend facade and route every listed consumer**

Resolve generation once and read its taxonomy, interpretation, metrics, mappings, Social state, and snapshots. Legacy/shadow/dual preserve existing outputs. Economic legacy-shaped responses use reviewed mappings/redirects only, never display-name inference.

- [ ] **Step 4: Write and run failing frontend identity, availability, and conflict tests**

Run: `cd frontend && npm run test:run -- src/api/economicThemes.test.js src/features/themes/components/EconomicThemeDetailModal.test.jsx src/components/Themes/EconomicTaxonomyReview.test.jsx`

Expected: FAIL on missing modules.

- [ ] **Step 5: Implement the global UI and review workflow**

Show five ranking views with explicit unavailable states; stable identity details; facets/relationships; direct versus derived evidence; source-family counts; structured signals; developments; constituents; split allocations; Social decision conflicts; preview hash; reviewer reason; and stale-preview refresh. Legacy/shadow/dual show existing production UI plus admin preview; economic shows the global UI.

- [ ] **Step 6: Register reader capability only after contract tests pass**

Build `ReaderCapabilityManifest(backend_contract=1, frontend_contract=1, migration_version="0054", consumer_test_hash=<test inventory hash>)`. The release command persists it only after backend consumer tests, frontend tests, and build succeed.

- [ ] **Step 7: Run backend/frontend verification and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_read_service.py tests/unit/test_economic_theme_consumer_cutover.py tests/unit/test_theme_endpoints_contract.py tests/unit/test_ui_snapshot_service.py -q`

Run: `cd frontend && npm run test:run -- src/api/economicThemes.test.js src/features/themes/components/EconomicThemeDetailModal.test.jsx src/components/Themes/EconomicTaxonomyReview.test.jsx src/pages/ThemesPage.test.jsx`

Run: `cd frontend && npm run build`

Expected: PASS; economic consumers use no unapproved legacy semantic read.

```bash
git add backend/app/services/economic_theme_read_service.py backend/app/api/v1/themes_queries.py backend/app/api/v1/themes_taxonomy.py backend/app/api/v1/stocks.py backend/app/services/digest_service.py backend/app/services/social_confirmation_reader.py backend/app/services/social_theme_market_service.py backend/app/interfaces/mcp/market_copilot.py backend/app/services/ui_snapshot_service.py backend/tests/unit/test_economic_theme_read_service.py backend/tests/unit/test_economic_theme_consumer_cutover.py frontend/src/api/economicThemes.js frontend/src/api/economicThemes.test.js frontend/src/features/themes/components/EconomicThemeDetailModal.jsx frontend/src/features/themes/components/EconomicThemeDetailModal.test.jsx frontend/src/components/Themes/EconomicTaxonomyReview.jsx frontend/src/components/Themes/EconomicTaxonomyReview.test.jsx frontend/src/features/themes/pages/ThemesPageContainer.jsx
git commit -m "feat: cut readers over to serving generations"
```

### Task 19: Enforce zero-skip release gates and write the operator runbook

**Files:**
- Create: `backend/tests/required_economic_taxonomy_postgres.txt`
- Create: `backend/scripts/run_required_economic_taxonomy_postgres.py`
- Modify: `.github/workflows/ci.yml`
- Create: `docs/runbooks/economic-taxonomy-cutover.md`
- Modify: `docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md`
- Test: `backend/tests/unit/test_required_economic_taxonomy_postgres.py`
- Test: `backend/tests/unit/test_economic_taxonomy_runbook.py`

**Interfaces:**
- Consumes: every prior task.
- Produces: exact PostgreSQL gate, reader-ready release artifact, and catch-up/barrier/recovery procedures.

- [ ] **Step 1: Write failing gate and runbook contract tests**

```python
def test_required_gate_rejects_skipped_node(tmp_path, fake_pytest):
    result = run_required_tests(manifest_with("test_cutover_race"), fake_pytest.skip_it())
    assert result.exit_code != 0

def test_runbook_names_catchup_barrier_and_recovery():
    text = RUNBOOK.read_text()
    for phrase in (
        "catch-up outside the publication transaction",
        "exclusive writer fence", "exact evidence manifest",
        "reader capability", "rollback_recovery",
    ):
        assert phrase in text
```

- [ ] **Step 2: Run tests and confirm gate/runbook are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_required_economic_taxonomy_postgres.py tests/unit/test_economic_taxonomy_runbook.py -q`

Expected: FAIL on missing script/runbook.

- [ ] **Step 3: Implement the exact-node PostgreSQL runner**

Read non-comment node IDs, run `pytest --collect-only`, fail if any ID is absent, then execute with a plugin that counts pass/fail/skip/xfail/xpass. Exit nonzero unless every listed node passed and PostgreSQL identity was verified. Include snapshot sealing, fence, work, processing publication, outbox, Social, and publication race suites.

- [ ] **Step 4: Add the CI gate**

```yaml
- name: Required economic taxonomy PostgreSQL contracts
  env:
    DATABASE_URL: postgresql://ci:ci@localhost:5432/ci
    STOCKSCANNER_TEST_ALLOW_POSTGRES: "1"
  run: cd backend && ./venv/bin/python scripts/run_required_economic_taxonomy_postgres.py
```

- [ ] **Step 5: Write exact operator commands and stop conditions**

Document migration, seed, shadow, benchmark, reviewed dispositions/allocations, dual mode, catch-up, outbox drain, generation preparation, reader-capability verification, final barrier, publication verification, normal rollback, and `rollback_recovery`. Stop on unresolved allocations/conflicts, changed manifest, pending required delivery, stale snapshot hash, missing reader capability, benchmark failure, or any skipped required PostgreSQL node.

- [ ] **Step 6: Run focused backend and legacy regressions**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_economic_taxonomy_contracts.py tests/unit/test_economic_taxonomy_snapshots.py tests/unit/test_economic_taxonomy_interpretations.py tests/unit/test_economic_taxonomy_mappings.py tests/unit/test_economic_taxonomy_outbox.py tests/unit/test_economic_taxonomy_social_adapter.py tests/unit/test_economic_taxonomy_developments.py tests/unit/test_economic_taxonomy_publication.py tests/unit/test_economic_theme_read_service.py tests/unit/test_economic_theme_consumer_cutover.py tests/unit/test_required_economic_taxonomy_postgres.py tests/unit/test_economic_taxonomy_runbook.py tests/unit/test_theme_claim_review.py tests/unit/test_theme_state_authorities.py tests/unit/test_theme_development.py tests/integration/test_social_theme_projection.py`

Expected: PASS with zero skips in this focused set.

- [ ] **Step 7: Run the required PostgreSQL gate and full frontend verification**

Run: `cd backend && DATABASE_URL=postgresql://ci:ci@localhost:5432/ci STOCKSCANNER_TEST_ALLOW_POSTGRES=1 ./venv/bin/python scripts/run_required_economic_taxonomy_postgres.py`

Run: `cd frontend && npm run test:run`

Run: `cd frontend && npm run build`

Expected: every manifest node passes with zero skips/xfails; full Vitest and production build pass.

- [ ] **Step 8: Rehearse cutover and rollback recovery in disposable PostgreSQL**

Seed representative legacy themes, a Refining split, duplicate/conflicting Social associations, Social-native development, corrected-to-empty source, UI snapshots, and an out-of-order compatibility event. Run the exact runbook and record generation IDs, taxonomy/interpretation/manifest hashes, checkpoints, epoch, capability manifest, and post-rollback reader equivalence.

- [ ] **Step 9: Mark the design/plan release gate and commit**

Update the design status only after the rehearsal artifact is attached. Link the runbook to the design, ADR, and this plan.

```bash
git add backend/tests/required_economic_taxonomy_postgres.txt backend/scripts/run_required_economic_taxonomy_postgres.py .github/workflows/ci.yml docs/runbooks/economic-taxonomy-cutover.md docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md backend/tests/unit/test_required_economic_taxonomy_postgres.py backend/tests/unit/test_economic_taxonomy_runbook.py
git commit -m "docs: gate economic taxonomy publication"
```

---

## Dependency Order

1. Task 0 is mandatory before any migration or schema implementation.
2. Tasks 1-3 establish sealed semantics, append-only interpretation history, serving generations, and the fence used by every writer.
3. Tasks 4-8 establish governed extraction, frozen admission, processing-head updates, and current interpretation selection.
4. Tasks 9-10 establish cardinality-safe governance, lifecycle, signals, and metrics.
5. Tasks 11-13 integrate every producer through the shared fence and ordered compatibility protocol.
6. Tasks 14-15 build coherent reader artifacts and migration inputs without changing production authority.
7. Task 16 is the only implementation allowed to change serving generation or mode.
8. Task 17 schedules bounded work but cannot publish automatically.
9. Task 18 completes the authority-aware reader/frontend capability required by cutover.
10. Task 19 is the production release gate and cannot be waived by SQLite, manual spot checks, or unverified test collection.

Do not enter `dual` before Tasks 11-15 pass. Do not enter `economic` before Tasks 16-19 pass, the exact PostgreSQL gate reports zero skips/xfails, the benchmark is reviewed, and the reader capability manifest is ready. Do not remove legacy records or compatibility writes in this project.

## Recommended Execution

Use **subagent-driven development**. The twenty tasks have crisp review boundaries, while mistakes in identity, interpretation selection, split allocation, Social decision preservation, fencing, or publication can silently corrupt historical meaning. Require a fresh implementation review after every task and a whole-branch review before the Task 19 rehearsal.
