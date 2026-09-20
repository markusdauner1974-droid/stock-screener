# Open Multi-Dimensional Economic Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pipeline-scoped and L1/L2 theme identity with a versioned global Economic Theme taxonomy, while preserving evidence provenance and supporting a fenced, reversible production cutover.

**Architecture:** Build an immutable Economic Taxonomy beside the legacy Theme Catalog. Source-level work extracts evidence-backed exposure candidates, retrieval proposes possible matches, semantic resolution decides identity, and observations attach analytical lenses without duplicating evidence. A database authority row, epoch fencing, durable outbox, versioned UI snapshots, migration mappings, and continued compatibility writes provide shadow, dual, economic, and rollback modes.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, PostgreSQL 16, SQLite test harness, Celery, existing LLM and embedding services, React, MUI, TanStack Query, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md`

## Global Constraints

- `EconomicTheme.semantic_key` is an opaque UUID assigned once; display names and facets never define identity.
- Published taxonomy versions are complete immutable snapshots; drafts clone their complete parent snapshot.
- Production authority is the singleton `taxonomy_authority` row with mode `legacy|shadow|dual|economic`, an active version, and a monotonically increasing epoch.
- `shadow` and `dual` serve legacy reads; `economic` serves the sealed Economic Taxonomy version.
- Similarity may retrieve candidates but cannot decide equivalence.
- Compound themes require explicit composition support; co-occurrence alone is insufficient.
- A source revision may have multiple distinct primary claims, while derived observations share a root and all claims share one source-family identity.
- `security_id` always means `stock_universe.id` resolved through SecurityMaster rules.
- Existing grounding, evidence eligibility, Social administration, and development-event history remain authoritative.
- Structural merges, splits, defining-mechanism changes, new dimensions, and retirement require reviewed proposals.
- Legacy Theme Catalog writes continue after economic cutover until a separate cleanup project retires rollback compatibility.
- This project does not infer issuer revenue materiality, add recursive ontology propagation, replace SecurityMaster, or create a general asset master.
- Production publication requires PostgreSQL concurrency tests; skipped PostgreSQL variants do not satisfy the gate.

## Review Focus

1. Independent AI and memory mentions must not create `AI Memory`; Task 7 pins this with an unsupported-composition test.
2. An authority epoch change during processing must leave no mixed write; Tasks 6 and 17 pin this with stale-worker and publication-race tests.
3. A source discussing two independent themes plus derived parents must count as one source family without collapsing the two primary roots; Task 10 pins this invariant.
4. Social admin decisions and evidence-work IDs must survive shadow, dual, economic, and rollback modes; Task 14 pins state-preservation and compatibility-write tests.
5. A failed UI snapshot or delta replay must leave the old authority and pointers active; Tasks 15 and 17 inject failures before the atomic switch.

## Delivery Slices

- **Slice A — Semantic kernel:** Tasks 1-4 deliver pure policy, immutable schema, authority, facets, and naming without changing production behavior.
- **Slice B — Source processing:** Tasks 5-9 deliver durable source work, extraction, retrieval, resolution, and provisional publication in shadow storage.
- **Slice C — Evidence and governance:** Tasks 10-12 deliver observations, constituents, lifecycle, metrics, and reviewed operations.
- **Slice D — Producer and reader adapters:** Tasks 13-15 integrate legacy and Social producers, APIs, and versioned UI snapshots while legacy remains authoritative.
- **Slice E — Migration and cutover:** Tasks 16-18 deliver benchmarked migration, epoch-fenced publication, rollback, and scheduled operations.
- **Slice F — Product cutover:** Tasks 19-21 replace UI and downstream readers, enforce CI gates, and publish the operator runbook.

## File Map

### New domain and persistence files

- `backend/app/domain/economic_taxonomy/contracts.py` — enums and immutable value objects shared by services.
- `backend/app/domain/economic_taxonomy/policy.py` — pure validation, lifecycle, propagation, and review-gate policy.
- `backend/app/models/economic_taxonomy.py` — stable identities and complete immutable taxonomy snapshot tables.
- `backend/app/models/economic_taxonomy_runtime.py` — work, candidates, observations, metrics, proposals, migration, and outbox tables.
- `backend/app/infra/db/repositories/economic_taxonomy_repo.py` — snapshot, authority, draft, and publication persistence.
- `backend/app/infra/db/repositories/economic_taxonomy_work_repo.py` — idempotent enqueue, lease, retry, observation, and outbox persistence.

### New services and interfaces

- `backend/app/services/economic_taxonomy_authority.py` — authority state, mode transitions, advisory lock, and epoch checks.
- `backend/app/services/economic_taxonomy_seed.py` — approved facet-dimension seed data.
- `backend/app/services/economic_theme_naming.py` — deterministic names and naming-review result.
- `backend/app/services/economic_source_revision.py` — canonical content and Social source revisions/families.
- `backend/app/services/economic_exposure_extraction.py` — structured extraction only.
- `backend/app/services/economic_exposure_claim_review.py` — evidence review and legacy-status mapping.
- `backend/app/services/economic_theme_candidate_retrieval.py` — bounded lexical, facet, alias, embedding, and constituent retrieval.
- `backend/app/services/economic_theme_resolution.py` — constrained semantic identity decision and deterministic post-validation.
- `backend/app/services/economic_taxonomy_processor.py` — end-to-end source processing and provisional identity publication.
- `backend/app/services/economic_theme_observation_service.py` — primary/derived provenance and lens associations.
- `backend/app/services/economic_theme_lifecycle_service.py` — provisional, established, dormant, and reactivated transitions.
- `backend/app/services/economic_theme_metrics_service.py` — lens metrics with direct/root/source-family counts.
- `backend/app/services/economic_taxonomy_operations.py` — proposal preview/apply and immutable structural operations.
- `backend/app/services/economic_taxonomy_runtime.py` — mode-aware write routing and legacy compatibility delivery.
- `backend/app/services/economic_taxonomy_migration.py` — migration runs, dispositions, mappings, and delta replay.
- `backend/app/services/economic_taxonomy_cutover.py` — prepare, publish, rollback, and validation gates.
- `backend/app/services/economic_theme_read_service.py` — authority-aware reads for API, stock, digest, assistant, and MCP callers.
- `backend/app/api/v1/economic_themes.py` and `backend/app/api/v1/economic_taxonomy.py` — global read and reviewed-write APIs.
- `backend/app/tasks/economic_taxonomy_tasks.py` — discovery, processing, outbox, lifecycle, metrics, and shadow-validation tasks.

### Migrations and tests

- `backend/alembic/versions/20260921_0046_economic_taxonomy_core.py` — identity, immutable snapshot, and authority tables.
- `backend/alembic/versions/20260921_0047_economic_taxonomy_runtime.py` — work, evidence, metrics, proposals, migration, mapping, and outbox tables.
- `backend/alembic/versions/20260921_0048_economic_taxonomy_social_adapter.py` — Social association mapping columns.
- `backend/alembic/versions/20260921_0049_economic_taxonomy_ui_snapshot.py` — UI snapshot authority columns.
- Unit tests use `backend/tests/unit/test_economic_*.py`; migration and concurrency tests use `backend/tests/integration/test_economic_*.py`.
- `backend/tests/fixtures/economic_taxonomy/contrast_cases.json` contains the cutover benchmark corpus.

### Frontend and operations

- `frontend/src/api/economicThemes.js` — global read and governance clients.
- `frontend/src/features/themes/components/EconomicThemeDetailModal.jsx` — facets, relationships, evidence, developments, and constituents.
- `frontend/src/components/Themes/EconomicTaxonomyReview.jsx` — migration and structural review queue.
- `docs/runbooks/economic-taxonomy-cutover.md` — exact shadow, dual, publish, verify, and rollback commands.

---

### Task 1: Define the semantic contracts and pure policy

**Files:**
- Create: `backend/app/domain/economic_taxonomy/__init__.py`
- Create: `backend/app/domain/economic_taxonomy/contracts.py`
- Create: `backend/app/domain/economic_taxonomy/policy.py`
- Test: `backend/tests/unit/test_economic_taxonomy_policy.py`

**Interfaces:**
- Consumes: no database or provider services.
- Produces: `EvidenceRef`, `LensEligibility`, `SourceRevision`, `FacetClaim`, `ConstituentClaim`, `ExposureCandidate`, `ResolutionCandidate`, `ResolutionDecision`, `CandidateValidation`, `LifecycleEvidence`, `DerivedTarget`, and the enums used by every later task.

- [ ] **Step 1: Write failing tests for namespace, specificity, lifecycle, and propagation policy**

```python
def test_technical_setup_is_not_an_economic_theme():
    result = validate_candidate(candidate(name="VCP", mechanism="technical setup"))
    assert result.accepted is False
    assert result.error_code == "unsupported_exposure"

def test_missing_hbm_specificity_stops_at_ai_memory():
    result = choose_specificity(supported=("AI", "Memory"), unsupported=("HBM",))
    assert result.resolved == ("AI", "Memory")
    assert result.unresolved_narrower == (("AI", "HBM"),)

def test_propagation_is_one_hop_only():
    assert derive_targets(primary=11, relationships={11: (12,), 12: (13,)}) == (
        DerivedTarget(theme_id=12, path=(11, 12)),
    )
```

- [ ] **Step 2: Run the policy test and confirm it fails on missing imports**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_policy.py -q`

Expected: FAIL with `ModuleNotFoundError: app.domain.economic_taxonomy`.

- [ ] **Step 3: Implement exact enums and immutable value objects**

```python
class AuthorityMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    DUAL = "dual"
    ECONOMIC = "economic"

class ResolutionOutcome(StrEnum):
    EQUIVALENT = "equivalent"
    SPECIALIZATION = "specialization"
    BROADER = "broader"
    RELATED = "related"
    DISTINCT = "distinct"
    AMBIGUOUS = "ambiguous"

class FailureCode(StrEnum):
    UNSUPPORTED_EXPOSURE = "unsupported_exposure"
    UNSUPPORTED_COMPOSITION = "unsupported_composition"
    UNRESOLVED_SPECIFICITY = "unresolved_specificity"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    CANDIDATE_DIMENSION = "candidate_dimension"
    SPLIT_REVIEW_REQUIRED = "split_review_required"
    RESOLVER_UNAVAILABLE = "resolver_unavailable"
    CLAIM_REVIEW_UNAVAILABLE = "claim_review_unavailable"
    AUTHORITY_EPOCH_CHANGED = "authority_epoch_changed"
    SOURCE_REVISION_CHANGED = "source_revision_changed"
    STALE_REVIEW_PREVIEW = "stale_review_preview"
    PUBLICATION_VALIDATION_FAILED = "publication_validation_failed"

@dataclass(frozen=True)
class LensEligibility:
    lens: Literal["technical", "fundamental", "narrative"]
    provenance_kind: Literal["content_eligibility", "social_work"]
    provenance_id: int

@dataclass(frozen=True)
class SourceRevision:
    source_kind: Literal["content_item", "social_work"]
    source_id: int
    revision: str
    source_family_key: str
    observed_at: datetime
    title: str
    text: str
    evidence: tuple[EvidenceRef, ...]
    lens_eligibility: tuple[LensEligibility, ...]
```

Implement `validate_candidate`, `choose_specificity`, `requires_structural_review`, `evaluate_lifecycle`, and `derive_targets` as pure functions. Export support states `direct|inferred|unsupported|unresolved`, observation kinds `primary|derived`, lenses `technical|fundamental|narrative`, and lifecycle states `provisional|established|dormant|reactivated|retired`.

- [ ] **Step 4: Run the policy test**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the semantic kernel**

```bash
git add backend/app/domain/economic_taxonomy backend/tests/unit/test_economic_taxonomy_policy.py
git commit -m "feat: define economic taxonomy domain policy"
```

### Task 2: Add stable identity and complete immutable snapshot persistence

**Files:**
- Create: `backend/app/models/economic_taxonomy.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260921_0046_economic_taxonomy_core.py`
- Test: `backend/tests/unit/test_economic_taxonomy_models.py`
- Test: `backend/tests/integration/test_economic_taxonomy_core_migration.py`

**Interfaces:**
- Consumes: enums from Task 1.
- Produces: `TaxonomyVersion`, `EconomicTheme`, `EconomicThemeRevision`, `EconomicThemeAlias`, `FacetDimension`, `FacetValue`, `ThemeFacetAssignment`, `ThemeRelationshipAssertion`, and `TaxonomyAuthority`.

- [ ] **Step 1: Write failing model tests for identity and snapshot constraints**

```python
def test_identity_has_no_mutable_semantic_fields():
    assert set(EconomicTheme.__table__.columns.keys()) == {"id", "semantic_key", "created_at"}

def test_relationship_rejects_self_edge(db_session, sealed_version, theme):
    db_session.add(ThemeRelationshipAssertion(
        taxonomy_version_id=sealed_version.id,
        source_theme_id=theme.id,
        target_theme_id=theme.id,
        relationship_type="related",
        canonical_pair_low_id=theme.id,
        canonical_pair_high_id=theme.id,
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run model tests and confirm the models are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_models.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement the core models and constraints**

```python
class EconomicTheme(Base):
    __tablename__ = "economic_themes"
    id = Column(Integer, primary_key=True)
    semantic_key = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class TaxonomyAuthority(Base):
    __tablename__ = "taxonomy_authority"
    id = Column(Integer, primary_key=True)
    mode = Column(String(16), nullable=False, default="legacy")
    active_version_id = Column(Integer, ForeignKey("taxonomy_versions.id", ondelete="RESTRICT"))
    authority_epoch = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor = Column(String(120), nullable=False)
    reason = Column(Text, nullable=False)
```

Add composite primary or unique keys that include `taxonomy_version_id` for every revision, alias, dimension, value, assignment, and relationship row. Store only `specializes`; canonicalize `related` and `distinct` pairs with `canonical_pair_low_id < canonical_pair_high_id`. Constrain version status to `draft|sealed|published|superseded`. Seed singleton authority row `id=1, mode='legacy', authority_epoch=1` in the migration.

Create database triggers for every semantic snapshot table that reject inserts, updates, and deletes when the referenced taxonomy version is `sealed`, `published`, or `superseded`. Use PostgreSQL trigger functions in production and equivalent SQLite triggers in the test migration.

- [ ] **Step 4: Implement upgrade and downgrade migration tests**

The SQLite test must assert all tables, the singleton row, and raw-SQL mutation rejection for a sealed version. The PostgreSQL variant must assert JSONB columns, check constraints, foreign keys, unique indexes, trigger protection, and that a self-edge fails.

Run: `cd backend && ./venv/bin/pytest tests/integration/test_economic_taxonomy_core_migration.py -q`

Expected: PASS on SQLite; PostgreSQL case passes when `STOCKSCANNER_TEST_ALLOW_POSTGRES=1`.

- [ ] **Step 5: Run model registration and migration-head checks**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_models.py tests/unit/test_main_migrations.py -q`

Expected: PASS and Alembic head `20260921_0046`.

- [ ] **Step 6: Commit the core schema**

```bash
git add backend/app/models/economic_taxonomy.py backend/app/models/__init__.py backend/alembic/versions/20260921_0046_economic_taxonomy_core.py backend/tests/unit/test_economic_taxonomy_models.py backend/tests/integration/test_economic_taxonomy_core_migration.py
git commit -m "feat: add immutable economic taxonomy schema"
```

### Task 3: Implement snapshot loading, cloning, sealing, and authority transitions

**Files:**
- Create: `backend/app/infra/db/repositories/economic_taxonomy_repo.py`
- Create: `backend/app/services/economic_taxonomy_authority.py`
- Test: `backend/tests/unit/test_economic_taxonomy_authority.py`
- Test: `backend/tests/integration/test_economic_taxonomy_authority_postgres.py`

**Interfaces:**
- Consumes: Task 2 models.
- Produces: `TaxonomySnapshot`, `TaxonomyAuthorityState`, `EconomicTaxonomyRepository.load_snapshot()`, `clone_draft()`, `seal_draft()`, `publish_version()`, and `transition_mode()`.

- [ ] **Step 1: Write failing snapshot and immutability tests**

```python
def test_clone_draft_copies_complete_parent(repo, published_version):
    draft_id = repo.clone_draft(published_version.id, actor="test", reason="rename")
    assert repo.snapshot_hash(draft_id) == repo.snapshot_hash(published_version.id)

def test_published_revision_cannot_be_updated(db_session, published_revision):
    published_revision.display_name = "mutated"
    with pytest.raises(ValueError, match="published_taxonomy_immutable"):
        db_session.flush()
```

- [ ] **Step 2: Run the unit tests and confirm repository imports fail**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_authority.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement repository contracts**

```python
@dataclass(frozen=True)
class TaxonomyAuthorityState:
    mode: AuthorityMode
    active_version_id: int | None
    authority_epoch: int

snapshot: TaxonomySnapshot = repo.load_snapshot(version_id)
draft_id: int = repo.clone_draft(parent_version_id, actor=actor, reason=reason)
content_hash: str = repo.seal_draft(draft_id)
published: TaxonomyAuthorityState = repo.publish_version(
    draft_id, expected_version_id=parent_version_id,
    expected_epoch=expected_epoch, actor=actor, reason=reason,
)
transitioned: TaxonomyAuthorityState = repo.transition_mode(
    target_mode, expected_epoch=published.authority_epoch,
    actor=actor, reason=reason,
)
```

Use `SELECT ... FOR UPDATE` on the singleton authority row and `SELECT pg_advisory_xact_lock(78124017)` on PostgreSQL. SQLite tests use the row lock path without executing PostgreSQL SQL. Hash a canonical, sorted JSON representation of the complete snapshot.

- [ ] **Step 4: Add ORM and bulk-update guards for sealed semantic rows**

Register `Session.before_flush` and `Session.do_orm_execute` guards covering every semantic snapshot class. Both paths raise `published_taxonomy_immutable` when the referenced version is sealed or published.

- [ ] **Step 5: Run SQLite and PostgreSQL concurrency tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_authority.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_authority_postgres.py -q`

Expected: one concurrent publisher succeeds, one receives `authority_epoch_changed`, and the active version is complete.

- [ ] **Step 6: Commit authority and immutable publication**

```bash
git add backend/app/infra/db/repositories/economic_taxonomy_repo.py backend/app/services/economic_taxonomy_authority.py backend/tests/unit/test_economic_taxonomy_authority.py backend/tests/integration/test_economic_taxonomy_authority_postgres.py
git commit -m "feat: publish immutable taxonomy snapshots"
```

### Task 4: Seed governed facets and deterministic naming

**Files:**
- Create: `backend/app/services/economic_taxonomy_seed.py`
- Create: `backend/app/services/economic_theme_naming.py`
- Test: `backend/tests/unit/test_economic_taxonomy_seed.py`
- Test: `backend/tests/unit/test_economic_theme_naming.py`

**Interfaces:**
- Consumes: Task 1 facets and Task 3 draft repository.
- Produces: `INITIAL_DIMENSIONS`, `seed_initial_dimensions(repo, draft_id)`, `bootstrap_economic_taxonomy(repo)`, and `name_candidate(candidate, snapshot) -> NamingResult`.

- [ ] **Step 1: Write failing seed and naming tests**

```python
def test_ai_memory_name_requires_both_supported_facets(snapshot):
    result = name_candidate(candidate(facets={"technology": "AI", "product": "Memory"}), snapshot)
    assert result.display_name == "AI Memory"
    assert result.requires_review is False

def test_unknown_dimension_is_not_activated(snapshot):
    result = name_candidate(candidate(facets={"moon_phase": "Waxing"}), snapshot)
    assert result.error_code == "candidate_dimension"
    assert result.requires_review is True
```

- [ ] **Step 2: Run tests and confirm missing implementations**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_seed.py tests/unit/test_economic_theme_naming.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement the exact approved dimensions and scopes**

```python
INITIAL_DIMENSIONS = {
    "industry": "theme", "product": "theme", "technology": "theme",
    "end_market": "theme", "commodity": "theme", "customer": "both",
    "value_chain_role": "both", "shipping_segment": "theme",
    "vessel_class": "theme", "geography": "both", "policy_driver": "theme",
    "macro_driver": "theme", "infrastructure_layer": "both",
}
```

Seed only into a draft and make repeated calls idempotent. `bootstrap_economic_taxonomy()` creates and publishes the initial complete snapshot while leaving authority mode `legacy`; a repeated call returns the seeded version without advancing the epoch. Implement deterministic rules for AI Memory, AI HBM, Copper Miners, Crude Tankers, and Product Tankers.

- [ ] **Step 4: Implement constrained semantic naming after resolution**

`name_candidate()` accepts an optional naming provider only after identity resolution. The prompt contains the validated mechanism, approved facet dimensions/values, and forbidden signal/development terms. It returns a name of 2-80 characters or `requires_naming_review`; it may not add a facet or alter the resolved identity.

```python
def test_semantic_namer_cannot_add_unsupported_hbm(snapshot, naming_provider):
    naming_provider.response = {"display_name": "AI HBM"}
    result = name_candidate(ai_memory_candidate(), snapshot, generate=naming_provider)
    assert result.display_name is None
    assert result.error_code == "requires_naming_review"
```

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_seed.py tests/unit/test_economic_theme_naming.py -q`

Expected: PASS.

```bash
git add backend/app/services/economic_taxonomy_seed.py backend/app/services/economic_theme_naming.py backend/tests/unit/test_economic_taxonomy_seed.py backend/tests/unit/test_economic_theme_naming.py
git commit -m "feat: govern economic facets and names"
```

### Task 5: Add durable work, evidence, governance, migration, and outbox persistence

**Files:**
- Create: `backend/app/models/economic_taxonomy_runtime.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260921_0047_economic_taxonomy_runtime.py`
- Test: `backend/tests/unit/test_economic_taxonomy_runtime_models.py`
- Test: `backend/tests/integration/test_economic_taxonomy_runtime_migration.py`

**Interfaces:**
- Consumes: Task 2 identity and version foreign keys.
- Produces: `EconomicTaxonomyWork`, `EconomicExposureCandidateRow`, `EconomicThemeEmbedding`, `ThemeObservation`, `ThemeObservationLens`, `EconomicThemeDevelopmentLink`, `ThemeConstituentExposure`, `ThemePipelineMetric`, `ThemeLifecycleEvent`, `TaxonomyProposal`, `TaxonomyOperation`, `TaxonomyMigrationRun`, `TaxonomyMigrationDisposition`, `LegacyThemeMapping`, and `TaxonomyWriteOutbox`.

- [ ] **Step 1: Write failing constraint and idempotency tests**

```python
def test_work_identity_is_source_and_policy_version_scoped(db_session):
    insert_work(db_session, source_kind="content_item", source_id=7, source_revision="r1")
    with pytest.raises(IntegrityError):
        insert_work(db_session, source_kind="content_item", source_id=7, source_revision="r1")

def test_derived_observation_requires_root(db_session, economic_theme):
    db_session.add(observation(theme=economic_theme, kind="derived", root_id=None))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run tests and confirm runtime models are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_runtime_models.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement the runtime models with named constraints**

```python
class EconomicTaxonomyWork(Base):
    __tablename__ = "economic_taxonomy_work"
    __table_args__ = (UniqueConstraint(
        "source_kind", "source_id", "source_revision",
        "extraction_policy_version", "resolver_policy_version",
        name="uq_economic_taxonomy_work_identity",
    ),)
    eligibility_json = Column(JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False)

class TaxonomyWriteOutbox(Base):
    __tablename__ = "taxonomy_write_outbox"
    event_key = Column(String(64), nullable=False, unique=True)
    target_representation = Column(String(16), nullable=False)
    payload_json = Column(JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False)
    claimed_authority_epoch = Column(Integer, nullable=False)
```

Use explicit status checks from the spec. `eligibility_json` stores the technical, fundamental, and narrative eligibility records that produced the source-level work. `LegacyThemeMapping` is keyed by `(taxonomy_version_id, legacy_theme_cluster_id)` and stores the accepted `economic_theme_id` plus disposition. `ThemeConstituentExposure.security_id` references `stock_universe.id`. Observation uniqueness is `(economic_theme_id, source_kind, source_id, source_revision, claim_fingerprint, observation_kind, derivation_policy_version)`.

- [ ] **Step 4: Implement and run migration round-trip tests**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_economic_taxonomy_runtime_migration.py -q`

Expected: SQLite upgrade/downgrade preserves the core tables from Task 2; PostgreSQL verifies JSONB, partial work indexes, foreign keys, and named checks.

- [ ] **Step 5: Run model registration tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_runtime_models.py tests/unit/test_main_migrations.py -q`

Expected: PASS and Alembic head `20260921_0047`.

- [ ] **Step 6: Commit runtime persistence**

```bash
git add backend/app/models/economic_taxonomy_runtime.py backend/app/models/__init__.py backend/alembic/versions/20260921_0047_economic_taxonomy_runtime.py backend/tests/unit/test_economic_taxonomy_runtime_models.py backend/tests/integration/test_economic_taxonomy_runtime_migration.py
git commit -m "feat: persist economic taxonomy runtime state"
```

### Task 6: Build source revisions, leased work, retries, and epoch fencing

**Files:**
- Create: `backend/app/services/economic_source_revision.py`
- Create: `backend/app/infra/db/repositories/economic_taxonomy_work_repo.py`
- Test: `backend/tests/unit/test_economic_source_revision.py`
- Test: `backend/tests/unit/test_economic_taxonomy_work_repo.py`
- Test: `backend/tests/integration/test_economic_taxonomy_work_postgres.py`

**Interfaces:**
- Consumes: `SourceRevision` from Task 1, content/attachment data, Social work snapshots, authority from Task 3, and work models from Task 5.
- Produces: `build_content_source_revision()`, `build_social_source_revision()`, `enqueue()`, `claim_next()`, `complete()`, `retry()`, and `assert_epoch()`.

- [ ] **Step 1: Write failing source-hash and lease tests**

```python
def test_content_revision_changes_when_attachment_revision_changes(content_item):
    before = build_content_source_revision(content_item, attachment_revision="a")
    after = build_content_source_revision(content_item, attachment_revision="b")
    assert before.revision != after.revision
    assert before.source_family_key == after.source_family_key

def test_worker_aborts_when_authority_epoch_changes(repo, claimed_work):
    repo.bump_authority_epoch()
    with pytest.raises(AuthorityEpochChanged):
        repo.complete(claimed_work.id, claimed_work.lease_token)
```

- [ ] **Step 2: Run tests and confirm missing functions**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_source_revision.py tests/unit/test_economic_taxonomy_work_repo.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement canonical revision hashing**

```python
def build_content_source_revision(item, *, attachments, preparation_metadata, eligibility_rows) -> SourceRevision:
    payload = {
        "content_item_id": item.id,
        "title": item.title or "",
        "content": item.content or "",
        "attachment_revision": item.attachment_revision,
        "attachments": sorted(attachments, key=lambda row: row["reference_key"]),
        "preparation_metadata": preparation_metadata,
        "lens_eligibility": sorted(
            (row.pipeline, row.id, row.channel, row.originating_source_id, row.observed_at.isoformat())
            for row in eligibility_rows
        ),
    }
    return source_revision("content_item", item.id, payload, observed_at=item.published_at)
```

Social revisions hash `SocialExtractionWork.input_snapshot_json`, `input_hash`, prompt/schema/model identity, saved result identity, and the narrative eligibility provenance. Source-family keys use the admitted content identity, not the extraction policy version. When technical or fundamental eligibility changes, the new content revision supersedes the prior work so the processor still extracts once while attaching every currently eligible lens.

- [ ] **Step 4: Implement leased work operations and lock order**

`claim_next()` locks work rows using `FOR UPDATE SKIP LOCKED`, records a UUID lease token, a five-minute lease, and current authority epoch. `complete()` locks authority first, then work; it rejects changed epochs or source revisions, marks the old work retryable, and enqueues the new revision. Three lease expiries become `failed_terminal`; provider quota, rate, and timeout outcomes remain `failed_retryable` with exponential backoff.

- [ ] **Step 5: Run concurrency and stale-revision tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_source_revision.py tests/unit/test_economic_taxonomy_work_repo.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_work_postgres.py -q`

Expected: two workers never claim the same row; stale epoch and source revision commits persist no candidate or observation rows.

- [ ] **Step 6: Commit durable work processing**

```bash
git add backend/app/services/economic_source_revision.py backend/app/infra/db/repositories/economic_taxonomy_work_repo.py backend/tests/unit/test_economic_source_revision.py backend/tests/unit/test_economic_taxonomy_work_repo.py backend/tests/integration/test_economic_taxonomy_work_postgres.py
git commit -m "feat: add fenced economic taxonomy work queue"
```

### Task 7: Extract and review structured economic exposures

**Files:**
- Create: `backend/app/services/economic_exposure_extraction.py`
- Create: `backend/app/services/economic_exposure_claim_review.py`
- Test: `backend/tests/unit/test_economic_exposure_extraction.py`
- Test: `backend/tests/unit/test_economic_exposure_claim_review.py`
- Modify: `backend/app/services/theme_claim_evidence.py`

**Interfaces:**
- Consumes: `SourceRevision`, Task 1 contracts, the existing LLM service, grounding context, and admitted evidence sources.
- Produces: `EconomicExposureExtractor.extract(source) -> tuple[ExposureCandidate, ...]` and `review_exposure_candidates(candidates, source, generate) -> ReviewedBatch`.

- [ ] **Step 1: Write failing structured-output and composition tests**

```python
def test_independent_ai_and_memory_sentences_reject_compound(review):
    source = "AI server shipments accelerated. Separately, memory prices rose."
    result = review(source, extracted_candidate("AI Memory", compound=True))
    assert result.accepted == ()
    assert result.decisions[0].error_code == "unsupported_composition"

def test_supported_theme_survives_unsupported_development(review):
    result = review("Memory suppliers discussed pricing.", candidate_with_development())
    assert result.accepted[0].display_name_hint == "Memory"
    assert result.accepted[0].development_candidate is None
```

- [ ] **Step 2: Run tests and confirm extraction modules are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement a strict extraction schema and prompt**

The provider response is a JSON array whose items contain exactly these keys:

```json
{
  "display_name_hint": "AI Memory",
  "economic_mechanism": "AI accelerator demand increases memory demand",
  "compound": true,
  "plausibly_multi_security": true,
  "facet_claims": [{"dimension": "technology", "value": "AI"}, {"dimension": "product", "value": "Memory"}],
  "composition_support": {"status": "direct", "evidence_refs": ["primary:42-96"]},
  "constituent_claims": [],
  "development_candidate": null,
  "resolved_specificity": ["AI", "Memory"],
  "unresolved_narrower_candidates": [["AI", "HBM"]],
  "evidence_refs": ["primary:42-96"]
}
```

Reject extra keys, more than 30 candidates, malformed evidence references, unapproved dimension keys, and technical signals as identities.

- [ ] **Step 4: Implement claim review without weakening existing authorities**

Map `supported -> direct`, `inferred -> inferred`, `unsupported -> unsupported`, development-only `absent -> absent`, and provider/coverage failure to `unresolved`. Composition and every defining facet are reviewed independently. Reuse evidence normalization from `theme_claim_evidence.py`; do not change the legacy reviewer response contract.

- [ ] **Step 5: Run new and existing claim-review tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py tests/unit/test_theme_claim_review.py tests/unit/test_theme_grounding_context.py -q`

Expected: PASS.

- [ ] **Step 6: Commit structured extraction**

```bash
git add backend/app/services/economic_exposure_extraction.py backend/app/services/economic_exposure_claim_review.py backend/app/services/theme_claim_evidence.py backend/tests/unit/test_economic_exposure_extraction.py backend/tests/unit/test_economic_exposure_claim_review.py
git commit -m "feat: extract reviewed economic exposures"
```

### Task 8: Retrieve candidates and resolve semantic identity

**Files:**
- Create: `backend/app/services/economic_theme_candidate_retrieval.py`
- Create: `backend/app/services/economic_theme_resolution.py`
- Test: `backend/tests/unit/test_economic_theme_candidate_retrieval.py`
- Test: `backend/tests/unit/test_economic_theme_resolution.py`
- Test: `backend/tests/unit/test_economic_theme_contrast_cases.py`

**Interfaces:**
- Consumes: reviewed candidates from Task 7, snapshots from Task 3, and embedding generation from `backend/app/services/theme_embedding_service.py`.
- Produces: `retrieve_candidates(candidate, snapshot, limit=12) -> tuple[ResolutionCandidate, ...]` and `resolve_identity(candidate, retrieved, generate) -> ResolutionDecision`.

- [ ] **Step 1: Write failing retrieval-versus-decision tests**

```python
def test_high_embedding_similarity_only_retrieves(snapshot, embedder):
    rows = retrieve_candidates(exposure("AI Memory"), snapshot, embedder=embedder)
    assert rows[0].theme_id == snapshot.theme_id("Memory")
    assert not hasattr(rows[0], "outcome")

def test_provider_failure_never_falls_back_to_auto_merge(resolver):
    with pytest.raises(ResolverUnavailable):
        resolver.resolve(exposure("Artificial Intelligence Memory"), provider=failed_provider)
```

- [ ] **Step 2: Run tests and confirm missing modules**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_candidate_retrieval.py tests/unit/test_economic_theme_resolution.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement bounded retrieval with explicit reasons**

```python
@dataclass(frozen=True)
class ResolutionCandidate:
    theme_id: int
    lexical_score: float
    embedding_score: float | None
    compatible_facets: tuple[str, ...]
    conflicting_facets: tuple[str, ...]
    constituent_overlap: float | None
    retrieval_reasons: tuple[str, ...]
```

Retrieve exact aliases first, then lexical keys, compatible facets, fresh embeddings, relationships, and constituent overlap. Exclude stale embeddings whose semantic content hash differs from the active revision. Return at most 12 candidates in deterministic order.

- [ ] **Step 4: Implement constrained semantic resolution and post-validation**

The provider may emit only `equivalent|specialization|broader|related|distinct|ambiguous`, selected theme ID, differentiating facet, confidence, and rationale. Deterministic validation changes an incompatible `equivalent` result to `ambiguous`; it never upgrades another outcome to `equivalent`.

- [ ] **Step 5: Pin the contrast cases**

```python
@pytest.mark.parametrize(("left", "right", "allowed"), [
    ("AI Memory", "Memory", {"specialization"}),
    ("Artificial Intelligence Memory", "AI Memory", {"equivalent"}),
    ("AI-Powered Cybersecurity", "AI Security", {"distinct", "ambiguous"}),
    ("Crude Tankers", "Product Tankers", {"distinct", "related"}),
    ("Copper", "Copper Miners", {"specialization"}),
])
def test_contrast(left, right, allowed, resolver):
    assert resolver(left, right).outcome in allowed
```

- [ ] **Step 6: Run resolution tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_candidate_retrieval.py tests/unit/test_economic_theme_resolution.py tests/unit/test_economic_theme_contrast_cases.py -q`

Expected: PASS.

```bash
git add backend/app/services/economic_theme_candidate_retrieval.py backend/app/services/economic_theme_resolution.py backend/tests/unit/test_economic_theme_candidate_retrieval.py backend/tests/unit/test_economic_theme_resolution.py backend/tests/unit/test_economic_theme_contrast_cases.py
git commit -m "feat: resolve economic theme identity"
```

### Task 9: Orchestrate source processing and provisional identity publication

**Files:**
- Create: `backend/app/services/economic_taxonomy_processor.py`
- Test: `backend/tests/unit/test_economic_taxonomy_processor.py`
- Test: `backend/tests/integration/test_economic_provisional_publication_postgres.py`

**Interfaces:**
- Consumes: Tasks 3-8.
- Produces: `EconomicTaxonomyProcessor.process(source_revision, work_id, lease_token) -> ProcessingResult`.

- [ ] **Step 1: Write failing outcome tests**

```python
def test_ambiguous_candidate_creates_proposal_not_identity(processor, ambiguous_source):
    result = processor.process(ambiguous_source, work_id=1, lease_token="lease")
    assert result.status == "review_required"
    assert result.proposal_type == "ambiguous_identity"
    assert result.theme_ids == ()

def test_distinct_candidate_publishes_one_provisional_identity(processor, distinct_source):
    first = processor.process(distinct_source, work_id=1, lease_token="a")
    second = processor.process(distinct_source, work_id=1, lease_token="b")
    assert first.theme_ids == second.theme_ids
    assert first.published_version_id == second.published_version_id
```

- [ ] **Step 2: Run tests and confirm processor is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_processor.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement processing order and persisted audits**

```python
def process(self, source_revision: SourceRevision, work_id: int, lease_token: str) -> ProcessingResult:
    extracted = self.extractor.extract(source_revision)
    reviewed = self.claim_reviewer.review(extracted, source_revision)
    decisions = tuple(self.resolve(candidate) for candidate in reviewed.accepted)
    return self.persist_with_epoch_fence(work_id, lease_token, reviewed, decisions)
```

Persist every extracted candidate and review result before returning. `equivalent` reuses the existing identity; `specialization|broader|related|distinct` create a new provisional identity plus the supported relationship; `ambiguous` creates a proposal. Unsupported candidates remain audit rows and create no identity.

- [ ] **Step 4: Implement minimal-draft provisional publication**

Clone the active version, add one identity/revision/aliases/facets/relationship, recompute snapshot hash, lock authority, verify base version, candidate fingerprint, source revision, lease token, and epoch, then seal and publish. A stale base retries retrieval and resolution once against the new snapshot. The observation transaction starts only after successful publication.

- [ ] **Step 5: Run unit and concurrent publication tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_processor.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_provisional_publication_postgres.py -q`

Expected: concurrent identical distinct candidates create one identity; concurrent different candidates create two complete sequential versions.

- [ ] **Step 6: Commit the processor**

```bash
git add backend/app/services/economic_taxonomy_processor.py backend/tests/unit/test_economic_taxonomy_processor.py backend/tests/integration/test_economic_provisional_publication_postgres.py
git commit -m "feat: process economic taxonomy work"
```

### Task 10: Record primary and derived observations, lenses, constituents, and developments

**Files:**
- Create: `backend/app/services/economic_theme_observation_service.py`
- Modify: `backend/app/services/theme_development_service.py`
- Test: `backend/tests/unit/test_economic_theme_observations.py`
- Test: `backend/tests/unit/test_economic_theme_constituents.py`
- Test: `backend/tests/unit/test_economic_theme_development_links.py`

**Interfaces:**
- Consumes: resolved identities from Task 9, relationships from the active snapshot, SecurityMaster, and `ThemeDevelopmentObservation`.
- Produces: `record_claim()`, `derive_observations()`, `attach_lenses()`, `record_constituents()`, and `link_developments()`.

- [ ] **Step 1: Write failing source-family and root tests**

```python
def test_two_primary_claims_share_family_but_not_root(service, source):
    rows = service.record_claims(source, claims=(claim("AI Memory"), claim("Crude Tankers")))
    assert len({row.root_observation_id for row in rows if row.kind == "primary"}) == 2
    assert len({row.source_family_key for row in rows}) == 1

def test_derived_rows_do_not_become_new_roots(service, ai_hbm_claim):
    rows = service.record_claim(ai_hbm_claim)
    primary = next(row for row in rows if row.kind == "primary")
    assert all(row.root_observation_id == primary.id for row in rows)
```

- [ ] **Step 2: Run tests and confirm service is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_observations.py tests/unit/test_economic_theme_constituents.py tests/unit/test_economic_theme_development_links.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement primary, derived, and lens persistence**

Create one primary root per distinct claim fingerprint. Derive one semantic hop plus explicit compound/component paths. Store relationship assertion IDs and a derivation-policy version. Attach `technical`, `fundamental`, and `narrative` lens rows from `SourceRevision.lens_eligibility`, including the eligibility record or Social work ID that justified each lens.

- [ ] **Step 4: Resolve constituents to persistent stock identities**

```python
def resolve_security_id(db, claim: ConstituentClaim) -> int | None:
    identity = security_master_resolver.resolve_identity(
        symbol=claim.symbol, market=claim.market, exchange=claim.exchange
    )
    return db.scalar(select(StockUniverse.id).where(
        StockUniverse.symbol == identity.canonical_symbol,
        StockUniverse.market == identity.market,
    ))
```

Persist roles only for admitted evidence. Unresolved identities stay in the candidate audit. Price strength and ticker co-occurrence never establish exposure.

- [ ] **Step 5: Link rather than duplicate development history**

After `record_developments()` returns authoritative `ThemeDevelopmentObservation` rows, create `EconomicThemeDevelopmentLink` rows from the corresponding primary Economic Theme observation. Do not copy development facts into Economic Taxonomy tables.

- [ ] **Step 6: Run new and existing authority tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_observations.py tests/unit/test_economic_theme_constituents.py tests/unit/test_economic_theme_development_links.py tests/unit/test_theme_development.py tests/unit/test_theme_state_authorities.py -q`

Expected: PASS.

- [ ] **Step 7: Commit evidence persistence**

```bash
git add backend/app/services/economic_theme_observation_service.py backend/app/services/theme_development_service.py backend/tests/unit/test_economic_theme_observations.py backend/tests/unit/test_economic_theme_constituents.py backend/tests/unit/test_economic_theme_development_links.py
git commit -m "feat: preserve economic theme evidence provenance"
```

### Task 11: Publish lifecycle transitions and analytical-lens metrics

**Files:**
- Create: `backend/app/services/economic_theme_lifecycle_service.py`
- Create: `backend/app/services/economic_theme_metrics_service.py`
- Test: `backend/tests/unit/test_economic_theme_lifecycle.py`
- Test: `backend/tests/unit/test_economic_theme_metrics.py`

**Interfaces:**
- Consumes: observations and constituents from Task 10, Task 1 lifecycle policy, and Task 3 immutable publication.
- Produces: `evaluate_theme_lifecycle()`, `publish_lifecycle_transitions()`, and `calculate_lens_metrics()`.

- [ ] **Step 1: Write failing lifecycle threshold tests**

```python
def test_establishment_requires_independent_breadth(service, provisional_theme):
    evidence = lifecycle_evidence(source_families=2, dates=2, securities=2)
    assert service.evaluate(provisional_theme, evidence).target == "established"

def test_two_revisions_of_one_source_do_not_establish(service, provisional_theme):
    evidence = lifecycle_evidence(source_families=1, dates=2, securities=2)
    assert service.evaluate(provisional_theme, evidence).target is None

def test_dormancy_uses_direct_root_observations_only(service, established_theme):
    evidence = lifecycle_evidence(last_direct_root_days=31, last_derived_days=1)
    assert service.evaluate(established_theme, evidence).target == "dormant"
```

- [ ] **Step 2: Write failing metric-count tests**

```python
def test_metrics_keep_evidence_counts_separate(service, observations):
    row = service.calculate(observations, lens="technical")
    assert row.direct_observation_count == 2
    assert row.derived_observation_count == 3
    assert row.unique_root_count == 2
    assert row.unique_source_family_count == 1
```

- [ ] **Step 3: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py -q`

Expected: FAIL on import.

- [ ] **Step 4: Implement lifecycle publication**

Automatic establishment requires two source families, two observation dates, and two supported `StockUniverse` identities or an explicit reviewed breadth override. Thirty days without a direct root produces dormant; a new direct root produces reactivated. Each change appends `ThemeLifecycleEvent`, clones the active snapshot, updates the revision, and publishes with the expected epoch. Only a reviewed operation may retire.

- [ ] **Step 5: Implement metrics without semantic side effects**

Compute `technical_attention`, `fundamental_momentum`, `narrative_attention`, `emerging`, and `broad_confirmation` from observation lenses and existing pure calculations in `theme_discovery_service.py`. Key rows by `(economic_theme_id, lens, date, taxonomy_version_id)`. A VCP or breakout may change Technical Attention but cannot create a theme or facet.

- [ ] **Step 6: Run lifecycle, metric, and legacy regression tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py tests/unit/test_theme_lifecycle_policies.py tests/unit/test_theme_lifecycle_service.py -q`

Expected: PASS.

- [ ] **Step 7: Commit lifecycle and metrics**

```bash
git add backend/app/services/economic_theme_lifecycle_service.py backend/app/services/economic_theme_metrics_service.py backend/tests/unit/test_economic_theme_lifecycle.py backend/tests/unit/test_economic_theme_metrics.py
git commit -m "feat: publish economic theme lifecycle and lenses"
```

### Task 12: Add reviewed proposals and structural operations

**Files:**
- Create: `backend/app/services/economic_taxonomy_operations.py`
- Create: `backend/app/schemas/economic_taxonomy.py`
- Test: `backend/tests/unit/test_economic_taxonomy_operations.py`

**Interfaces:**
- Consumes: snapshot repository and proposal models.
- Produces: `preview(operation, base_version_id) -> ProposalPreview` and `apply(proposal_id, preview_hash, actor, reason) -> AppliedOperation`.

- [ ] **Step 1: Write failing review and staleness tests**

```python
def test_structural_apply_requires_actor_and_reason(service, proposal):
    with pytest.raises(ValueError, match="actor_and_reason_required"):
        service.apply(proposal.id, proposal.preview_hash, actor="", reason="")

def test_stale_preview_cannot_apply(service, proposal, publish_another_version):
    publish_another_version()
    with pytest.raises(StaleReviewPreview):
        service.apply(proposal.id, proposal.preview_hash, actor="admin", reason="reviewed")
```

- [ ] **Step 2: Run tests and confirm operations service is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_operations.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement preview hashes and exact operation types**

```python
STRUCTURAL_OPERATIONS = {
    "rename", "facet_correction", "relationship_correction",
    "merge_equivalent", "split", "mechanism_correction",
    "approve_dimension", "reject_dimension", "retire", "retain",
}
```

Preview contains base version, before/after canonical JSON, affected identity IDs, observation and migration counts, and SHA-256 preview hash. Apply verifies proposal status, base version, preview hash, actor, reason, and evidence references under the publication lock.

- [ ] **Step 4: Implement each operation as a complete new snapshot**

Merge keeps one stable identity, adds aliases and `LegacyThemeMapping` rows, and never stores an equivalence edge. Split creates reviewed identities and explicit observation/migration reassignment. Rename retains the prior display name as an alias unless the proposal rejects it. Dimension approval creates a governed dimension only in the result version. Retirement sets lifecycle state and timestamp; it does not delete history.

- [ ] **Step 5: Run operation tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_operations.py tests/unit/test_economic_taxonomy_authority.py -q`

Expected: PASS; the parent snapshot hash remains unchanged after every operation.

```bash
git add backend/app/services/economic_taxonomy_operations.py backend/app/schemas/economic_taxonomy.py backend/tests/unit/test_economic_taxonomy_operations.py
git commit -m "feat: govern economic taxonomy operations"
```

### Task 13: Integrate legacy content producers with shadow and dual modes

**Files:**
- Create: `backend/app/services/economic_taxonomy_runtime.py`
- Modify: `backend/app/tasks/theme_discovery_tasks.py`
- Modify: `backend/app/services/theme_extraction_service.py`
- Test: `backend/tests/unit/test_economic_taxonomy_legacy_adapter.py`
- Test: `backend/tests/integration/test_economic_taxonomy_dual_write.py`

**Interfaces:**
- Consumes: authority mode, source revisions, work repository, and outbox.
- Produces: `EconomicTaxonomyRuntime.after_legacy_content_commit()` and `EconomicTaxonomyRuntime.write_economic_then_compatibility()`.

- [ ] **Step 1: Write failing mode-matrix tests**

```python
@pytest.mark.parametrize(("mode", "legacy", "economic", "required"), [
    ("legacy", True, False, False),
    ("shadow", True, True, False),
    ("dual", True, True, True),
    ("economic", True, True, True),
])
def test_content_write_matrix(mode, legacy, economic, required, runtime):
    result = runtime.route_content_write(mode=mode)
    assert result.write_legacy is legacy
    assert result.write_economic is economic
    assert result.economic_completion_required is required
```

- [ ] **Step 2: Run tests and confirm runtime adapter is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_legacy_adapter.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement shadow enqueue and reconciliation**

After a successful legacy extraction commit, shadow mode idempotently enqueues `EconomicTaxonomyWork`; failure is logged with source revision and does not change the legacy result. Add `reconcile_shadow_content(limit=500)` to scan admitted `ContentItem` revisions without matching work and repair missed enqueues.

- [ ] **Step 4: Implement dual and economic outbox semantics**

In dual mode, insert a required `target_representation='economic'` outbox event in the same transaction as the legacy result. In economic mode, commit the Economic Taxonomy result first and insert `target_representation='legacy'` compatibility work in that transaction. `event_key` is SHA-256 of target, source kind, source ID, revision, and authority epoch. Deliveries are idempotent and terminal failures block cutover health.

- [ ] **Step 5: Run adapter, legacy extraction, and transaction tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_legacy_adapter.py tests/unit/test_theme_reprocessing.py tests/unit/test_theme_pipeline_state_service.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_dual_write.py -q`

Expected: legacy mode creates no economic work; shadow failure preserves legacy success; dual mode leaves a durable outbox event; economic mode leaves a durable legacy compatibility event.

- [ ] **Step 6: Commit the legacy producer adapter**

```bash
git add backend/app/services/economic_taxonomy_runtime.py backend/app/tasks/theme_discovery_tasks.py backend/app/services/theme_extraction_service.py backend/tests/unit/test_economic_taxonomy_legacy_adapter.py backend/tests/integration/test_economic_taxonomy_dual_write.py
git commit -m "feat: adapt legacy theme producers to taxonomy modes"
```

### Task 14: Integrate the Social producer and preserve administrator authority

**Files:**
- Modify: `backend/app/infra/db/models/social_analysis.py`
- Modify: `backend/app/services/social_theme_projection_service.py`
- Modify: `backend/app/services/social_theme_market_service.py`
- Create: `backend/alembic/versions/20260921_0048_economic_taxonomy_social_adapter.py`
- Test: `backend/tests/unit/test_economic_taxonomy_social_adapter.py`
- Test: `backend/tests/integration/test_economic_taxonomy_social_modes.py`
- Modify: `backend/tests/integration/test_social_theme_projection.py`

**Interfaces:**
- Consumes: saved `SocialExtractionWork`, source revision builder, runtime adapter, and existing Social decision history.
- Produces: nullable `SocialThemeAssociation.economic_theme_id` and mode-aware Social projection.

- [ ] **Step 1: Write failing Social state-preservation tests**

```python
def test_dual_projection_preserves_admin_decision_and_evidence(service, accepted_association):
    before = (accepted_association.state, accepted_association.decision_owner,
              tuple(accepted_association.evidence_work_ids))
    service.project_saved_work(accepted_association.evidence_work_ids[0])
    assert (accepted_association.state, accepted_association.decision_owner,
            tuple(accepted_association.evidence_work_ids)) == before
    assert accepted_association.economic_theme_id is not None
```

- [ ] **Step 2: Run tests and confirm the new column is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_social_adapter.py -q`

Expected: FAIL because `economic_theme_id` is absent.

- [ ] **Step 3: Add the nullable mapping and migration constraints**

Add `economic_theme_id` as a `RESTRICT` foreign key and unique `(economic_theme_id, market, canonical_symbol)` constraint. Retain non-null `theme_cluster_id`, its uniqueness, `state`, `decision_owner`, `evidence_work_ids`, version, and append-only decisions for rollback compatibility.

- [ ] **Step 4: Route saved Social claims through the common processor**

Build a `social_work` source revision from the saved input/result, attach the `narrative` lens, and invoke the same retrieval/resolution path as content. Shadow continues legacy projection and best-effort Economic Taxonomy enqueue. Dual requires the economic outbox event. Economic mode writes the global association and emits legacy compatibility work.

- [ ] **Step 5: Run Social migration and mode tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_social_adapter.py tests/integration/test_social_theme_projection.py tests/unit/test_theme_social_source_admin_boundary.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_social_modes.py -q`

Expected: Social administrator decisions are byte-for-byte stable across all modes; accepted associations have both IDs after dual convergence.

- [ ] **Step 6: Commit Social integration and adapter migration**

```bash
git add backend/app/infra/db/models/social_analysis.py backend/app/services/social_theme_projection_service.py backend/app/services/social_theme_market_service.py backend/alembic/versions/20260921_0048_economic_taxonomy_social_adapter.py backend/tests/unit/test_economic_taxonomy_social_adapter.py backend/tests/integration/test_economic_taxonomy_social_modes.py backend/tests/integration/test_social_theme_projection.py
git commit -m "feat: integrate social economic taxonomy writes"
```

### Task 15: Expose global APIs and authority-versioned UI snapshots

**Files:**
- Create: `backend/app/schemas/economic_theme.py`
- Create: `backend/app/api/v1/economic_themes.py`
- Create: `backend/app/api/v1/economic_taxonomy.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/models/ui_view_snapshot.py`
- Modify: `backend/app/schemas/ui_view_snapshot.py`
- Modify: `backend/app/services/ui_snapshot_service.py`
- Create: `backend/alembic/versions/20260921_0049_economic_taxonomy_ui_snapshot.py`
- Test: `backend/tests/unit/test_economic_theme_api.py`
- Test: `backend/tests/unit/test_economic_taxonomy_api.py`
- Test: `backend/tests/unit/test_economic_theme_ui_snapshot.py`

**Interfaces:**
- Consumes: active snapshot, observations, metrics, proposals, and operations.
- Produces: `/api/v1/economic-themes`, `/api/v1/economic-taxonomy`, and theme snapshot envelopes carrying `authority_epoch` and `taxonomy_version_id`.

- [ ] **Step 1: Write failing API and cache-coherence tests**

```python
def test_theme_list_uses_one_identity_across_lenses(client, seeded_taxonomy):
    technical = client.get("/api/v1/economic-themes", params={"lens": "technical"}).json()
    fundamental = client.get("/api/v1/economic-themes", params={"lens": "fundamental"}).json()
    assert technical["items"][0]["semantic_key"] == fundamental["items"][0]["semantic_key"]

def test_snapshot_rejects_mismatched_epoch(client, snapshot_with_old_epoch):
    response = client.get("/api/v1/economic-themes/bootstrap")
    assert response.status_code == 409
    assert response.json()["detail"] == "theme_snapshot_authority_mismatch"
```

- [ ] **Step 2: Run API tests and confirm routes are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_api.py tests/unit/test_economic_taxonomy_api.py tests/unit/test_economic_theme_ui_snapshot.py -q`

Expected: FAIL with route/import errors.

- [ ] **Step 3: Implement read and review contracts**

The list accepts `lens`, lifecycle, source type, date, offset, and limit. Detail returns stable identity, active revision, facets, relationships, direct and derived evidence, development links, constituent roles, and lens history. Review endpoints expose proposal queue, preview, apply, migration dispositions, and authority health; every mutating route uses `require_admin`.

- [ ] **Step 4: Version theme UI snapshots**

Add nullable `authority_epoch` and `taxonomy_version_id` to `UIViewSnapshot`; non-theme views leave them null. Economic theme snapshots require both values. Build the target snapshot before publication. The cutover transaction updates `taxonomy_authority` and the relevant `UIViewSnapshotPointer` rows together; retrieval rejects a pointer whose epoch or version differs from authority.

- [ ] **Step 5: Inject snapshot publication failure**

Add a test hook that raises after target snapshot creation but before pointer switch. Assert the old pointer and old authority remain active and the target snapshot remains an unreferenced audit artifact.

- [ ] **Step 6: Run API and existing snapshot regressions**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_api.py tests/unit/test_economic_taxonomy_api.py tests/unit/test_economic_theme_ui_snapshot.py tests/unit/test_ui_snapshot_service.py tests/unit/test_theme_endpoints_contract.py -q`

Expected: PASS.

- [ ] **Step 7: Commit APIs and versioned snapshots**

```bash
git add backend/app/schemas/economic_theme.py backend/app/schemas/economic_taxonomy.py backend/app/api/v1/economic_themes.py backend/app/api/v1/economic_taxonomy.py backend/app/api/v1/router.py backend/app/models/ui_view_snapshot.py backend/app/schemas/ui_view_snapshot.py backend/app/services/ui_snapshot_service.py backend/alembic/versions/20260921_0049_economic_taxonomy_ui_snapshot.py backend/tests/unit/test_economic_theme_api.py backend/tests/unit/test_economic_taxonomy_api.py backend/tests/unit/test_economic_theme_ui_snapshot.py
git commit -m "feat: expose versioned economic theme APIs"
```

### Task 16: Build reviewed legacy migration and the contrast benchmark

**Files:**
- Create: `backend/app/services/economic_taxonomy_migration.py`
- Create: `backend/scripts/build_economic_taxonomy_migration.py`
- Create: `backend/scripts/evaluate_economic_taxonomy.py`
- Create: `backend/tests/fixtures/economic_taxonomy/contrast_cases.json`
- Test: `backend/tests/unit/test_economic_taxonomy_migration.py`
- Test: `backend/tests/unit/test_economic_taxonomy_benchmark.py`
- Test: `backend/tests/integration/test_economic_taxonomy_migration_run.py`

**Interfaces:**
- Consumes: active legacy themes, aliases, mentions, constituents, Social associations, developments, and the shadow Economic Taxonomy.
- Produces: `build_migration_run()`, `review_disposition()`, `materialize_legacy_mappings()`, and `evaluate_contrast_cases()`.

- [ ] **Step 1: Write failing completeness and no-cutover tests**

```python
def test_every_active_legacy_theme_has_one_disposition(service, active_legacy_ids):
    run = service.build_migration_run()
    assert {row.legacy_theme_cluster_id for row in run.dispositions} == set(active_legacy_ids)
    assert len(run.dispositions) == len(active_legacy_ids)

def test_build_does_not_change_authority(service, authority):
    before = authority.state()
    service.build_migration_run()
    assert authority.state() == before
```

- [ ] **Step 2: Run migration tests and confirm service is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_migration.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement exact dispositions and high-watermarks**

```python
MIGRATION_DISPOSITIONS = {
    "retain_as_global_theme", "equivalent_to", "split_required",
    "not_a_theme", "insufficient_evidence",
}
```

Capture high-watermarks for `content_items`, `social_extraction_work`, `theme_development_work`, and taxonomy operations. Persist one disposition per active legacy identity with proposed theme IDs, before/after JSON, evidence, reason, and review state. Materialize `LegacyThemeMapping` only for reviewed retain/equivalent results.

- [ ] **Step 4: Create the version-bound contrast fixture**

The JSON fixture contains positive, negative, ambiguous, and insufficient-specificity cases for:

```text
Memory / HBM / AI Memory / AI HBM
AI-Powered Cybersecurity / AI Security
petroleum refining / metals refining
Crude Tankers / Product Tankers
Copper / Copper Miners / downstream copper consumers
VCP / breakout / relative-strength leadership pseudo-themes
Rate-Cut Beneficiaries
```

Each case specifies source text, expected accepted themes, forbidden themes, allowed resolution outcomes, and expected error code. The evaluator records taxonomy content hash plus extraction, resolver, naming, and derivation policy versions.

- [ ] **Step 5: Implement separate benchmark error classes**

Report `false_equivalence`, `false_specialization`, `unsupported_compound`, `over_specific`, `missed_valid_theme`, and `pseudo_theme_creation` counts. Exit non-zero if any configured threshold regresses from the checked-in baseline.

- [ ] **Step 6: Run migration and benchmark tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_migration.py tests/unit/test_economic_taxonomy_benchmark.py tests/integration/test_economic_taxonomy_migration_run.py -q`

Expected: PASS; dry run changes no authority or UI pointer.

- [ ] **Step 7: Commit migration and benchmark tools**

```bash
git add backend/app/services/economic_taxonomy_migration.py backend/scripts/build_economic_taxonomy_migration.py backend/scripts/evaluate_economic_taxonomy.py backend/tests/fixtures/economic_taxonomy/contrast_cases.json backend/tests/unit/test_economic_taxonomy_migration.py backend/tests/unit/test_economic_taxonomy_benchmark.py backend/tests/integration/test_economic_taxonomy_migration_run.py
git commit -m "feat: build reviewed taxonomy migration"
```

### Task 17: Implement delta replay, atomic cutover, and rollback

**Files:**
- Create: `backend/app/services/economic_taxonomy_cutover.py`
- Create: `backend/scripts/publish_economic_taxonomy.py`
- Test: `backend/tests/unit/test_economic_taxonomy_cutover.py`
- Test: `backend/tests/integration/test_economic_taxonomy_cutover_postgres.py`

**Interfaces:**
- Consumes: migration run, outbox health, authority repository, UI target snapshots, and benchmark report.
- Produces: `prepare_cutover()`, `replay_delta()`, `publish_cutover()`, and `rollback_cutover()`.

- [ ] **Step 1: Write failing readiness and rollback tests**

```python
def test_prepare_rejects_pending_outbox(cutover, migration_run):
    with pytest.raises(PublicationValidationFailed, match="outbox_not_drained"):
        cutover.prepare_cutover(migration_run.id)

def test_failure_before_pointer_switch_keeps_legacy_authority(cutover, fault_injector):
    fault_injector.raise_at("before_authority_switch")
    with pytest.raises(RuntimeError):
        cutover.publish_cutover()
    assert cutover.authority().mode == "dual"
    assert cutover.ui_pointer().authority_epoch == cutover.authority().authority_epoch
```

- [ ] **Step 2: Run cutover tests and confirm service is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_cutover.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement readiness gates**

`prepare_cutover()` requires: authority mode `dual`; reviewed migration dispositions; complete legacy mappings; zero pending, leased, or terminal outbox events; no active old-epoch work; passing version-bound benchmark; built target UI snapshots; and matching source high-watermarks.

- [ ] **Step 4: Implement final replay and fenced switch**

Under advisory lock `78124017`, record fresh high-watermarks, replay every content, Social, development, and structural revision after the migration snapshot, drain required outbox work, verify high-watermarks again, lock authority, and atomically switch mode to `economic`, active version, epoch, and theme UI pointers. A changed high-watermark aborts before the switch.

- [ ] **Step 5: Implement rollback without deleting artifacts**

`rollback_cutover()` verifies legacy compatibility outbox health, builds legacy UI snapshots, then atomically switches mode to `legacy` and matching pointers while incrementing epoch. It retains Economic Taxonomy versions, candidates, observations, migration runs, and mappings.

- [ ] **Step 6: Run PostgreSQL race and failure tests**

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_cutover_postgres.py -q`

Expected: a source arriving during replay is included or publication aborts; an old worker cannot commit after the epoch change; every injected failure leaves one coherent authority and pointer set.

- [ ] **Step 7: Run unit tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_cutover.py -q`

Expected: PASS.

```bash
git add backend/app/services/economic_taxonomy_cutover.py backend/scripts/publish_economic_taxonomy.py backend/tests/unit/test_economic_taxonomy_cutover.py backend/tests/integration/test_economic_taxonomy_cutover_postgres.py
git commit -m "feat: add atomic taxonomy cutover and rollback"
```

### Task 18: Schedule shadow processing, outbox delivery, lifecycle, and metrics

**Files:**
- Create: `backend/app/tasks/economic_taxonomy_tasks.py`
- Modify: `backend/app/celery_app.py`
- Modify: `backend/app/tasks/theme_discovery_tasks.py`
- Test: `backend/tests/unit/test_economic_taxonomy_tasks.py`
- Test: `backend/tests/unit/test_economic_taxonomy_celery_contract.py`

**Interfaces:**
- Consumes: work processor, runtime reconciliation, outbox, lifecycle, and metrics services.
- Produces: Celery tasks `discover_economic_taxonomy_work`, `process_economic_taxonomy_work`, `deliver_taxonomy_outbox`, `apply_economic_theme_lifecycle`, and `calculate_economic_theme_metrics`.

- [ ] **Step 1: Write failing task-mode and retry tests**

```python
def test_legacy_mode_discovery_is_noop(task, authority):
    authority.mode = "legacy"
    assert task.run(limit=50) == {"status": "skipped", "reason": "legacy_mode"}

def test_provider_quota_keeps_work_retryable(task, quota_failure):
    result = task.run(limit=1)
    assert result["failed_retryable"] == 1
    assert result["failed_terminal"] == 0
```

- [ ] **Step 2: Run tests and confirm tasks are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_taxonomy_celery_contract.py -q`

Expected: FAIL on import or missing Celery registration.

- [ ] **Step 3: Implement bounded task entry points**

Every task opens short database transactions, processes bounded batches, reports counts by stable outcome, and does no work in legacy mode. Work and outbox tasks use leases from Task 6; lifecycle and metrics use the active snapshot captured at task start and abort on epoch change.

- [ ] **Step 4: Register queues and schedules**

Include `app.tasks.economic_taxonomy_tasks` in Celery. Route source processing and outbox delivery to the existing `celery` queue. Schedule discovery every 5 minutes, outbox delivery every minute, lifecycle daily at 02:10 in configured Celery timezone, and metrics after existing theme metric calculation. Do not add a new worker process.

- [ ] **Step 5: Run task and existing worker-contract tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_taxonomy_celery_contract.py tests/unit/test_theme_discovery_ingestion_tasks.py tests/unit/test_social_worker_compose_contract.py -q`

Expected: PASS.

- [ ] **Step 6: Commit scheduled operation**

```bash
git add backend/app/tasks/economic_taxonomy_tasks.py backend/app/celery_app.py backend/app/tasks/theme_discovery_tasks.py backend/tests/unit/test_economic_taxonomy_tasks.py backend/tests/unit/test_economic_taxonomy_celery_contract.py
git commit -m "feat: schedule economic taxonomy processing"
```

### Task 19: Add the global theme and taxonomy review experience

**Files:**
- Create: `frontend/src/api/economicThemes.js`
- Create: `frontend/src/api/economicThemes.test.js`
- Create: `frontend/src/features/themes/components/EconomicThemeDetailModal.jsx`
- Create: `frontend/src/features/themes/components/EconomicThemeDetailModal.test.jsx`
- Create: `frontend/src/components/Themes/EconomicTaxonomyReview.jsx`
- Create: `frontend/src/components/Themes/EconomicTaxonomyReview.test.jsx`
- Modify: `frontend/src/features/themes/pages/ThemesPageContainer.jsx`
- Modify: `frontend/src/pages/ThemesPage.test.jsx`

**Interfaces:**
- Consumes: Task 15 APIs and the runtime authority response.
- Produces: one global list with lens selection, stable identity details, and reviewed migration/operation workflows.

- [ ] **Step 1: Write failing API adapter and stable-ID tests**

```javascript
it('keeps one identity while changing lenses', async () => {
  const technical = await getEconomicThemes({ lens: 'technical' });
  const fundamental = await getEconomicThemes({ lens: 'fundamental' });
  expect(technical.items[0].semanticKey).toBe(fundamental.items[0].semanticKey);
});
```

- [ ] **Step 2: Write failing review-workflow tests**

```javascript
it('requires reviewer reason and rejects stale previews', async () => {
  render(<EconomicTaxonomyReview proposal={proposal} />);
  await user.click(screen.getByRole('button', { name: /apply/i }));
  expect(screen.getByText(/reason is required/i)).toBeVisible();
  server.use(stalePreviewResponse());
  await submitReason('mechanism verified');
  expect(screen.getByText(/preview changed; refresh before applying/i)).toBeVisible();
});
```

- [ ] **Step 3: Run frontend tests and confirm modules are absent**

Run: `cd frontend && npm run test:run -- src/api/economicThemes.test.js src/features/themes/components/EconomicThemeDetailModal.test.jsx src/components/Themes/EconomicTaxonomyReview.test.jsx`

Expected: FAIL on imports.

- [ ] **Step 4: Implement the global list and detail view**

Replace pipeline identity tabs with lens choices: Technical Attention, Fundamental Momentum, Narrative Attention, Emerging, and Broad Confirmation. Detail renders definition, mechanism, defining facets, aliases, narrower/broader/related identities, direct/derived evidence counts, source-family count, developments, constituents, and roles. Render VCP and breakout under signals, never as theme names.

- [ ] **Step 5: Implement migration and structural review**

Render queues for `split_required`, `not_a_theme`, `insufficient_evidence`, `ambiguous_identity`, `candidate_dimension`, merge, mechanism correction, and retirement. Show before/after JSON as labeled fields, affected identities and observations, evidence links, preview hash, reviewer, and required reason. Refresh on `stale_review_preview`.

- [ ] **Step 6: Keep legacy UI selectable until economic authority**

Read authority state on page load. In legacy, shadow, and dual modes render the existing production page plus an admin-only Economic Taxonomy preview. In economic mode render the global page. Do not remove legacy components in this task.

- [ ] **Step 7: Run focused tests and production build**

Run: `cd frontend && npm run test:run -- src/api/economicThemes.test.js src/features/themes/components/EconomicThemeDetailModal.test.jsx src/components/Themes/EconomicTaxonomyReview.test.jsx src/pages/ThemesPage.test.jsx`

Run: `cd frontend && npm run build`

Expected: tests PASS and Vite build exits 0.

- [ ] **Step 8: Commit the product experience**

```bash
git add frontend/src/api/economicThemes.js frontend/src/api/economicThemes.test.js frontend/src/features/themes/components/EconomicThemeDetailModal.jsx frontend/src/features/themes/components/EconomicThemeDetailModal.test.jsx frontend/src/components/Themes/EconomicTaxonomyReview.jsx frontend/src/components/Themes/EconomicTaxonomyReview.test.jsx frontend/src/features/themes/pages/ThemesPageContainer.jsx frontend/src/pages/ThemesPage.test.jsx
git commit -m "feat: add global economic theme experience"
```

### Task 20: Cut downstream readers over through one authority-aware facade

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
- Test: `backend/tests/unit/test_economic_theme_read_service.py`
- Test: `backend/tests/unit/test_economic_theme_consumer_cutover.py`

**Interfaces:**
- Consumes: authority state, global APIs, legacy models, and `LegacyThemeMapping`.
- Produces: `EconomicThemeReadService.list_themes()`, `get_theme()`, `themes_for_security()`, `latest_metrics()`, and `resolve_name()`.

- [ ] **Step 1: Write failing facade mode tests**

```python
@pytest.mark.parametrize(("mode", "expected_source"), [
    ("legacy", "legacy"), ("shadow", "legacy"), ("dual", "legacy"), ("economic", "economic"),
])
def test_read_source_follows_authority(mode, expected_source, service):
    assert service.for_mode(mode).source_name == expected_source
```

- [ ] **Step 2: Inventory and pin current consumers**

Run: `rg -l 'ThemeCluster|ThemeMention|ThemeMetrics|ThemeConstituent|parent_cluster_id|is_l1|taxonomy_level' backend/app --glob '*.py'`

Add assertions for themes rankings/detail/history/mentions, stock themes, digest themes, Social confirmation, Social market baskets, MCP theme detail/rankings, and UI snapshots. The test fails if a production consumer bypasses `EconomicThemeReadService` while mode is economic.

- [ ] **Step 3: Implement the facade and legacy adapter**

Legacy, shadow, and dual implementations preserve existing responses. Economic implementation reads the active snapshot, observations, constituents, and lens metrics. When a legacy response field is unavoidable, translate using reviewed `LegacyThemeMapping`; never infer a mapping by display name.

- [ ] **Step 4: Replace production reads and retire L1/L2 authority**

Route listed consumers through the facade. In economic mode, `/themes/taxonomy/l1` returns `410 Gone` with `economic_taxonomy_replaces_l1_l2`; relationships are served by the Economic Theme endpoints. Keep legacy mutation endpoints admin-disabled unless authority is legacy or rollback is active.

- [ ] **Step 5: Run consumer and legacy compatibility tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_read_service.py tests/unit/test_economic_theme_consumer_cutover.py tests/unit/test_theme_endpoints_contract.py tests/unit/test_theme_content_browser_api.py tests/unit/test_ui_snapshot_service.py -q`

Expected: PASS in all four modes; economic-mode tests issue no `theme_clusters` semantic read outside the facade.

- [ ] **Step 6: Commit reader cutover**

```bash
git add backend/app/services/economic_theme_read_service.py backend/app/api/v1/themes_queries.py backend/app/api/v1/themes_taxonomy.py backend/app/api/v1/stocks.py backend/app/services/digest_service.py backend/app/services/social_confirmation_reader.py backend/app/services/social_theme_market_service.py backend/app/interfaces/mcp/market_copilot.py backend/app/services/ui_snapshot_service.py backend/tests/unit/test_economic_theme_read_service.py backend/tests/unit/test_economic_theme_consumer_cutover.py
git commit -m "refactor: route theme reads through taxonomy authority"
```

### Task 21: Enforce release gates and write the operator runbook

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `docs/runbooks/economic-taxonomy-cutover.md`
- Modify: `docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md`
- Test: `backend/tests/unit/test_economic_taxonomy_runbook.py`

**Interfaces:**
- Consumes: every prior task.
- Produces: non-skippable PostgreSQL CI coverage and exact operator procedures.

- [ ] **Step 1: Write a failing runbook contract test**

```python
def test_runbook_names_every_transition_and_gate():
    text = RUNBOOK.read_text()
    for phrase in (
        "legacy -> shadow", "shadow -> dual", "dual -> economic",
        "delta replay", "outbox drain", "authority epoch",
        "benchmark", "rollback", "verify UI snapshot pointers",
    ):
        assert phrase in text
```

- [ ] **Step 2: Add the non-skippable PostgreSQL gate**

Add a CI step under the existing PostgreSQL-backed `backend` job:

```yaml
- name: Economic taxonomy authority and cutover concurrency
  env:
    DATABASE_URL: postgresql://ci:ci@localhost:5432/ci
    STOCKSCANNER_TEST_ALLOW_POSTGRES: "1"
  run: >-
    cd backend && python -m pytest -q
    tests/integration/test_economic_taxonomy_authority_postgres.py
    tests/integration/test_economic_taxonomy_work_postgres.py
    tests/integration/test_economic_provisional_publication_postgres.py
    tests/integration/test_economic_taxonomy_social_modes.py
    tests/integration/test_economic_taxonomy_cutover_postgres.py
```

- [ ] **Step 3: Write exact runbook commands and stop conditions**

Document migration upgrade, facet seed, shadow transition, shadow health query, benchmark command, migration build, disposition review, dual transition, outbox drain, target snapshot build, cutover dry run, publish, verification queries, and rollback. Every command records migration-run ID, taxonomy version, authority epoch, source high-watermarks, content hash, and benchmark report path. Stop on unresolved split/retirement/dimension proposals, failed benchmark thresholds, pending outbox, stale UI pointers, or changed high-watermarks.

- [ ] **Step 4: Run focused backend verification**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_economic_taxonomy_policy.py tests/unit/test_economic_taxonomy_models.py tests/unit/test_economic_taxonomy_authority.py tests/unit/test_economic_taxonomy_runtime_models.py tests/unit/test_economic_source_revision.py tests/unit/test_economic_taxonomy_work_repo.py tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py tests/unit/test_economic_theme_candidate_retrieval.py tests/unit/test_economic_theme_resolution.py tests/unit/test_economic_taxonomy_processor.py tests/unit/test_economic_theme_observations.py tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py tests/unit/test_economic_taxonomy_operations.py tests/unit/test_economic_taxonomy_legacy_adapter.py tests/unit/test_economic_taxonomy_social_adapter.py tests/unit/test_economic_theme_api.py tests/unit/test_economic_taxonomy_api.py tests/unit/test_economic_theme_ui_snapshot.py tests/unit/test_economic_taxonomy_migration.py tests/unit/test_economic_taxonomy_benchmark.py tests/unit/test_economic_taxonomy_cutover.py tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_theme_read_service.py tests/unit/test_economic_theme_consumer_cutover.py tests/unit/test_economic_taxonomy_runbook.py`

Expected: all listed tests PASS with zero skips.

- [ ] **Step 5: Run existing theme, Social, migration, and authority regressions**

Run: `cd backend && ./venv/bin/pytest -q tests/unit/test_theme_claim_review.py tests/unit/test_theme_state_authorities.py tests/unit/test_theme_identity_invariants_ci.py tests/unit/test_theme_pipeline_state_service.py tests/unit/test_theme_development.py tests/unit/test_social_signals_api.py tests/integration/test_social_theme_projection.py tests/integration/test_theme_state_authorities_migration.py`

Expected: PASS; PostgreSQL-marked tests run with the CI environment rather than skip.

- [ ] **Step 6: Run frontend verification**

Run: `cd frontend && npm run test:run`

Run: `cd frontend && npm run build`

Expected: full Vitest suite PASS and production build exits 0.

- [ ] **Step 7: Rehearse migration and rollback in disposable PostgreSQL**

Run the exact runbook sequence against a disposable database containing representative legacy, Social, development, and UI snapshot data. Record the old and new authority rows, snapshot pointers, content hashes, outbox counts, benchmark result, and post-rollback equivalence. Expected: economic publication and rollback both preserve one coherent authority and no accepted Social decision changes.

- [ ] **Step 8: Confirm documentation links and commit release gates**

Verify the approved spec links to this plan and the runbook links back to both documents.

```bash
git add .github/workflows/ci.yml docs/runbooks/economic-taxonomy-cutover.md docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md backend/tests/unit/test_economic_taxonomy_runbook.py
git commit -m "docs: gate economic taxonomy cutover"
```

---

## Dependency Order

1. Tasks 1-4 establish contracts, immutable semantics, authority, and governed naming.
2. Tasks 5-9 establish durable source processing and global identity resolution.
3. Tasks 10-12 establish evidence truth, analytical views, lifecycle, and reviewed restructuring.
4. Tasks 13-15 integrate all producers and expose shadow validation without changing production reads.
5. Tasks 16-18 prove migration quality, dual-write convergence, atomic cutover, rollback, and scheduled operation.
6. Tasks 19-20 switch the product and downstream consumers only after the dual-mode gates pass.
7. Task 21 is the production release gate and cannot be waived by passing SQLite tests.

Do not enter `dual` before Tasks 13-16 pass. Do not enter `economic` before Tasks 17-18 pass in PostgreSQL and the benchmark is reviewed. Do not remove legacy writes or tables in this project.

## Recommended Execution

Use **subagent-driven development**. The twenty-one tasks cross immutable schema design, concurrent publication, LLM semantics, two producer families, migration, UI snapshots, APIs, frontend behavior, and rollback; each task has a reviewable boundary, while an identity or cutover defect can silently corrupt historical meaning. Require a fresh review after every task and a whole-branch review before the Task 21 rehearsal.
