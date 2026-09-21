# Open Multi-Dimensional Economic Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pipeline-scoped and L1/L2 theme identity with a global Economic Theme taxonomy whose semantic snapshots, accepted evidence interpretations, projections, metrics, and reader pointers are published coherently and can be rolled back safely.

**Architecture:** Build an immutable processing taxonomy beside the legacy Theme Catalog, but expose it only through immutable serving generations. Route-independent source lineages and frozen evidence packets feed stable processing requests, reusable extraction/review artifacts, and exact immutable classification attempts. Each generation pins one accepted attempt plus every eligibility, decision, development, mapping, override, metrics-policy, and compatibility revision needed to reproduce the product. One publication coordinator captures a bounded cutoff, prepares sealed artifacts outside the final lock, then atomically switches taxonomy, interpretation, metrics, and reader pointers under a short producer fence.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, PostgreSQL 16, SQLite unit/migration harness, Celery, existing LLM/embedding and Social-budget services, React, MUI, TanStack Query, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md`

**ADR:** `docs/adr/0005-economic-taxonomy-snapshots-and-interpretations.md`

**Status:** production-ready. Production cutover remains gated by Task 19's exact PostgreSQL checks and the operator procedure in `docs/runbooks/economic-taxonomy-cutover.md`; the completed disposable-database exercise is recorded in `docs/runbooks/artifacts/economic-taxonomy-rehearsal-2026-09-21.md`.

## Global Constraints

- `EconomicTheme.semantic_key` is an opaque UUID assigned once; mutable semantic fields live only in version-owned rows.
- Taxonomy versions have only `draft|sealed`; a sealed version cannot reopen, mutate, or receive moved rows.
- `taxonomy_authority.processing_taxonomy_version_id` is not a reader pointer. Readers use only `serving_generation_id`.
- A serving generation binds one sealed taxonomy, interpretation set, complete generation-input manifest, metrics revision, UI/API snapshot bundle, and reader-capability manifest.
- Source-family, source-lineage, evidence-packet, processing-request, classification-attempt, and lens-eligibility identities are separate.
- Evidence revision ordinal is deterministic admission/audit order, not proof of source freshness. Effective precedence requires authoritative provider revision metadata, an explicit supersession/equivalence relation, or review; unresolved late captures cannot displace the accepted packet.
- Successful extraction and claim-review results are reusable, but provider attempts are append-only. Retryable or uncertain failures never become permanent reusable-result cache hits; each permitted retry has a new attempt and budget record.
- Successful empty classification is authoritative when selected; failed, partial, review-only, or superseded attempts never replace the last accepted attempt.
- Similarity retrieves candidates but never authorizes equivalence.
- Proposed-candidate relationship outcomes are directional: proposed `Copper` relative to existing `Copper Miners` is `broader`.
- Migration disposition is one-per-legacy-identity, but destinations and claim allocations are zero-to-many.
- Existing `SocialThemeAssociation` rows and their decisions are preserved. Global Social membership is a separate projection.
- A global Social association has one stable identity per `(economic_theme_id, security_id)` and append-only numbered revisions; generations pin revisions, not a mutable pair row.
- Every content, Social, development, structural, compatibility, and migration writer acquires the shared taxonomy fence and rechecks authority before commit.
- The coordinator captures a committed cutoff under a short exclusive fence, prepares outside the lock, and publishes if the parent generation, semantic invalidation revision, and frozen manifest remain valid. Ordinary work committed after the cutoff waits for the next generation and does not invalidate the prepared one.
- The final publisher performs no provider call, replay, outbox drain, or worker wait while holding the exclusive fence.
- Logical outbox event identity excludes authority epoch and includes a monotonic per-lineage projection revision. Payloads replace one lineage's complete target contribution, targets reject older revisions, and mirror-origin events never recurse.
- A staged compatibility event becomes durably deliverable from the successful publication event committed with its generation; post-commit queue notification is only an optimization, and abandoned-generation events are never eligible.
- Evidence-channel eligibility does not itself create a technical, fundamental, or narrative metric observation.
- `fundamental_attention` is an unsigned attention view; directional fundamental scoring is explicitly deferred.
- Provisional-to-established requires the evidence thresholds plus cross-security breadth: two accepted securities or an authenticated reviewed breadth assertion.
- `reactivated` behaves like `established` for the 90-day inactivity transition and may become dormant again while retaining reactivation history.
- Observation-only classification against existing identities leaves `output_taxonomy_version_id` null and does not advance the processing head.
- Semantic writes use an authenticated `AdminPrincipal`; automatic routine publication uses only `system:economic-taxonomy-refresh`.
- After economic cutover, routine changes are automatically coalesced and published at most once per five-minute window; review-required structural changes remain held.
- `security_id` means `stock_universe.id`; ADR-0003 remains unchanged for StockUniverse history.
- Economic mode is impossible until reader capability, frontend contract, compatibility, PostgreSQL concurrency, and zero-skip release gates all pass.

## Review Focus

1. Crash after creating a provisional processing snapshot: retry must yield one identity, one accepted attempt, one logical mirror event after serving acceptance, and no reader-visible partial state. Task 7 owns this test.
2. A request started on H10 and committed after H11 must retain a superseded H10 attempt, reuse extraction/review artifacts, create exactly one H11 attempt, and never pretend H11 was the original input. Tasks 2, 5, and 7 own this test.
3. Source correction to empty followed by failed reprocessing: current reads must select the empty accepted attempt, while a later failed attempt leaves it unchanged and all histories remain reproducible. Task 8 owns this test.
4. Legacy split plus Social many-to-one consolidation: claim allocation must preserve historical legacy interpretation and conflicting administrator decisions must remain blocked. Tasks 9 and 12 own these tests.
5. Late producer commit and out-of-order compatibility delivery: old-mode work must not cross cutover, and projection revision 1 after revision 2 must be a no-op. Tasks 3, 11, and 16 own these tests.
6. One post through legacy and Social with a later lens-only change: it retains one family and ordinary lineage, avoids a second extraction/provider charge, and counts as one deduplicated source family. Tasks 5 and 12 own this test.
7. A prepared generation must still publish during continuous ordinary writes, while a stale parent or declared semantic invalidator must abort it. Tasks 3, 16, and 17 own this test.
8. G1 must remain byte-for-byte reproducible after eligibility, Social decision, development, override, or mapping changes; only G2 may expose those revisions. Tasks 2, 3, 8, 12-14, and 16 own this test.
9. A corrected-empty packet followed by first admission of an older or less-complete capture through another route must remain empty unless source precedence is proven; ambiguous precedence is held for review. Tasks 0, 5, 8, and 12 own this test.
10. One transient provider failure followed by success must preserve two truthful provider attempts and one reusable successful artifact; an uncertain timeout must remain distinct from a known pre-dispatch failure. Tasks 0, 5-7, and 12 own this test.
11. A crash after committing G2 publication but before notification must not strand G2 compatibility events or block G3; ordinary workers derive eligibility from publication history, while abandoned events remain invisible. Tasks 11, 16, and 17 own this test.
12. Two Social membership revisions for the same theme/security must coexist, stay generation-pinned, and leave legacy rows unchanged. Tasks 0, 2, and 12 own this test.

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
- `backend/app/models/economic_taxonomy_runtime.py` — lineages, packets, requests, reusable artifacts, exact attempts/events, assignments, selections/overrides, observations, mappings, revisions, metrics, outbox, and serving artifacts/events.
- `backend/app/infra/db/repositories/economic_taxonomy_repo.py` — clone, validate, hash, and seal semantic snapshots.
- `backend/app/infra/db/repositories/economic_taxonomy_work_repo.py` — evidence/request/artifact/attempt idempotency and leases.
- `backend/app/infra/db/repositories/economic_taxonomy_publication_repo.py` — cutoff capture, generation-input manifests, sealed artifacts, generation events, and atomic pointer changes.

### Services

- `backend/app/services/economic_taxonomy_fence.py` — shared producer and exclusive publisher lock protocol.
- `backend/app/services/economic_source_admission.py` — canonical source families, frozen packets, and lens eligibility.
- `backend/app/services/economic_exposure_extraction.py` — structured exposure extraction.
- `backend/app/services/economic_exposure_claim_review.py` — evidence and composition validation.
- `backend/app/services/economic_theme_candidate_retrieval.py` — bounded retrieval only.
- `backend/app/services/economic_theme_resolution.py` — semantic decisions with explicit direction.
- `backend/app/services/economic_theme_naming.py` — governed normalization and deterministic names.
- `backend/app/services/economic_taxonomy_processor.py` — immutable attempt persistence, reusable artifacts, and one-shot processing-head advancement.
- `backend/app/services/economic_theme_embedding_service.py` — append-only derived retrieval cache with deterministic lexical/facet fallback.
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
- `backend/alembic/versions/20260921_0047_economic_taxonomy_interpretations.py` — lineages, evidence packets and precedence references, requests, extraction/review artifacts, attempts/events, assignments, selections/overrides, observations, signals, and embeddings.
- `backend/alembic/versions/20260921_0048_economic_taxonomy_publication.py` — authority, dirty/semantic revisions, complete manifests, sealed artifacts, generation events, and reader capabilities.
- `backend/alembic/versions/20260921_0049_economic_taxonomy_work.py` — leased processing requests, candidates, proposals/decisions, and provider attempts.
- `backend/alembic/versions/20260921_0050_economic_taxonomy_mappings.py` — dispositions, destinations, allocations, redirects, and operations.
- `backend/alembic/versions/20260921_0051_economic_taxonomy_outbox.py` — staged ordered outbox, publication-history eligibility, delivery attempts, and projection checkpoints.
- `backend/alembic/versions/20260921_0052_economic_taxonomy_social.py` — stable global Social association identity, numbered association/decision revisions, and legacy bridge.
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
- Verify: `docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md`
- Verify: `docs/adr/0005-economic-taxonomy-snapshots-and-interpretations.md`
- Create: `backend/app/domain/economic_taxonomy/__init__.py`
- Create: `backend/app/domain/economic_taxonomy/contracts.py`
- Create: `backend/app/domain/economic_taxonomy/policy.py`
- Create: `backend/tests/unit/test_economic_taxonomy_contracts.py`
- Create: `backend/tests/fixtures/economic_taxonomy/contract_cases.json`

**Interfaces:**
- Consumes: the approved design and existing authority names from the legacy Theme/Social domains.
- Produces: `SourceLineageKey`, `ProcessingRequestKey`, `ProviderAttemptKey`, `ExtractionArtifactKey`, `ClaimReviewArtifactKey`, `ClassificationAttemptKey`, `EvidencePrecedenceDecision`, `SocialAssociationRevisionRef`, `GenerationInputSelection`, `ProjectionKey`, `AdminPrincipal`, `MigrationDispositionResult`, `SocialDecisionResult`, `choose_interpretation()`, `decide_evidence_precedence()`, `projection_is_deliverable()`, `relationship_from_proposed()`, `reconcile_social_decisions()`, `validate_split_allocations()`, and all shared enums.

- [ ] **Step 1: Write failing pure contract tests for every blocking counterexample**

```python
def test_h10_and_h11_are_distinct_attempts_but_reuse_review_artifact():
    request = processing_request(packet="p5", policies="v1")
    h10 = attempt(request, input_taxonomy="H10", review_artifact="r1")
    h11 = attempt(request, input_taxonomy="H11", review_artifact="r1")
    assert h10.key != h11.key
    assert h10.review_artifact_id == h11.review_artifact_id

def test_later_effective_source_revision_wins_when_older_attempt_finishes_late():
    correction = completed_attempt(provider_revision_order=5, ordinal=5, assignments=())
    delayed_old = completed_attempt(provider_revision_order=4, ordinal=4, assignments=("ai-memory",))
    assert choose_interpretation(
        previous=None, candidates=(correction, delayed_old)
    ) == correction

def test_successful_empty_supersedes_old_interpretation():
    old = attempt("old", status="completed", assignment_count=1)
    empty = attempt("empty", status="completed", assignment_count=0)
    assert choose_interpretation(previous=old, candidates=(empty,)) == empty

def test_failed_reprocessing_retains_previous_interpretation():
    assert choose_interpretation(
        previous=attempt("accepted", status="completed"),
        candidates=(attempt("failed", status="failed"),),
    ).attempt_key == "accepted"

def test_route_ids_do_not_change_ordinary_lineage():
    assert lineage(provider_post="42", route="legacy") == lineage(
        provider_post="42", route="social"
    )

def test_late_archive_cannot_supersede_corrected_empty_without_source_precedence():
    decision = decide_evidence_precedence(
        accepted=packet(provider_revision="5", assignments=()),
        candidate=packet(provider_revision=None, captured_from="late_archive", assignments=("memory",)),
    )
    assert decision == EvidencePrecedenceDecision.HOLD_REVIEW

def test_less_complete_recapture_does_not_withdraw_prior_attachment_evidence():
    decision = decide_evidence_precedence(
        accepted=packet(provider_revision="5", attachment_hashes=("a1",)),
        candidate=packet(provider_revision=None, attachment_hashes=()),
    )
    assert decision == EvidencePrecedenceDecision.HOLD_REVIEW

def test_retryable_failure_is_attempt_history_not_reusable_artifact():
    first = provider_attempt(
        logical_request="request:p5:v1", operation="extract", number=1,
        outcome="retryable_failure",
    )
    second = provider_attempt(
        logical_request="request:p5:v1", operation="extract", number=2,
        outcome="success",
    )
    assert first.key != second.key
    assert first.result_artifact_id is None
    assert second.result_artifact_id == "artifact-1"

def test_social_pair_identity_allows_numbered_revision_history():
    accepted = SocialAssociationRevisionRef(association_id="a1", revision_number=1)
    rejected = SocialAssociationRevisionRef(association_id="a1", revision_number=2)
    assert accepted != rejected

def test_projection_delivery_is_derived_from_publication_history():
    assert projection_is_deliverable(generation_event="published") is True
    assert projection_is_deliverable(generation_event="abandoned") is False

def test_generation_selection_pins_auxiliary_revisions():
    selection = GenerationInputSelection(
        lineage="post:42", selected_attempt_id="attempt-3", eligibility_revision=4,
        evidence_precedence_revision=5, interpretation_override_revision_id=None,
        social_decision_revision=6, development_revision=7,
        mapping_revision=8, metrics_policy_revision=9,
        compatibility_projection_revision=10,
    )
    assert selection.evidence_precedence_revision == 5

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
    key = ProjectionKey(
        source_lineage="post:1", projection_revision=2,
        projection_kind="legacy_theme", projection_version=1, target="legacy",
    )
    assert "authority_epoch" not in key.__dataclass_fields__

def test_v1_names_unsigned_fundamental_view():
    assert RankingView.FUNDAMENTAL_ATTENTION.value == "fundamental_attention"
    assert "fundamental_momentum" not in {item.value for item in RankingView}
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
    FUNDAMENTAL_ATTENTION = "fundamental_attention"
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

class EvidencePrecedenceDecision(StrEnum):
    ADVANCE = "advance"
    REUSE_EQUIVALENT = "reuse_equivalent"
    IGNORE_SUPERSEDED = "ignore_superseded"
    HOLD_REVIEW = "hold_review"

class ProviderAttemptOutcome(StrEnum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    UNCERTAIN = "uncertain"
    TERMINAL_FAILURE = "terminal_failure"
```

Add attempt events `started|completed|failed|superseded_before_acceptance`, serving-generation events `prepared|published|superseded|abandoned`, and failure codes `invalid_schema`, `unsupported_composition`, `unknown_dimension`, `requires_naming_review`, `ambiguous_identity`, `stale_processing_head`, `stale_authority_epoch`, `stale_projection_revision`, `authorization_required`, `budget_exhausted`, `conflict_review_required`, `compatibility_pending`, `reader_not_ready`, `manifest_changed`, `publication_validation_failed`, `rollback_recovery_required`, `provider_retryable`, `provider_outcome_uncertain`, and `provider_terminal`.

Define keys exactly as follows:

- ordinary `SourceLineageKey` derives from the canonical source family; a scope suffix requires an explicit non-overlapping admission-policy key;
- `ProcessingRequestKey` uses lineage, evidence packet, and desired policy bundle, but not a taxonomy head;
- `ProviderAttemptKey` uses stable logical request, operation kind, and monotonically assigned attempt number; each actual dispatch gets a distinct key;
- `ExtractionArtifactKey` is `(evidence_packet_id, extraction_policy_version)`;
- `ClaimReviewArtifactKey` is `(extraction_artifact_id, claim_review_policy_version, facet_catalog_semantic_hash)`;
- `ClassificationAttemptKey` adds actual input taxonomy plus resolver, naming, and derivation policy versions;
- `ProjectionKey` is `(source_lineage, projection_revision, projection_kind, projection_version, target)` and excludes authority epoch.

Define `EvidencePrecedenceDecision` as `advance|reuse_equivalent|ignore_superseded|hold_review`. The admission ordinal orders stored packets but cannot return `advance` on its own. Define `SocialAssociationRevisionRef` as stable association ID plus revision number. Define projection deliverability from append-only successful publication history, never from an optional notification/release flag.

- [ ] **Step 4: Implement the pure selection, direction, mapping, and decision rules**

`decide_evidence_precedence()` uses authoritative provider revision identity/order when supplied, explicit correction/supersession links, and known-equivalent packet identity. It never invents provider ordering; a late archive, partial recapture, or conflicting packet without adequate precedence metadata returns `hold_review`. `choose_interpretation()` considers only completed attempts whose packets are effective under that decision, then uses lineage ordinal for deterministic ordering within established precedence and permits an authenticated immutable override; completed-empty is valid. `validate_split_allocations()` requires every current claim to have exactly one destination or reviewed exclusion. `reconcile_social_decisions()` returns conflict for mixed administrator accept/reject decisions. `relationship_from_proposed()` returns `broader` for proposed Copper against Copper Miners.

- [ ] **Step 5: Freeze the schema/state-machine decisions before migration code**

Document in `contracts.py`: immutable payload versus append-only event tables; stable Social association identity versus numbered revisions; effective evidence precedence versus admission order; reusable terminal results versus retryable/uncertain provider attempts; publication-history-derived compatibility eligibility; the full `GenerationInputManifest` entry schema; bounded-cutoff and semantic-invalidation rules; complete-lineage projection replacement; proposal/override revision streams; retrieval embeddings as non-authoritative derived cache; authenticated administrator/service principals; dimension-definition inclusion in the facet-catalog hash; and the exact V1 lifecycle, attention, percentile, and technical-weighting rules. Verify the approved design and existing ADR remain consistent with those contracts; these amendments do not change either architecture document and must not create a duplicate ADR.

- [ ] **Step 6: Run the contract tests and fixture-schema check**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_contracts.py -q`

Expected: PASS with all named counterexamples collected.

- [ ] **Step 7: Commit the contract kernel**

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
- Produces: `TaxonomyVersion`, `EconomicTheme`, version-owned semantic rows, `EconomicTaxonomyRepository.clone_draft()`, `seal_draft()`, `load_snapshot()`, `semantic_hash()`, `facet_catalog_semantic_hash()`, and `artifact_integrity_hash()`.

- [ ] **Step 1: Write failing snapshot, graph, and hash tests**

```python
def test_semantic_clone_hash_ignores_ids_and_audit_metadata(repo, sealed_version):
    clone = repo.clone_draft(sealed_version.id, actor="test", reason="clone")
    assert repo.semantic_hash(clone) == repo.semantic_hash(sealed_version.id)
    assert repo.artifact_integrity_hash(clone) != repo.artifact_integrity_hash(sealed_version.id)

def test_sealed_snapshot_cannot_reopen(repo, sealed_version):
    with pytest.raises(ImmutableSnapshot):
        repo.set_status(sealed_version.id, "draft")

def test_specialization_cycle_is_rejected(repo, draft_with_a_to_b):
    repo.add_specialization(draft_with_a_to_b.id, narrower="b", broader="a")
    with pytest.raises(GraphInvariantViolation, match="specialization_cycle"):
        repo.seal_draft(draft_with_a_to_b.id)

def test_dimension_definition_alone_changes_catalog_and_snapshot_hash(repo, dimension_draft):
    before_catalog = repo.facet_catalog_semantic_hash(dimension_draft.id)
    before_snapshot = repo.semantic_hash(dimension_draft.id)
    repo.update_dimension(dimension_draft.id, "industry", definition="Revised semantic boundary")
    assert repo.facet_catalog_semantic_hash(dimension_draft.id) != before_catalog
    assert repo.semantic_hash(dimension_draft.id) != before_snapshot
```

- [ ] **Step 2: Run the tests and confirm missing models**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_snapshots.py -q`

Expected: FAIL on model import.

- [ ] **Step 3: Implement models, same-snapshot foreign keys, and immutable triggers**

Create stable UUID theme identity and complete version-owned revision, alias, facet, relationship, lifecycle, and policy rows. Use composite foreign keys containing `taxonomy_version_id` so references cannot cross snapshots. PostgreSQL triggers reject insert/update/delete against a sealed version and reject changing a row's version ID.

- [ ] **Step 4: Implement semantic and artifact-integrity hashes plus seal validation**

```python
SEMANTIC_HASH_FIELDS = {
    "theme": (
        "semantic_key", "display_name", "definition", "mechanism",
        "lifecycle", "lifecycle_policy_version",
    ),
    "alias": ("theme_semantic_key", "normalized_alias"),
    "dimension": (
        "key", "definition", "value_type", "cardinality", "scope",
        "normalization_policy", "inclusion_semantics", "exclusion_semantics",
    ),
    "facet": ("theme_semantic_key", "dimension_key", "normalized_value"),
    "relationship": (
        "source_semantic_key", "target_semantic_key", "kind", "direction", "discriminator",
    ),
    "mapping": ("legacy_identity", "disposition", "destinations", "allocations", "redirects"),
    "policy": ("policy_kind", "policy_version"),
}
```

Sort normalized payloads and exclude database IDs, version IDs, timestamps, actors, and comments. `facet_catalog_semantic_hash()` covers each dimension's key, semantic definition, value type, cardinality, scope, normalization policy, and separately stored inclusion/exclusion semantics; changing any one field changes the hash. The separate artifact-integrity hash covers the complete immutable serialization, including stable logical row IDs and provenance, but excludes mutable operational state. Seal while holding a version-scoped lock; validate no cycle and no active `distinct` contradiction with equivalence, redirects, or specialization. Task 9 extends the mapping portion once those rows exist.

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
- Produces: `SourceFamily`, `SourceLineage`, `EvidencePacket`, immutable evidence supersession/equivalence references, `LensEligibilityRevision`, `ProcessingRequest`, `ExtractionArtifact`, `ClaimReviewArtifact`, `ClassificationAttempt`, `ClassificationAttemptEvent`, `ClaimAssignment`, `InterpretationOverrideRevision`, `SocialAssociationRevisionRef`, sealable `InterpretationSet`, `InterpretationSelection`, `ThemeObservation`, `ThemeConstituentExposure`, `ThemeSignalObservation`, `EconomicThemeEmbedding`, sealable `MetricsRevision`, and `ThemeMetric`.

- [ ] **Step 1: Write failing uniqueness and immutability tests**

```python
def test_same_request_can_store_attempts_for_actual_h10_and_h11(db, request):
    review = claim_review_artifact(request, policy="review-v1")
    first = classification_attempt(request, review, input_taxonomy="H10")
    second = classification_attempt(request, review, input_taxonomy="H11")
    db.add_all([first, second])
    db.flush()
    assert first.id != second.id
    assert first.claim_review_artifact_id == second.claim_review_artifact_id

def test_evidence_ordinal_is_monotonic_inside_lineage(db, lineage):
    packets = [evidence_packet(lineage), evidence_packet(lineage)]
    db.add_all(packets)
    db.flush()
    assert [packet.evidence_revision_ordinal for packet in packets] == [1, 2]

def test_observation_identity_comes_from_assignment(db, assignment):
    db.add(ThemeObservation(claim_assignment_id=assignment.id, observation_kind="primary"))
    db.flush()

def test_generation_input_uses_social_association_revision_not_pair_only():
    first = SocialAssociationRevisionRef(association_id="association-1", revision_number=1)
    second = SocialAssociationRevisionRef(association_id="association-1", revision_number=2)
    assert first.association_id == second.association_id
    assert first != second
```

- [ ] **Step 2: Run tests and confirm models are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretation_models.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement immutable source, request, artifact, and attempt tables**

`SourceLineage` is route-independent and belongs to a canonical family. `EvidencePacket` stores lineage-local `evidence_revision_ordinal`, full provenance-sensitive packet hash, route-independent `evidence_content_fingerprint`, authoritative provider revision identity/order when supplied, capture provenance and capture time, explicit corrected/supersedes references, original/translated text references, admitted attachment/text hashes, grounding snapshot, preparation version, source metadata, and observed/available times. Assign the ordinal while locking the lineage. The ordinal is immutable admission order only; it does not itself assert that a late capture is a fresher source revision. Supersession, equivalence, and review-hold records are append-only.

`ProcessingRequest` is stable across stale-head retries and unique by lineage, packet, and desired policy bundle. `ExtractionArtifact` and `ClaimReviewArtifact` use the exact Task 0 keys, including explicit claim-review policy and facet-catalog semantic hash. `ClassificationAttempt` adds the actual input taxonomy and resolver/naming/derivation policies, records nullable output taxonomy, and has append-only status events. Completed attempt payloads and `ClaimAssignment` rows are immutable; a completed attempt may have zero assignments.

- [ ] **Step 4: Implement sealed interpretation/metrics payloads and append-only auxiliary revisions**

`InterpretationSelection` is unique by `(interpretation_set_id, source_lineage_id)` and references a completed attempt plus the pinned evidence ordinal and optional immutable override revision. Observation, constituent, and signal uniqueness includes immutable assignment identity; no rule overwrites a prior policy's row. Interpretation sets and metrics revisions build unsealed, then permit one audited `unsealed -> sealed` transition that writes `sealed_at`, semantic/content hash, and artifact-integrity hash; triggers reject payload mutation after sealing.

Persist append-only eligibility, constituent-decision, proposal-decision, development-selection, and interpretation-override revision identities even when later migrations add their payload columns. Define Social generation references as `(association_id, revision_number)` and decision revision ID—not as theme/security pair alone—so Task 12 can materialize multiple immutable revisions for one stable pair. Add `EconomicThemeEmbedding` keyed by theme UUID, taxonomy semantic hash, source text hash, embedding model, and model version; it is a derived cache excluded from semantic authority and snapshot hash.

- [ ] **Step 5: Run migration and model tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretation_models.py tests/integration/test_economic_taxonomy_interpretation_migration.py tests/unit/test_main_migrations.py -q`

Expected: PASS and Alembic head `20260921_0047`; H10/H11 attempts coexist, old payloads reject mutation, evidence ordinal allocation is concurrency-safe, and Social selections carry stable association ID plus immutable revision number.

- [ ] **Step 6: Commit interpretation persistence**

```bash
git add backend/app/models/economic_taxonomy_runtime.py backend/app/models/__init__.py backend/alembic/versions/20260921_0047_economic_taxonomy_interpretations.py backend/tests/unit/test_economic_taxonomy_interpretation_models.py backend/tests/integration/test_economic_taxonomy_interpretation_migration.py
git commit -m "feat: persist taxonomy interpretation history"
```

### Task 3: Add serving generations, manifests, and the shared writer fence

**Files:**
- Modify: `backend/app/models/economic_taxonomy_runtime.py`
- Modify: `backend/app/api/v1/config.py`
- Create: `backend/app/services/economic_taxonomy_fence.py`
- Create: `backend/app/infra/db/repositories/economic_taxonomy_publication_repo.py`
- Create: `backend/alembic/versions/20260921_0048_economic_taxonomy_publication.py`
- Test: `backend/tests/unit/test_economic_taxonomy_admin_auth.py`
- Test: `backend/tests/unit/test_economic_taxonomy_publication_models.py`
- Test: `backend/tests/integration/test_economic_taxonomy_fence_postgres.py`

**Interfaces:**
- Consumes: sealed versions and interpretation sets.
- Produces: `TaxonomyAuthority`, `TaxonomySourceRevisionLog`, `SemanticInvalidationRevision`, `GenerationInputManifest`, immutable `ServingGeneration`, `ServingGenerationEvent`, sealable `ReaderSnapshotBundle`, `ReaderCapabilityManifest`, authenticated `AdminPrincipal`, `producer_write()`, and `exclusive_publication()`.

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

def test_post_cutoff_ordinary_revision_does_not_invalidate_manifest(repo, captured_cutoff):
    repo.append_ordinary_revision(after=captured_cutoff)
    assert repo.validate_cutoff(captured_cutoff).valid is True

def test_missing_admin_principal_id_fails_closed(admin_key, settings):
    settings.admin_principal_id = None
    with pytest.raises(HTTPException) as error:
        require_admin(x_admin_key=admin_key, settings=settings)
    assert error.value.status_code == 503
```

- [ ] **Step 2: Run tests and confirm missing publication models**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_publication_models.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement authority, immutable generation payloads, append-only events, and complete manifests**

Authority contains mode, processing version/revision, serving generation, epoch, write-fence state, semantic-invalidation revision, cutover catch-up cursor, and rollback state. A serving generation is immutable payload only: sealed taxonomy, interpretation set, metrics revision, generation-input manifest, reader snapshot bundle, capability manifest, semantic hash, and artifact-integrity hash. Status lives in append-only `ServingGenerationEvent(prepared|published|superseded|abandoned)`; the authority pointer alone identifies the active generation.

`GenerationInputManifest` stores sorted typed selections for lineage/evidence packet, evidence precedence/supersession revision, accepted attempt/override, lens eligibility, constituent decisions, Social association/decision projection, development observation/selection, mapping/redirect snapshot, metrics policy, and compatibility projection/checkpoint. Its cutoff is a committed revision tuple set, not a maximum allocated ID. Create sealable `ReaderSnapshotBundle` identity here; Task 14 fills its generation-scoped payload. Add manifest foreign keys to interpretation sets, metrics revisions, and snapshot bundles; all must reference the same sealed manifest before preparation.

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

- [ ] **Step 5: Extend existing administrator authentication to return a trusted principal**

Change `require_admin` in `backend/app/api/v1/config.py` to return `AdminPrincipal(subject=settings.admin_principal_id, auth_method="admin_api_key")` only after key validation. Require `ADMIN_PRINCIPAL_ID`; fail closed when it or the key is absent. Semantic write, mode-change, manual-publication, and recovery services accept this principal object and never trust `X-Admin-Actor` or a request-body actor string. Reserve the fixed `system:economic-taxonomy-refresh` service principal for Task 17 automation.

- [ ] **Step 6: Prove the late-lower-ID race and bounded cutoff are correct**

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_fence_postgres.py -q`

Expected: exclusive acquisition waits for existing shared writers, blocks new writers, and captures a committed manifest containing a transaction whose sequence ID was allocated earlier. New ordinary work after the cutoff does not invalidate it; a later structural semantic-invalidation revision does.

- [ ] **Step 7: Run authentication tests and commit publication primitives**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_admin_auth.py tests/unit/test_economic_taxonomy_publication_models.py -q`

Expected: PASS, including denied access before any preview/application row is written and stored actors sourced only from the trusted principal.

```bash
git add backend/app/models/economic_taxonomy_runtime.py backend/app/api/v1/config.py backend/app/services/economic_taxonomy_fence.py backend/app/infra/db/repositories/economic_taxonomy_publication_repo.py backend/alembic/versions/20260921_0048_economic_taxonomy_publication.py backend/tests/unit/test_economic_taxonomy_admin_auth.py backend/tests/unit/test_economic_taxonomy_publication_models.py backend/tests/integration/test_economic_taxonomy_fence_postgres.py
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
- Produces: `admit_content()`, `admit_social_work()`, `decide_evidence_precedence()`, `revise_lens_eligibility()`, `enqueue_request()`, `claim_next()`, `begin_provider_attempt()`, `retry()`, and `complete()`.

- [ ] **Step 1: Write failing source-family, packet, and eligibility tests**

```python
def test_same_provider_post_from_legacy_and_social_shares_family(admission, post):
    legacy = admission.admit_content(post.as_content_item())
    social = admission.admit_social_work(post.as_saved_work())
    assert legacy.source_family_id == social.source_family_id
    assert legacy.source_lineage_id == social.source_lineage_id
    assert social.precedence_state == "equivalent"
    assert social.effective_packet_id == legacy.effective_packet_id

def test_adding_lens_does_not_create_packet_or_work(admission, admitted):
    revised = admission.revise_lens_eligibility(admitted.packet_id, add="fundamental")
    assert revised.packet_id == admitted.packet_id
    assert revised.enqueued_request_id is None

def test_delayed_packet_keeps_admission_order(admission, lineage):
    old = admission.admit(lineage, payload="old")
    correction = admission.admit(lineage, payload="corrected")
    assert old.evidence_revision_ordinal < correction.evidence_revision_ordinal

def test_first_admitted_late_archive_does_not_restore_corrected_empty(admission, corrected_empty):
    late = admission.admit_social_work(
        archived_capture(corrected_empty.source, provider_revision=None, old_payload="Memory demand")
    )
    assert late.evidence_revision_ordinal > corrected_empty.evidence_revision_ordinal
    assert late.precedence_state == "hold_review"
    assert admission.effective_packet(corrected_empty.lineage_id).id == corrected_empty.id

def test_less_complete_recapture_does_not_withdraw_attachment_evidence(admission, packet_with_attachment):
    recapture = admission.admit_content(
        partial_capture(packet_with_attachment.source, attachments=())
    )
    assert recapture.precedence_state == "hold_review"
    assert admission.effective_packet(packet_with_attachment.lineage_id).id == packet_with_attachment.id

def test_retryable_provider_work_gets_new_attempt_identity(work_repo, request):
    first = work_repo.begin_provider_attempt(request.id, operation="extract")
    work_repo.fail_attempt(first.id, outcome="retryable_failure")
    second = work_repo.begin_provider_attempt(request.id, operation="extract")
    assert second.logical_request_id == first.logical_request_id
    assert second.attempt_number == first.attempt_number + 1
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_source_admission.py tests/unit/test_economic_taxonomy_work_repo.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement family resolution and packet hashing**

The full packet hash includes selected original/translated text, translation version, admitted attachments and extracted-text hashes, grounding snapshot, preparation version, source metadata, authoritative provider revision identity/order when available, capture provenance, and explicit correction/supersession references. A separate route-independent evidence-content fingerprint covers the admitted evidence bytes/attachment/grounding/preparation inputs but excludes route and capture metadata; it identifies equivalent evidence received through legacy and Social without discarding either route's provenance. Both exclude lens eligibility. Canonical provider post ID wins over route-specific database IDs for family and ordinary-lineage keys. A scope suffix is accepted only with a governed admission-policy key proving a non-overlapping evidence scope. Assign a monotonic packet ordinal while locking the lineage, but use Task 0's precedence policy to mark the packet `effective`, `equivalent`, `superseded`, or `hold_review`.

Reuse a known-equivalent packet instead of creating another effective revision. Advance only when provider metadata or an explicit correction establishes precedence. Never invent provider-specific ordering. A first-time late archive, a partial recapture missing previously admitted attachments/context, or any unresolved conflict remains reproducible but held for review and cannot displace the effective packet.

- [ ] **Step 4: Implement work identity and leases**

Work identity is the stable `ProcessingRequestKey` from Task 0, not an assumed taxonomy-head attempt key. Persist durable candidate and dimension/naming proposal rows beside work. Persist each provider call as a separate append-only `ProviderAttempt(logical_request_id, operation_kind, attempt_number)`; the unique key permits several attempts for one request but makes retry of the same dispatch idempotent. Claim with `FOR UPDATE SKIP LOCKED`, UUID lease token, five-minute expiry, observed processing-head revision, and observed authority epoch. Completion occurs inside `producer_write()`. A stale head records/supersedes the exact old-head attempt and schedules resolution against the new head; a stale authority rejects the commit. Neither case mutates an existing provider attempt, classification attempt, or assignment.

- [ ] **Step 5: Run reproducibility and concurrency tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_source_admission.py tests/unit/test_economic_taxonomy_work_repo.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_work_postgres.py -q`

Expected: one claimant per request, route aliases share one ordinary lineage, old packets retain frozen translation/grounding, ordinals are monotonic but do not override unresolved freshness, late/partial captures stay held, provider retry attempt numbers are concurrency-safe, and lens-only changes do not enqueue extraction.

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
- Consumes: frozen effective `EvidencePacket`, Task 5 provider-attempt repository, approved facet-catalog semantic hash, explicit extraction/claim-review policies, optional provider reservation.
- Produces: `extract(request: ProcessingRequest) -> ExtractionArtifact`, which reuses `get_extraction_artifact(packet, policy)` when present, and `review(extraction: ExtractionArtifact, policy, facet_hash) -> ClaimReviewArtifact`.

- [ ] **Step 1: Write failing composition, empty, unknown-dimension, and support-state tests**

```python
def test_ai_and_memory_cooccurrence_without_link_is_not_ai_memory(extractor):
    result = extractor.extract(request_for(packet("AI spending rose. Memory pricing rose independently.")))
    assert "AI Memory" not in result.accepted_names

def test_unknown_dimension_is_review_required_not_parse_failure(extractor):
    result = extractor.extract(request_for(packet_with_dimension("deployment_model", "edge")))
    assert result.status == "review_required"
    assert result.candidates[0].raw_facets["deployment_model"] == "edge"

def test_successful_empty_is_distinct_from_failure(extractor):
    assert extractor.extract(request_for(packet("No investable exposure."))).status == "successful_empty"

def test_retryable_failure_then_success_preserves_attempts_and_reuses_success(
    extractor, provider, budget, request
):
    provider.side_effects = [
        RetryableProviderError(provider_request_id="r1", actual_cost=ZERO),
        accepted_payload("Memory"),
    ]
    with pytest.raises(RetryableProviderFailure):
        extractor.extract(request)
    succeeded = extractor.extract(request)
    repeated = extractor.extract(request)
    assert [attempt.outcome for attempt in request.provider_attempts] == ["retryable_failure", "success"]
    assert succeeded.artifact_id == repeated.artifact_id
    assert provider.call_count == 2
    assert budget.reservation_count == 2

def test_uncertain_timeout_is_not_released_like_known_pre_dispatch_failure(extractor):
    uncertain = extractor.record_timeout(provider_dispatch_confirmed=True)
    pre_dispatch = extractor.record_failure(provider_dispatch_confirmed=False)
    assert uncertain.attempt.state == "uncertain"
    assert uncertain.retry_allowed is False
    assert pre_dispatch.attempt.state == "released"
    assert pre_dispatch.retry_allowed is True

def test_dimension_definition_change_invalidates_claim_review_artifact(reviewer, extraction):
    first = reviewer.review(extraction, facet_hash="catalog-definition-v1")
    second = reviewer.review(extraction, facet_hash="catalog-definition-v2")
    assert first.id != second.id
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement schema-constrained extraction as a reusable immutable artifact**

Key reusable raw extraction artifacts by `(evidence_packet_id, extraction_policy_version)` and create them only for `accepted_candidates|successful_empty|review_required` terminal result payloads. Preserve raw candidates for unknown dimensions and naming review. Separate exposure support from development support and require quoted evidence spans for compound relationships. After an artifact exists, identical requests return it without another provider call.

A provider failure is not an extraction artifact. Known pre-dispatch failure releases its reservation and leaves retryable work. A dispatched transient failure remains an immutable failed attempt; retry creates a new Task 5 provider-attempt identity and budget reservation under the same logical request. An ambiguous timeout remains `uncertain` until provider/budget policy resolves whether another call is permitted; request idempotency does not claim exactly-once billing. A later success creates/selects the reusable artifact without overwriting prior attempt history.

- [ ] **Step 4: Implement claim review as a separately reusable artifact outside persistence locks**

Key review by extraction artifact, explicit claim-review policy version, and the facet-catalog semantic hash from Task 1. A dimension-definition-only change therefore creates a distinct review artifact even when extraction is reusable. Reject technical setups as themes, enforce narrowest supported specificity, validate security grounding, and retain provider response hashes. Deterministic held/review-required results remain held until an explicitly eligible input, policy, facet-catalog, or reviewed decision changes. Provider quota/timeout follows the attempt policy above; schema/composition failure is durable review or terminal according to Task 0 codes. A taxonomy-head-only change must not repeat either provider result artifact.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py -q`

Expected: PASS; transient failure then success records two truthful attempts and one successful artifact, a repeated success performs no provider call, uncertain timeout differs from pre-dispatch failure, and a definition-only catalog change invalidates claim-review reuse.

```bash
git add backend/app/services/economic_exposure_extraction.py backend/app/services/economic_exposure_claim_review.py backend/tests/unit/test_economic_exposure_extraction.py backend/tests/unit/test_economic_exposure_claim_review.py
git commit -m "feat: extract reviewed economic exposures"
```

### Task 7: Resolve identities and advance the processing head atomically

**Files:**
- Create: `backend/app/services/economic_theme_candidate_retrieval.py`
- Create: `backend/app/services/economic_theme_embedding_service.py`
- Create: `backend/app/services/economic_theme_resolution.py`
- Create: `backend/app/services/economic_taxonomy_processor.py`
- Test: `backend/tests/unit/test_economic_theme_candidate_retrieval.py`
- Test: `backend/tests/unit/test_economic_theme_resolution.py`
- Test: `backend/tests/unit/test_economic_taxonomy_processor.py`
- Test: `backend/tests/integration/test_economic_processing_publication_postgres.py`

**Interfaces:**
- Consumes: reviewed candidates, processing snapshot, work lease, naming service, fence.
- Produces: `retrieve_candidates()`, `get_or_recompute_embedding()`, `resolve_candidate()`, and `EconomicTaxonomyProcessor.process(request_id, lease_token)`.

- [ ] **Step 1: Write failing direction and crash-idempotency tests**

```python
def test_proposed_copper_is_broader_than_existing_copper_miners(resolver):
    assert resolver.resolve(proposed=copper(), existing=copper_miners()).outcome == "broader"

def test_retry_after_processing_head_crash_reuses_identity(processor, fault, request):
    fault.raise_after("processing_head_commit")
    with pytest.raises(InjectedCrash):
        processor.process(request.id, request.lease_token)
    result = processor.process(request.id, request.lease_token)
    assert result.created_identity_count == 0
    assert result.classification_attempt_count == 1

def test_stale_h10_attempt_is_retained_and_h11_reuses_artifacts(processor, request):
    result = processor.process_while_head_advances(request, old="H10", new="H11")
    assert result.attempts == (("H10", "superseded_before_acceptance"), ("H11", "completed"))
    assert len({attempt.extraction_artifact_id for attempt in result.rows}) == 1
    assert len({attempt.claim_review_artifact_id for attempt in result.rows}) == 1

def test_retryable_or_uncertain_provider_attempt_cannot_be_classified(processor, request):
    request.extraction_artifact = None
    request.provider_attempt_state = "uncertain"
    with pytest.raises(ProviderResultUnavailable):
        processor.process(request.id, request.lease_token)

def test_concurrent_observations_of_existing_identity_do_not_advance_head(
    processor, established_theme, concurrent_requests
):
    head = processor.processing_head()
    results = processor.process_concurrently(concurrent_requests.for_theme(established_theme.id))
    assert processor.processing_head() == head
    assert all(result.output_taxonomy_version_id is None for result in results)
    assert len({result.assignment_id for result in results}) == len(results)
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_candidate_retrieval.py tests/unit/test_economic_theme_resolution.py tests/unit/test_economic_taxonomy_processor.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement bounded retrieval and semantic resolution**

Retrieval returns at most 20 candidates from aliases, normalized facets, lexical search, append-only cached embeddings, constituents, and graph neighbors. `EconomicThemeEmbedding` is keyed exactly as defined in Task 2, excluded from semantic hashes, and recomputed from the sealed revision when missing/stale. Provider failure falls back to lexical/facet retrieval without changing identity. Resolution expresses proposed relative to existing and validates that provider output is one allowed outcome with referenced candidate IDs.

- [ ] **Step 4: Implement one exact attempt and processing-head transaction per request/head pair**

Require a selected successful/review-eligible Task 6 artifact; retryable, failed, or uncertain provider-attempt rows alone cannot produce a classification attempt. Construct the attempt key from the reviewed artifact and the actual resolver input taxonomy, then compute the semantic patch before cloning.

Under `producer_write()`, lock authority/request and verify the processing revision. If the patch adds or changes a supported identity, alias, facet, relationship, lifecycle value, mapping, or other semantic content, clone one draft, apply every eligible change, attribute automated provisional creation only to `system:economic-taxonomy-refresh`, seal once, set `output_taxonomy_version_id`, and advance the processing head/revision. If the result is successful-empty or non-empty but only assigns observations to existing identities with no semantic delta, persist the completed attempt and assignments with null `output_taxonomy_version_id` and leave the head unchanged. Actual supported alias/facet changes legitimately create a version. Append one dirty source revision and complete the request in either case. No live compatibility event becomes deliverable until a generation selects the attempt.

- [ ] **Step 5: Implement stale-head re-resolution**

If the processing head changed, retain the exact old-head attempt and append `superseded_before_acceptance`, release the transaction, then retrieve/resolve again against the new head using the same request and reusable extraction/review artifacts. Persist a distinct new-head attempt. A retry of an already committed new-head attempt returns it. Never relabel an old attempt with the new head and never run provider work under a database lock.

- [ ] **Step 6: Run unit and PostgreSQL crash/race tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_candidate_retrieval.py tests/unit/test_economic_theme_resolution.py tests/unit/test_economic_taxonomy_processor.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_processing_publication_postgres.py -q`

Expected: several semantic changes from one source create one sealed processing version; H10/H11 history is truthful; failed/uncertain provider attempts cannot classify; retry creates no duplicate identity, attempt, assignment, provider artifact, or logical mirror intent; concurrent observation-only requests accumulate assignments while the processing taxonomy head remains constant.

- [ ] **Step 7: Commit processing-head orchestration**

```bash
git add backend/app/services/economic_theme_candidate_retrieval.py backend/app/services/economic_theme_embedding_service.py backend/app/services/economic_theme_resolution.py backend/app/services/economic_taxonomy_processor.py backend/tests/unit/test_economic_theme_candidate_retrieval.py backend/tests/unit/test_economic_theme_resolution.py backend/tests/unit/test_economic_taxonomy_processor.py backend/tests/integration/test_economic_processing_publication_postgres.py
git commit -m "feat: resolve themes into the processing taxonomy"
```

### Task 8: Build accepted interpretations and assignment-derived facts

**Files:**
- Create: `backend/app/services/economic_taxonomy_interpretations.py`
- Create: `backend/app/services/economic_theme_observation_service.py`
- Test: `backend/tests/unit/test_economic_taxonomy_interpretations.py`
- Test: `backend/tests/unit/test_economic_theme_observations.py`

**Interfaces:**
- Consumes: `GenerationInputManifest`, completed attempts, effective-evidence precedence records and admission ordinals, assignments, pinned eligibility/decision/development/mapping revisions, and authenticated override revisions.
- Produces: `build_interpretation_set()`, `materialize_assignment_facts()`, and generation-scoped observation/constituent/signal queries.

- [ ] **Step 1: Write failing correction and historical-read tests**

```python
def test_corrected_to_empty_removes_current_facts(builder, old_attempt, empty_attempt):
    first = builder.build(manifest_selecting(old_attempt))
    second = builder.build(manifest_selecting(empty_attempt))
    assert builder.current_observations(second.id) == []
    assert len(builder.current_observations(first.id)) == 1

def test_failed_attempt_cannot_replace_selected_attempt(builder, accepted, failed):
    with pytest.raises(InvalidInterpretation, match="attempt_not_completed"):
        builder.build(manifest_selecting(failed))

def test_delayed_effective_revision_four_cannot_replace_revision_five(builder):
    current = completed_attempt(provider_revision_order=5, ordinal=5, assignments=())
    delayed = completed_attempt(provider_revision_order=4, ordinal=4, assignments=("memory",))
    assert builder.choose_default((current, delayed)) == current

def test_old_generation_pins_old_auxiliary_revisions(builder, generation_one):
    mutate_current_eligibility_social_decision_and_development()
    assert builder.read(generation_one.id) == generation_one.expected_payload

def test_route_alias_correction_to_empty_retracts_one_shared_lineage(builder, routed_post):
    corrected = builder.build(manifest_selecting(routed_post.social_empty_attempt))
    assert builder.current_observations(corrected.id, route="legacy") == []
    assert builder.current_observations(corrected.id, route="social") == []

def test_late_archived_payload_cannot_replace_corrected_empty(builder, corrected_empty, late_archive):
    assert late_archive.ordinal > corrected_empty.ordinal
    assert late_archive.precedence_state == "hold_review"
    selected = builder.choose_default((corrected_empty.attempt, late_archive.attempt))
    assert selected == corrected_empty.attempt

def test_partial_recapture_does_not_withdraw_attachment_backed_interpretation(
    builder, attachment_packet, partial_recapture
):
    selected = builder.choose_default((attachment_packet.attempt, partial_recapture.attempt))
    assert partial_recapture.precedence_state == "hold_review"
    assert selected == attachment_packet.attempt
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretations.py tests/unit/test_economic_theme_observations.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement immutable selection and fact materialization**

Select zero or one completed attempt per admitted source lineage from the manifest. First restrict candidates to the effective evidence chain established by authoritative provider revision metadata, explicit supersession/equivalence, or reviewed precedence. Packets in `hold_review` never displace the last accepted attempt merely because they have a higher admission ordinal. Within an established precedence chain, choose the highest effective ordinal and eligible completed policy attempt; a generation-pinned authenticated override may choose another completed attempt. Failed, partial, review-only, held, and superseded attempts are ineligible. Seal the set after validating that every selection, precedence record, and auxiliary revision appears in the same manifest. Materialize primary observations, one-hop derived observations sharing root/source family, constituent exposures, and structured signals from assignments. Current queries always join the requested serving generation, never a free-standing interpretation-set ID or mutable latest decision.

- [ ] **Step 4: Pin source-family deduplication and signal persistence**

One source family counts once per theme/channel/UTC day even when admitted through two routes; describe this as deduplication, not statistical independence. Derived facts never increment direct/root counts. Store signal type, normalized payload, security, UTC `available_at`, detected/effective times, source family, assignment, and detector policy.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_interpretations.py tests/unit/test_economic_theme_observations.py -q`

Expected: PASS for old/new reproducibility including pinned auxiliary revisions, successful empty correction, failed reprocessing, delayed older completion, late archives and partial recaptures held from supersession, authenticated overrides, and source-family deduplication.

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
- Consumes: draft repository, claim assignments, trusted `AdminPrincipal`, and reviewer reason.
- Produces: `LegacyIdentityDisposition`, `LegacyDestinationMapping`, `LegacyClaimAllocation`, `EconomicThemeRedirect`, immutable operation request/preview payloads, append-only operation/proposal/override events, `preview_operation()`, and `apply_operation()`.

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

def test_caller_supplied_actor_is_never_persisted(service, admin_principal):
    op = service.preview(rename_request(actor="forged"), principal=admin_principal)
    assert op.actor_subject == admin_principal.subject
```

- [ ] **Step 2: Run tests and confirm models/services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_mappings.py tests/unit/test_economic_taxonomy_operations.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement version-owned mapping rows**

One disposition per `(taxonomy_version_id, legacy_theme_cluster_id)`; zero-to-many destinations; claim/source allocation to a destination or reviewed exclusion; version-owned economic redirects for merges. Clone all four mapping kinds with the semantic snapshot. Extend Task 1's immutability triggers, canonical semantic hash, same-snapshot validation, and contradictory-graph checks to these rows.

- [ ] **Step 4: Implement durable reviewed request, preview, decision, and apply events**

Persist the immutable request and preview rather than returning an ephemeral structure. Preview records before/after semantic and artifact hashes, affected identities, assignments, mappings, compatibility intents, and validation errors. Apply requires unchanged preview hash, trusted `AdminPrincipal`, and reason; append-only events record review/application/failure. Under `producer_write()` it creates and seals a new processing version, advances the semantic-invalidation revision for changes declared incompatible with an already prepared generation, appends a structural dirty-revision row, and never changes serving authority directly. Proposal decisions and interpretation overrides are immutable revision streams selected explicitly by later generation manifests.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_mappings.py tests/unit/test_economic_taxonomy_operations.py -q`

Expected: PASS; historical legacy interpretation remains reproducible after split and later version publication, and no caller-provided actor string reaches durable authority fields.

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

def test_fundamental_attention_is_unsigned(metrics):
    positive = metrics.calculate(theme=fundamental_report(direction="positive"), as_of=NOW)
    negative = metrics.calculate(theme=fundamental_report(direction="negative"), as_of=NOW)
    assert positive.fundamental_attention.raw == negative.fundamental_attention.raw

def test_one_theme_cohort_gets_percentile_100(metrics):
    assert metrics.rank([available_theme()])[0].percentile == 100

def test_reactivated_theme_can_become_dormant_again(lifecycle):
    established = lifecycle.evaluate(provisional_theme_with_breadth(), as_of=DAY_30)
    dormant = lifecycle.evaluate(established, as_of=DAY_121)
    reactivated = lifecycle.evaluate(dormant_with_two_new_families(), as_of=DAY_130)
    dormant_again = lifecycle.evaluate(reactivated, as_of=DAY_221)
    assert [established.state, dormant.state, reactivated.state, dormant_again.state] == [
        "established", "dormant", "reactivated", "dormant",
    ]
    assert dormant_again.reactivated_at == reactivated.reactivated_at
```

- [ ] **Step 2: Run tests and confirm services are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement exact V1 calculations**

Use selected primary observations and UTC `available_at` with closed windows `[as_of - window, as_of]`; decay is `2 ** (-age_seconds / half_life_seconds)`. Technical Attention uses 30 days, seven-day half-life for roots, five-day half-life for accepted signals, and weight `1.0` for every V1 signal type. For each `(source_family, theme, UTC day)`, take the maximum decayed root-or-signal contribution so duplicate signals cannot multiply weight. Fundamental Attention is an unsigned 90-day/30-day-half-life count. Narrative Attention uses 14 days/three-day half-life. Emerging is `families_7d - families_prior_21d / 3`, available only for provisional/reactivated themes with two families on two dates in the last seven days. Broad Confirmation is the arithmetic mean of available channel percentiles and requires two channels plus two distinct source families.

Rank non-empty cohorts with `100 * (average_rank - 1) / (n - 1)`, average ranks for ties, and percentile `100` when `n == 1`. UUID is stable display ordering only and never a score tie-break. Missing is `unavailable`, never imputed zero. Persist formula version, as-of, interpretation set, generation-input manifest, pinned eligibility revisions, component availability, raw values, and ranked values.

- [ ] **Step 4: Implement lifecycle as processing proposals**

Apply the exact policy-versioned thresholds: provisional to established needs three direct primary roots, two source families, and two dates in 30 days plus either two accepted constituent securities or an authenticated reviewed multi-security breadth assertion; established to dormant needs no direct primary root for 90 days; dormant to reactivated needs two direct roots from two families in 14 days; retirement is reviewed only. Treat `reactivated` as established for inactivity evaluation: after 90 days without a direct primary root it returns to `dormant`, while append-only lifecycle events preserve the reactivation timestamp/history. It does not need a synthetic `reactivated -> established` transition. Under `producer_write()`, create a sealed processing snapshot through Task 9 operation machinery and append a lifecycle dirty-revision row; do not update serving pointers. Treat the 90-day and two-family choices as deliberate V1 policy, not placeholders.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py -q`

Expected: PASS with deterministic as-of results, policy/version provenance, and an established → dormant → reactivated → dormant cycle.

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
- Consumes: Task 3 fence, selected generation inputs, projection key, legacy discovery writes.
- Produces: `stage_projection()`, `claim_deliveries_from_published_generations()`, optional `notify_delivery_workers()`, `apply_delivery()`, and per-lineage `ProjectionCheckpoint`.

- [ ] **Step 1: Write failing epoch-retry, ordering, recursion, and writer-race tests**

```python
def test_retry_after_epoch_change_reuses_logical_event(outbox):
    first = outbox.stage_projection(source_lineage="post:1", projection_revision=2, epoch=10)
    retry = outbox.stage_projection(source_lineage="post:1", projection_revision=2, epoch=11)
    assert retry.id == first.id

def test_older_delivery_cannot_restore_state(target):
    target.apply(revision=2, payload={"name": "new"})
    target.apply(revision=1, payload={"name": "old"})
    assert target.name == "new"

def test_empty_replacement_retracts_only_its_lineage(target):
    target.apply(lineage="a", revision=1, payload={"themes": ["memory"]})
    target.apply(lineage="b", revision=1, payload={"themes": ["memory"]})
    target.apply(lineage="a", revision=2, payload={"themes": []})
    assert target.supporting_lineages("memory") == {"b"}

def test_delivery_eligibility_comes_from_publication_history(outbox):
    published = outbox.stage_projection(generation="g2", source_lineage="a", projection_revision=2)
    abandoned = outbox.stage_projection(
        generation="g-abandoned", source_lineage="b", projection_revision=1
    )
    append_generation_event("g2", "published")
    append_generation_event("g2", "superseded")
    append_generation_event("g-abandoned", "abandoned")
    assert outbox.claimable_ids() == {published.id}
    assert abandoned.id not in outbox.claimable_ids()
```

- [ ] **Step 2: Run tests and confirm outbox service is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_outbox.py tests/unit/test_economic_taxonomy_legacy_adapter.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Implement logical events, attempts, and target checkpoints**

Unique logical key is `(source_lineage, projection_revision, projection_kind, projection_version, target)` and excludes epoch. Advance the monotonic projection revision whenever selected attempt, reviewed allocation/redirect, applicable eligibility, or membership decision changes, even if source bytes do not. A mapping or redirect change fans out new revisions to every affected lineage rather than using one ambiguous global event. Each delivery attempt records claimed epoch, lease, outcome, and error. The target stores the last applied revision per lineage/projection kind and compare-and-sets only newer revisions. Payloads are complete replacement state for one lineage; an empty payload retracts that lineage without touching other lineages. Payloads contain selected interpretation/mapping versions and `origin_representation`; applying a mirror suppresses reverse event generation.

- [ ] **Step 4: Stage candidate-generation payloads and gate live delivery**

Shadow mode writes comparison payloads only to shadow projection storage. Generation preparation stages complete candidate payloads durably and binds each event to its generation; unselected attempts never change the live legacy representation. `claim_deliveries_from_published_generations()` derives eligibility by joining staged events to that generation's append-only successful `published` event, not a mutable `released` flag or only the current authority pointer. A later `superseded` event does not hide undelivered work; projection checkpoints make obsolete deliveries safe no-ops. Events whose generation has only `prepared` or `abandoned` history are never claimable. Post-commit queue notification is a wake-up optimization only, so worker polling recovers a publisher crash.

A mode-changing cutover requires acknowledgement through the prior accepted generation plus staged candidate payloads. Routine economic publication may deliver the new generation asynchronously and marks rollback temporarily unavailable until required acknowledgements arrive. Publication never waits for delivery.

- [ ] **Step 5: Route legacy producers through the shared fence**

Provider work remains outside transactions. Every legacy theme mutation starts with `producer_write()`, locks existing registry/grouping rows only after authority, writes its source revision and domain change atomically, and emits the appropriate shadow/dual compatibility event.

- [ ] **Step 6: Run PostgreSQL ordering and cutover-race tests**

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_outbox_postgres.py -q`

Expected: out-of-order delivery is harmless, corrected-to-empty or same-byte reclassification replaces only that lineage, unselected/abandoned results never affect live legacy, published events remain discoverable after supersession without a release flag, recursive emission is absent, and an old-mode writer cannot commit after epoch switch.

- [ ] **Step 7: Commit fenced compatibility delivery**

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
- Produces: stable `EconomicSocialAssociation`, append-only `EconomicSocialAssociationRevision`, `EconomicSocialDecisionRevision`, `EconomicSocialAssociationSource`, live-admission/reconciliation service, generation-pinnable projection revisions, and pending legacy mirror state.

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

def test_lens_only_change_reuses_existing_artifacts_and_budget(adapter, saved_work, budget):
    first = adapter.process(saved_work)
    second = adapter.add_eligibility(first.packet_id, "fundamental")
    assert second.extraction_artifact_id == first.extraction_artifact_id
    assert budget.additional_reservations == 0

def test_same_pair_keeps_accepted_and_rejected_revisions_for_historical_generations(
    adapter, legacy_rows
):
    before = snapshot_legacy_rows(legacy_rows)
    association = adapter.get_or_create_association(theme_id="memory", security_id=42)
    accepted = adapter.revise(association.id, state="accepted", idempotency_key="decision-1")
    g1 = generation_selecting(association.id, accepted.revision_number)
    rejected = adapter.revise(association.id, state="rejected", idempotency_key="decision-2")
    retry = adapter.revise(association.id, state="rejected", idempotency_key="decision-2")
    g2 = generation_selecting(association.id, rejected.revision_number)
    assert [accepted.revision_number, rejected.revision_number] == [1, 2]
    assert retry.id == rejected.id
    assert adapter.membership(g1).state == "accepted"
    assert adapter.membership(g2).state == "rejected"
    assert adapter.membership(g2).live is False
    assert snapshot_legacy_rows(legacy_rows) == before

def test_late_social_archive_cannot_restore_corrected_empty(adapter, corrected_empty_post):
    late = adapter.process(archived_saved_work(corrected_empty_post, provider_revision=None))
    assert late.precedence_state == "hold_review"
    assert adapter.current_assignments(corrected_empty_post.lineage_id) == ()

def test_social_retry_uses_two_budget_attempts_then_reuses_success(
    adapter, provider, budget, saved_work
):
    provider.side_effects = [
        RetryableProviderError(provider_request_id="r1", actual_cost=ZERO),
        accepted_payload("Memory"),
    ]
    with pytest.raises(RetryableProviderFailure):
        adapter.process(saved_work)
    success = adapter.process(saved_work)
    repeated = adapter.process(saved_work)
    assert budget.attempt_states == ["reconciled", "reconciled"]
    assert len(set(budget.attempt_ids)) == 2
    assert success.extraction_artifact_id == repeated.extraction_artifact_id
    assert provider.call_count == 2

def test_unknown_outcome_timeout_remains_uncertain_until_retry_policy_allows(
    adapter, budget, saved_work
):
    result = adapter.record_timeout(saved_work, provider_dispatch_confirmed=True)
    assert result.attempt.state == "uncertain"
    assert budget.reservation_is_open(result.attempt.id) is True
    assert adapter.retry_now(result.logical_request_id).status == "provider_outcome_uncertain"
```

- [ ] **Step 2: Run tests and confirm global projection is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_social_adapter.py tests/unit/services/test_social_llm_budget.py -q`

Expected: FAIL on global projection import.

- [ ] **Step 3: Implement separate global association and many-to-many bridge**

Do not add economic uniqueness to `SocialThemeAssociation`. Create stable `EconomicSocialAssociation` identity with `UNIQUE(economic_theme_id, security_id)`, where `security_id` is `stock_universe.id`. Store history in `EconomicSocialAssociationRevision` with `UNIQUE(association_id, revision_number)` and idempotent decision keys; never put pair-only uniqueness on the revision table. `EconomicSocialDecisionRevision`, bridges, generation manifests, and reader projections reference the intended immutable association revision. Bridge every contributing legacy association/evidence work row and preserve legacy decision rows. Matching decisions consolidate; a rejection prevents accepted membership; mixed administrator accept/reject becomes `conflict_review_required` and remains out of accepted membership. Never resolve conflict by processing order.

- [ ] **Step 4: Implement live admission and compatibility mirroring**

Only published, succeeded, policy-admitted saved work with effective Task 5 evidence precedence contributes narrative evidence. Proposed, rejected, unpublished, exploratory, late-archive `hold_review`, and partial-recapture `hold_review` work stays review-only. A later Social admission ordinal alone cannot revive obsolete claims. Constituent decisions remain separate from evidence admission. New global membership begins `pending_legacy_mirror`; an ordered event creates/reuses the legacy compatibility cluster and association without requiring an existing non-null legacy association, then acknowledgement permits live acceptance while rollback compatibility is required. Each generation pins the exact association revision, decision revision, and projection revision, so later administrator action cannot alter an old generation.

- [ ] **Step 5: Reserve/reconcile every additional provider call outside projection locks**

Use the existing `SocialLLMAttempt` as Social's concrete provider-attempt and budget record rather than creating a parallel attempt authority. Extend it with stable logical operation key, operation kind, and attempt number as needed; each actual provider dispatch gets a distinct idempotency key. Reserve before each call, mark dispatched, and reconcile known success/failure afterward; only then enter the short fenced projection transaction. Known pre-dispatch failure releases the reservation. Transient failure preserves its attempt and schedules retry with a new attempt key. Timeout with unknown provider outcome remains `uncertain` and retains conservative budget treatment until the existing Social budget policy permits reconciliation or another call. Reusing a successful artifact consumes no new budget. Do not infer exactly-once provider billing from request idempotency.

- [ ] **Step 6: Run unit and PostgreSQL Social tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_social_adapter.py tests/unit/services/test_social_llm_budget.py -q`

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_social_postgres.py tests/integration/test_social_theme_projection.py -q`

Expected: historical legacy rows/decisions remain unchanged; stable pair identity accepts multiple immutable revisions; G1/G2 retain their selected accepted/rejected states; identical revision retries are idempotent; conflicts, unpublished work, and stale/partial captures remain non-live; retryable calls have truthful per-call reservations while uncertain outcomes stay conservatively blocked.

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
- Produces: narrative `analysis_channel`, economic development links, append-only `LegacyDevelopmentEventMapping`, generation-pinnable development selection revisions, and one current canonical event identity across dual routes.

- [ ] **Step 1: Write failing Social-native and deduplication tests**

```python
def test_social_native_development_has_narrative_provenance(service):
    row = service.record(source=social_packet(), channel="narrative", themes=[theme_id])
    assert row.analysis_channel == "narrative"
    assert row.economic_theme_links[0].economic_theme_id == theme_id

def test_legacy_duplicate_identity_is_preserved_and_resolves_canonical(service, duplicates):
    result = service.migrate_duplicates(duplicates)
    assert result.legacy_mapping_count == len(duplicates)
    assert {service.current_event(row.id) for row in duplicates} == {result.canonical_event_id}
    assert all(row.historical_links_unchanged for row in duplicates)
```

- [ ] **Step 2: Run tests and confirm narrative is rejected**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_developments.py tests/unit/test_theme_development.py -q`

Expected: FAIL because existing `record_developments()` accepts only technical/fundamental.

- [ ] **Step 3: Migrate and extend the existing event authority**

Move channel provenance to development observations with `analysis_channel=technical|fundamental|narrative`, backfilled from the existing pipeline value. Use canonical source-family and event keys for new writes. Preserve duplicate legacy event rows and their attached historical observations/links; add append-only `LegacyDevelopmentEventMapping(old_event_id, canonical_event_id, old_pipeline, migration_run_id)` so current readers resolve one canonical event without deleting or silently repointing history. Add Economic Theme link rows; compatibility delivery creates legacy links without creating a second current event.

- [ ] **Step 4: Fence development writes and use separate support states**

Normalize provider work before the transaction, then persist event/observations/links, an append-only development selection revision, and dirty source revision under `producer_write()`. Accept presence support `present|absent|unresolved` separately from claim support and existing classification/uncertainty state; never pass `absent` as exposure support. Generation manifests pin the selected development observation/selection revisions.

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
    assert payload["generation_input_manifest_hash"] == payload["generation"]["generation_input_manifest_hash"]

def test_historical_generation_is_reproducible(client, old_generation):
    response = client.get(f"/api/v1/economic-themes?generation_id={old_generation.id}")
    assert response.json()["generation_id"] == old_generation.id

def test_interpretation_set_without_generation_is_not_a_product_read(client, interpretation_set):
    response = client.get(f"/api/v1/economic-themes?interpretation_set_id={interpretation_set.id}")
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests and confirm routers are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_theme_api.py tests/unit/test_economic_taxonomy_api.py tests/unit/test_economic_theme_ui_snapshot.py -q`

Expected: FAIL on import or 404.

- [ ] **Step 3: Implement generation-scoped schemas and read endpoints**

Return generation, taxonomy version, interpretation set, generation-input manifest hash, metrics revision, availability states, direct/derived counts, signals, constituents, developments, relationships, mappings, and reconciliation state. Include the pinned evidence-precedence, eligibility, constituent-decision, Social association/decision, development, override, mapping/redirect, metrics-policy, and compatibility revisions used by the payload. Default reads resolve one serving generation at request start; explicit historical reads require a generation ID. An interpretation-set ID alone is insufficient for product reads.

- [ ] **Step 4: Build immutable snapshot bundles without switching pointers**

`build_snapshot_bundle()` takes explicit taxonomy/interpretation/complete-manifest/metrics inputs and writes draft payload rows, validates every referenced theme/facet exists in the same snapshot, and performs the single audited seal transition with hashes. Later changes to auxiliary revisions must not alter the sealed bundle. Pointer switching is reserved for Task 16.

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
- Produces: sealed `TaxonomyMigrationRun`, append-only `TaxonomyMigrationProgressEvent`, `build_migration()`, `review_disposition()`, `replay_manifest()`, and a fail-closed benchmark report bound to taxonomy and policy hashes.

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

Seal immutable run inputs, source hashes, taxonomy/policy hashes, and migration policy identity. Record start, progress, pause, failure, review, replay, and completion as append-only `TaxonomyMigrationProgressEvent` rows; mutable counters are caches only. Persist dispositions, destinations, allocations, exclusions, trusted reviewer principal, and reason. Many-to-one merges reuse one global identity; one-to-many splits stay incomplete until every current claim is allocated. Backfill and replay commits use `producer_write()` and append migration dirty-revision rows so the final manifest covers migration state.

- [ ] **Step 4: Implement exact manifest replay and benchmark fixtures**

Replay sorted committed revision-log tuples, not sequence maxima. Every fixture declares required and forbidden identities, relationships, assignments, interpretation selections, and retractions; any mismatch makes the script exit nonzero. Include pseudo-theme rejection, tanker segmentation, AI/Memory co-occurrence, AI Memory/HBM specificity, AI Security mechanism contrast, Copper direction, Refining split, Social consolidation/conflict, same-source reclassification, successful empty correction, first-admitted late archive after corrected-empty, less-complete recapture after attachment-backed evidence, and duplicate-route deduplication.

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
- Consumes: processing head, interpretation builder, metrics, snapshot builder, bounded cutoff/manifest, semantic-invalidation revision, capability, compatibility checkpoints, exclusive fence, and trusted administrator/service principal.
- Produces: `capture_cutoff()`, `prepare_generation(cutoff)`, `publish_generation()`, `prepare_cutover()`, `publish_cutover()`, and `rollback()`.

- [ ] **Step 1: Write failing preparation, manifest-change, and rollback tests**

```python
def test_prepare_builds_all_artifacts_from_one_manifest(coordinator):
    generation = coordinator.prepare_generation(coordinator.capture_cutoff())
    assert generation.interpretation_set.generation_input_manifest_id == generation.manifest_id
    assert generation.metrics.generation_input_manifest_id == generation.manifest_id
    assert generation.snapshot_bundle.generation_input_manifest_id == generation.manifest_id

def test_ordinary_post_cutoff_revision_does_not_abort(coordinator):
    prepared = coordinator.prepare_generation(coordinator.capture_cutoff())
    coordinator.append_ordinary_revision()
    coordinator.publish_generation(prepared.id)
    assert coordinator.authority().serving_generation_id == prepared.id

def test_structural_invalidator_aborts_without_switch(coordinator):
    prepared = coordinator.prepare_generation(coordinator.capture_cutoff())
    coordinator.append_structural_invalidation()
    with pytest.raises(ManifestChanged):
        coordinator.publish_generation(prepared.id)
    assert coordinator.authority().serving_generation_id != prepared.id

def test_crash_after_publication_commit_cannot_strand_compatibility_events(
    coordinator, delivery_worker, fault
):
    prepared = coordinator.prepare_generation(coordinator.capture_cutoff())
    fault.raise_after("publication_commit_before_notification")
    with pytest.raises(InjectedCrash):
        coordinator.publish_generation(prepared.id)
    delivery_worker.run_without_publish_notification()
    delivery_worker.run_without_publish_notification()
    assert coordinator.generation(prepared.id).has_event("published")
    assert coordinator.compatibility_checkpoint(prepared.id).acknowledged is True
    assert coordinator.compatibility_checkpoint(prepared.id).applied_effect_count == 1
    next_generation = coordinator.prepare_generation(coordinator.capture_cutoff())
    coordinator.publish_generation(next_generation.id)
    assert coordinator.authority().serving_generation_id == next_generation.id

def test_abandoned_generation_events_are_never_delivered(coordinator, delivery_worker):
    prepared = coordinator.prepare_generation(coordinator.capture_cutoff())
    coordinator.abandon(prepared.id, reason="stale_parent")
    delivery_worker.run()
    assert coordinator.compatibility_checkpoint(prepared.id).delivery_count == 0
```

- [ ] **Step 2: Run tests and confirm coordinator is absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_publication.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Capture a bounded committed cutoff under a short fence**

In a short transaction, acquire `exclusive_publication()`, drain shared writers, lock authority, and capture committed cutoff C, the complete `GenerationInputManifest`, processing taxonomy/version revision, expected parent generation, and semantic-invalidation revision. Release immediately. The manifest contains exact typed committed revision tuples rather than sequence maxima. Work committed after C belongs to the durable `> C` backlog and cannot starve this generation.

- [ ] **Step 4: Implement preparation outside the exclusive lock**

From frozen C, build and seal the interpretation set, metrics revision, UI/API snapshot bundle, complete candidate-generation compatibility payloads, and immutable serving-generation payload. Verify benchmark output and reader capability. Require compatibility acknowledgement through the previously accepted generation and staged candidate payloads; do not wait for candidate delivery. Append `prepared`. No authority pointer changes occur here.

- [ ] **Step 5: Implement the short final compare-and-set barrier**

Under `exclusive_publication()`, lock authority and verify manifest integrity, artifact hashes, expected parent generation, captured semantic-invalidation revision, prior-generation compatibility acknowledgements, staged candidate payloads, reader capability, and snapshot hashes. Do not require equality with ordinary revisions committed after C. If the parent or a declared structural invalidator changed, append `abandoned`, release, and prepare again outside the transaction. Otherwise switch serving generation and reader pointers, optionally mode, increment epoch, record catch-up cursor C, and append `published` plus prior-generation `superseded` in the same commit.

That committed `published` event is the durable compatibility-delivery eligibility record used by Task 11 workers. Do not depend on a later release-state write. A post-commit queue notification may wake workers but carries no authority; a crash before notification is recovered by ordinary polling. Publication never waits for delivery. Superseded published generations remain eligible until their staged events are delivered or made harmless by newer projection checkpoints; abandoned generations never become eligible.

- [ ] **Step 6: Implement catch-up and rollback recovery outside the barrier**

Replay and drain outside publication. Routine economic publication may expose its generation before all new mirrors acknowledge, but records rollback as temporarily unavailable until required checkpoints catch up. If compatibility is unhealthy when rollback is requested, append durable `rollback_recovery`, restrict authoritative writes, rebuild ordered complete-lineage legacy projections from the current generation, verify checkpoints, prepare a legacy generation, then use the normal coordinator and barrier. Mode changes, manual publication, and recovery require trusted `AdminPrincipal`.

- [ ] **Step 7: Run PostgreSQL race and liveness matrix**

Run: `cd backend && STOCKSCANNER_TEST_ALLOW_POSTGRES=1 DATABASE_URL=postgresql://ci:ci@localhost:5432/ci ./venv/bin/pytest tests/integration/test_economic_taxonomy_publication_postgres.py -q`

Expected: existing source change, late lower-ID commit, blocked outbox, evidence after snapshot construction, continuous arrivals, stale parent, structural invalidation, old writer race, crash after publication commit/before notification, abandoned candidate, injected pre-commit crash, and unhealthy rollback all end with one coherent old or new generation and no deadlock. Published events are eventually checkpointed exactly once in effect, abandoned events are never delivered, and ordinary post-C revisions publish later without invalidating the candidate.

- [ ] **Step 8: Run unit tests and commit**

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
- Produces: Celery tasks `discover_economic_taxonomy_work`, `process_economic_taxonomy_work`, `deliver_taxonomy_outbox`, `refresh_economic_taxonomy_generation`, `apply_economic_theme_lifecycle`, and `calculate_economic_theme_metrics`.

- [ ] **Step 1: Write failing mode, budget, and bounded-batch tests**

```python
def test_legacy_mode_processing_is_noop(task, authority):
    authority.mode = "legacy"
    assert task.run(limit=50) == {"status": "skipped", "reason": "legacy_mode"}

def test_batch_never_exceeds_limit(task, queued_work):
    assert task.run(limit=10)["claimed"] <= 10

def test_economic_refresh_coalesces_to_one_generation_per_five_minutes(refresh, clock):
    refresh.run()
    clock.advance(minutes=4)
    assert refresh.run()["reason"] == "coalesced"

def test_review_required_structural_change_is_held(refresh, merge_proposal):
    assert refresh.run()["held_revision_ids"] == [merge_proposal.revision_id]

def test_delivery_poll_recovers_missing_publish_notification(delivery, published_without_notification):
    result = delivery.run()
    assert result.claimed_generation_ids == [published_without_notification.id]
    assert result.checkpointed == 1

def test_delivery_poll_ignores_abandoned_generation(delivery, abandoned_generation):
    result = delivery.run()
    assert abandoned_generation.id not in result.claimed_generation_ids
```

- [ ] **Step 2: Run tests and confirm tasks are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_taxonomy_celery_contract.py -q`

Expected: FAIL on task import/registration.

- [ ] **Step 3: Implement bounded entry points**

Provider work uses no publication lock; persistence uses the shared fence. Discovery/processing runs in shadow, dual, and economic modes. Delivery polls staged events joined to append-only successful publication history, including superseded published generations, and retries ordered logical events; it does not require a publisher notification or current-generation match and ignores prepared/abandoned generations. Lifecycle and metrics target explicit processing/interpretation inputs. Classify dirty log entries as routine or review-required. Routine includes evidence, eligible provisional discovery, accepted decision revisions, lifecycle evaluation, and metrics refresh. Hold unknown dimensions, ambiguous identities, merges, splits, retirements, defining-mechanism changes, and all other review-required structural proposals.

- [ ] **Step 4: Implement automatic routine economic-mode publication**

Every minute in economic mode, inspect dirty revisions and coalesce them into at most one publication per five-minute window. Use fixed principal `system:economic-taxonomy-refresh`, capture a bounded cutoff, prepare, and publish through Task 16's same coordinator. Reuse the deployed reader capability for data-only generations. Compare-and-set the expected parent, retry infrastructure failures with exponential backoff capped at five minutes, and leave a durable backlog so every committed revision is eventually considered. Never create one generation per source. Shadow/dual preparation and every mode change remain operator-controlled.

- [ ] **Step 5: Register existing queues and schedules**

Use the existing `celery` queue: discovery every five minutes, delivery every minute, lifecycle daily at 02:10 configured timezone, metrics after current theme metrics, and refresh polling every minute. The refresh task returns a no-op outside economic mode and enforces the five-minute coalescing window. Add no worker process.

- [ ] **Step 6: Run task contracts and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_taxonomy_celery_contract.py tests/unit/test_theme_discovery_ingestion_tasks.py tests/unit/test_social_worker_compose_contract.py -q`

Expected: PASS, including recovery of published compatibility work after a missed notification and exclusion of abandoned-generation events.

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

Show `Technical Attention`, unsigned `Fundamental Attention`, `Narrative Attention`, `Emerging`, and `Broad Confirmation`, all with explicit unavailable states; do not expose a `Fundamental Momentum` label. Also show stable identity details; facets/relationships; direct versus derived evidence; deduplicated source-family counts; structured signals; developments; constituents; split allocations; Social decision conflicts; preview hash; reviewer reason; and stale-preview refresh. Legacy/shadow/dual show existing production UI plus admin preview; economic shows the global UI.

- [ ] **Step 6: Register reader capability only after contract tests pass**

Build `ReaderCapabilityManifest(backend_contract=1, frontend_contract=1, migration_version="0054", consumer_test_hash=<test inventory hash>)`. The release command persists it only after backend consumer tests, frontend tests, and build succeed. Task 16 may reuse this verified capability for later data-only generations; any software, schema, or reader-contract change requires a newly verified capability manifest.

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
- Modify: `docs/superpowers/plans/2026-09-21-economic-taxonomy.md`
- Test: `backend/tests/unit/test_required_economic_taxonomy_postgres.py`
- Test: `backend/tests/unit/test_economic_taxonomy_runbook.py`

**Interfaces:**
- Consumes: every prior task.
- Produces: exact PostgreSQL gate, reader-ready release artifact, and catch-up/barrier/recovery procedures.

- [x] **Step 1: Write failing gate and runbook contract tests**

```python
def test_required_gate_rejects_skipped_node(tmp_path, fake_pytest):
    result = run_required_tests(manifest_with("test_cutover_race"), fake_pytest.skip_it())
    assert result.exit_code != 0

def test_runbook_names_catchup_barrier_and_recovery():
    text = RUNBOOK.read_text()
    for phrase in (
        "catch-up outside the publication transaction",
        "exclusive writer fence", "generation-input manifest",
        "reader capability", "rollback_recovery",
    ):
        assert phrase in text
```

- [x] **Step 2: Run tests and confirm gate/runbook are absent**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_required_economic_taxonomy_postgres.py tests/unit/test_economic_taxonomy_runbook.py -q`

Expected: FAIL on missing script/runbook.

- [x] **Step 3: Implement the exact-node PostgreSQL runner**

Read non-comment node IDs, run `pytest --collect-only`, fail if any ID is absent, then execute with a plugin that counts pass/fail/skip/xfail/xpass. Exit nonzero unless every listed node passed and PostgreSQL identity was verified. Include snapshot sealing, fence, work, processing publication, outbox, Social, and publication race suites.

The exact-node manifest must include PostgreSQL versions of the new critical contracts: concurrent provider-attempt numbering, concurrent observation-only assignments without head advancement, two immutable Social revisions for one association pair, publication-commit crash before notification with worker recovery, and abandoned-generation delivery exclusion. Unit coverage for late archive/partial recapture precedence, dimension-definition hashing, retryable-versus-uncertain provider outcomes, and reactivated-to-dormant lifecycle remains mandatory in the focused suite below; Task 19 does not replace their owning task gates.

- [x] **Step 4: Add the CI gate**

```yaml
- name: Required economic taxonomy PostgreSQL contracts
  env:
    DATABASE_URL: postgresql://ci:ci@localhost:5432/ci
    STOCKSCANNER_TEST_ALLOW_POSTGRES: "1"
  run: cd backend && ./venv/bin/python scripts/run_required_economic_taxonomy_postgres.py
```

- [x] **Step 5: Write exact operator commands and stop conditions**

Document migration, seed, shadow, benchmark, reviewed dispositions/allocations, dual mode, catch-up outside the publication transaction, short cutoff capture, outbox drain, generation preparation, reader-capability verification, final compare-and-set barrier, `> C` backlog, automatic routine publication, publication verification, temporarily unavailable rollback, normal rollback, and `rollback_recovery`. Stop on unresolved allocations/conflicts, parent or semantic-invalidation mismatch, pending required prior-generation delivery, unstaged candidate projections, stale snapshot hash, missing reader capability, benchmark failure, unauthorized principal, or any skipped required PostgreSQL node. Ordinary revisions after C are backlog, not a stop condition.

- [x] **Step 6: Run focused backend and legacy regressions**

Run: `cd backend && THEME_REVIEW_TEST_DATABASE_URL=postgresql://ci:ci@localhost:5432/economic_taxonomy_ci ./venv/bin/pytest -q tests/unit/test_economic_taxonomy_contracts.py tests/unit/test_economic_taxonomy_snapshots.py tests/unit/test_economic_source_admission.py tests/unit/test_economic_taxonomy_work_repo.py tests/unit/test_economic_exposure_extraction.py tests/unit/test_economic_exposure_claim_review.py tests/unit/test_economic_taxonomy_processor.py tests/unit/test_economic_taxonomy_interpretations.py tests/unit/test_economic_taxonomy_mappings.py tests/unit/test_economic_theme_lifecycle.py tests/unit/test_economic_theme_metrics.py tests/unit/test_economic_taxonomy_outbox.py tests/unit/test_economic_taxonomy_social_adapter.py tests/unit/services/test_social_llm_budget.py tests/unit/test_economic_taxonomy_developments.py tests/unit/test_economic_taxonomy_publication.py tests/unit/test_economic_taxonomy_tasks.py tests/unit/test_economic_theme_read_service.py tests/unit/test_economic_theme_consumer_cutover.py tests/unit/test_required_economic_taxonomy_postgres.py tests/unit/test_economic_taxonomy_runbook.py tests/unit/test_theme_claim_review.py tests/unit/test_theme_state_authorities.py tests/unit/test_theme_development.py tests/integration/test_social_theme_projection.py`

Expected: PASS with zero skips in this focused set.

- [x] **Step 7: Run the required PostgreSQL gate and full frontend verification**

Run: `cd backend && DATABASE_URL=postgresql://ci:ci@localhost:5432/ci STOCKSCANNER_TEST_ALLOW_POSTGRES=1 ./venv/bin/python scripts/run_required_economic_taxonomy_postgres.py`

Run: `cd frontend && npm run test:run`

Run: `cd frontend && npm run build`

Expected: every manifest node passes with zero skips/xfails; full Vitest and production build pass.

- [x] **Step 8: Rehearse cutover and rollback recovery in disposable PostgreSQL**

Seed representative legacy themes, a Refining split, duplicate/conflicting Social associations, Social-native development, corrected-to-empty source, UI snapshots, and an out-of-order compatibility event. Run the exact runbook and record generation IDs, taxonomy/interpretation/manifest hashes, checkpoints, epoch, capability manifest, and post-rollback reader equivalence.

- [x] **Step 9: Verify deferred-work entry gates are documented and non-blocking**

Copy the `Deferred Work Boundary` below into the runbook's scope section. State that none of those capabilities is required for V1 cutover and that no implementation may begin until its listed decisions and evidence gate are approved. Verify no API/schema uses misleading reserved fields (especially `fundamental_momentum`) in anticipation of deferred direction work.

- [x] **Step 10: Mark the design/plan production-readiness gate and commit**

The design is approved for implementation, but update the design and plan to `production-ready` only after the rehearsal artifact is attached. Link the runbook to the design, ADR, and this plan.

```bash
git add backend/tests/required_economic_taxonomy_postgres.txt backend/scripts/run_required_economic_taxonomy_postgres.py .github/workflows/ci.yml docs/runbooks/economic-taxonomy-cutover.md docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md docs/superpowers/plans/2026-09-21-economic-taxonomy.md backend/tests/unit/test_required_economic_taxonomy_postgres.py backend/tests/unit/test_economic_taxonomy_runbook.py
git commit -m "docs: gate economic taxonomy publication"
```

---

## Deferred Work Boundary

The items in this section are intentionally excluded from Tasks 0-19 and do not block V1 implementation or cutover. They are not placeholders for an implementer to fill in opportunistically. Each requires a separately approved design/ADR and the stated entry evidence before work starts.

### Directional economic driver pack

V1 ships `fundamental_attention`, an unsigned measure of the amount and recency of selected fundamental evidence. It does not infer improving/deteriorating direction. A later driver pack may add directional observations, transmission paths, issuer materiality, and aggregation only after all of these decisions are settled:

1. **Driver vocabulary:** governed demand, pricing, volume, capacity, cost/input, margin, regulation, financing, and supply categories, including mixed, neutral, and unknown direction.
2. **Attribution grain:** whether direction belongs to a claim, company, constituent, theme, or development, and how a single claim spanning grains avoids duplication.
3. **Materiality:** required revenue/profit exposure data, estimates, confidence model, and versioning.
4. **Corroboration/dependence:** publisher ownership, shared upstream sources, syndication, copied text, correlated analysts, and the boundary between deduplication and statistical independence.
5. **Point-in-time semantics:** roles of `published_at`, UTC `available_at`, effective period, revision, and restatement in live views and backtests.
6. **Aggregation:** polarity scale, weights, decay, conflict netting, missing-data behavior, and absolute versus benchmark-relative scores.
7. **Evaluation:** labeled fixtures/dataset, reviewer workflow, acceptance thresholds, calibration, and drift monitoring.
8. **Provider/budget:** extraction schema and model versions, fallback behavior, stable attempt keys, and incremental budget policy.
9. **Persistence/publication/API:** append-only driver observations and decisions, correction-to-empty behavior, generation-input pinning, API names, and compatibility with historical `fundamental_attention` generations.

**Entry gate:** an approved driver-pack design and ADR answering all nine items, plus a representative labeled dataset and acceptance criteria. Until then, do not reserve a `fundamental_momentum` field, alias, or UI label.

### Other deferred capabilities

| Deferred capability | Decisions and evidence required before work starts |
|---|---|
| Remove legacy Theme/Social storage or compatibility writes | Rollback-support end date; retention/export policy; machine-checked consumer inventory proving zero legacy reads; compatibility health history; explicit irreversible-cleanup approval. |
| Automatically approve structural changes | Accountable owner; confidence thresholds; reversible remediation; blast-radius limits; audited evaluation for false-positive cost covering new dimensions, merges, splits, mechanism changes, and retirement. |
| Recursive ontology propagation | Maximum depth; cycle behavior; attenuation and deduplication rules; provenance/evidence display; product evidence that V1 one-hop derivation is insufficient. |
| General asset master beyond `StockUniverse` | Supported asset classes; identifier authority; corporate-action lifecycle; market coverage; ownership and migration plan; amendment to the ADR boundary with StockUniverse. |
| Statistical source independence | Operational dependence definition; publisher/source graph data; syndication detection; refresh cadence; validation that the signal improves decisions. Distinct source-family counts remain deduplication only. |

Task 19 must reproduce these boundaries in the operator runbook so a later cleanup or enhancement project cannot mistake V1 non-goals for already-settled contracts.

---

## Dependency Order

1. Task 0 is mandatory before any migration or schema implementation.
2. Tasks 1-3 establish sealed semantics, append-only interpretation history, serving generations, and the fence used by every writer.
3. Tasks 4-8 establish governed extraction, frozen admission, processing-head updates, and current interpretation selection.
4. Tasks 9-10 establish cardinality-safe governance, lifecycle, signals, and metrics.
5. Tasks 11-13 integrate every producer through the shared fence and ordered compatibility protocol.
6. Tasks 14-15 build coherent reader artifacts and migration inputs without changing production authority.
7. Task 16 is the only implementation allowed to change serving generation or mode.
8. Task 17 schedules bounded work and, only after economic mode, automatically coalesces eligible routine revisions through the same coordinator; review-required structural changes remain held.
9. Task 18 completes the authority-aware reader/frontend capability required by cutover.
10. Task 19 is the production release gate and cannot be waived by SQLite, manual spot checks, or unverified test collection.

Do not enter `dual` before Tasks 11-15 pass. Do not enter `economic` before Tasks 16-19 pass, the exact PostgreSQL gate reports zero skips/xfails, the benchmark is reviewed, and the reader capability manifest is ready. Do not remove legacy records or compatibility writes, add directional fundamental scoring, or implement another deferred capability in this project.

## Recommended Execution

Use **subagent-driven development**. The twenty tasks have crisp review boundaries, while mistakes in identity, interpretation selection, split allocation, Social decision preservation, fencing, or publication can silently corrupt historical meaning. Require a fresh implementation review after every task and a whole-branch review before the Task 19 rehearsal.
