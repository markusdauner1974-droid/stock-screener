# Open Multi-Dimensional Economic Taxonomy

**Status:** Approved for implementation

**Date:** 2026-09-20

**Implementation plan:** `docs/superpowers/plans/2026-09-21-economic-taxonomy.md`

**Replaces:** Pipeline-scoped/L1-L2 theme identity after a staged cutover; it does not delete legacy records.

## 1. Intent and success criteria

The Theme Catalog needs one global identity for each durable investable exposure, independent of whether the evidence arrived through technical, fundamental, or Social research. The system must distinguish semantic identity from developments, signals, facets, constituent roles, and analytical scores.

The change succeeds when:

- `AI Memory`, `Memory`, `HBM`, and `AI HBM` can coexist without accidental equivalence;
- co-occurrence of AI and memory does not create `AI Memory` without evidence connecting them;
- `AI-Powered Cybersecurity` and `AI Security` stay distinct when their economic mechanisms differ;
- technical and fundamental observations attach to the same global identity;
- Social research can discover or attach to that same identity without creating a legacy-only theme;
- derived observations never inflate independent-evidence counts;
- every published taxonomy is immutable and reproducible;
- migration, publication, and rollback expose one coherent authority at a time; and
- legacy records remain current enough for rollback until a later cleanup project explicitly retires them.

## 2. Domain definition

An **Economic Theme** is a durable investable exposure shared, or plausibly shareable, across multiple securities through a coherent economic transmission mechanism. A mechanism may involve a product, technology, commodity, end market, customer, supply chain, geography, policy, regulation, macro driver, infrastructure requirement, or industry economics.

Technical setups, strategies, and screening attributes are not Economic Themes. VCP, breakouts, relative-strength leadership, undercut-and-rally, high short interest, and similar concepts are signals or observations.

An Economic Theme states **what exposure exists**. A development states **what changed**. A facet describes **how the exposure is structured**. A constituent role states **how one security participates**. An analytical lens states **how the exposure currently measures**.

## 3. Invariants

1. **Global identity.** One Economic Theme is shared by technical, fundamental, and Social research.
2. **First-class compounds.** A supported compound such as `AI Memory` can coexist with its related themes.
3. **Relationship support.** Co-occurrence alone cannot support a compound.
4. **Narrowest supported specificity.** Missing specificity is unknown, not negative evidence.
5. **Similarity retrieves; semantics resolves.** Lexical and embedding similarity cannot authorize equivalence.
6. **Economic mechanism beats wording.** Similar names with different mechanisms remain distinct or ambiguous.
7. **Separate namespaces.** Economic Themes, facets, developments, signals, and constituent roles cannot substitute for one another.
8. **Immutable publication.** Published semantic content is never updated in place.
9. **One source family, honest evidence.** A source revision may support multiple distinct primary exposure claims, but related/derived themes share each claim's root and all claims share the source-family identity.
10. **Governed restructuring.** Automatic processing may add evidence, attach a candidate to one existing identity, or create a new provisional identity. Merging existing identities, splits, defining-mechanism changes, new dimensions, and retirement require review.

## 4. High-level flow

```text
Admitted source revision
        |
        v
Source-level Economic Taxonomy Work
        |
        v
Structured Exposure Extraction
        |
        v
Claim / Composition / Role Validation
        |
        v
Persisted Exposure Candidates
        |
        +----> Candidate Retrieval
        |       aliases / facets / lexical / embeddings / relationships
        |
        v
Semantic Identity Resolution
        |
        +--> equivalent -------> reuse identity
        +--> specialization ---> distinct narrower identity + edge
        +--> broader ----------> distinct broader identity + edge
        +--> related ----------> distinct identity + edge
        +--> distinct ---------> distinct identity
        +--> ambiguous --------> proposal / review
        |
        v
Primary Observations + Controlled Derived Observations
        |
        v
Lens Associations and Metrics
```

Extraction is source-level, not pipeline-owned. Lens associations retain the technical/fundamental/Social eligibility that caused the source to be observed.

## 5. Stable identity and immutable snapshots

### 5.1 Stable identity

`EconomicTheme` contains only stable identity:

```text
economic_themes
  id                  integer primary key
  semantic_key        opaque UUID string, unique, assigned once
  created_at
```

`semantic_key` is never derived from a display name, facets, or mechanism. Names and definitions can change without changing identity. Existing canonical-key normalization remains useful for alias lookup but is not global identity authority.

### 5.2 Full immutable taxonomy snapshots

Each taxonomy version contains a complete semantic snapshot. Theme volume is small enough that correctness and simple reads outweigh copy-on-write ancestry resolution.

```text
taxonomy_versions
  id, version, status, parent_version_id
  actor, reason, content_hash
  created_at, published_at, superseded_at

economic_theme_revisions
  taxonomy_version_id, economic_theme_id
  display_name, description, economic_mechanism
  lifecycle_state, naming_policy_version
  first_observed_at, established_at, dormant_at, reactivated_at, retired_at
  content_hash

economic_theme_aliases
  taxonomy_version_id, economic_theme_id
  alias_text, alias_key, source, confidence, evidence_count, review_state

facet_dimensions
  taxonomy_version_id, key, display_name, definition
  scope, cardinality_policy, status

facet_values
  taxonomy_version_id, dimension_key
  canonical_value, display_name, aliases, status, provenance

theme_facet_assignments
  taxonomy_version_id, economic_theme_id
  dimension_key, canonical_value
  support_status, evidence_refs, review_state

theme_relationship_assertions
  taxonomy_version_id, source_theme_id, target_theme_id
  relationship_type, differentiating_dimension_key, differentiating_value
  evidence_refs, derivation, confidence, provenance, status
```

Draft creation clones the complete parent snapshot. Structural operations modify only the draft. Publication seals the snapshot; application guards and database constraints reject semantic edits to published versions.

Store only the canonical `specializes` direction. `broader_than` is derived when reading. `related` and `distinct` are stored in canonical ID order to prevent reciprocal drift. Equivalence resolves to one identity plus aliases and migration mappings, not an equivalence edge.

### 5.3 Taxonomy authority

One singleton row is the authority seam:

```text
taxonomy_authority
  id = 1
  mode                  legacy | shadow | dual | economic
  active_version_id
  authority_epoch
  updated_at, actor, reason
```

All readers and writers load this row. Every authority transition increments `authority_epoch` under a row lock and the shared taxonomy advisory lock.

Mode semantics are explicit:

- `legacy`: production reads and writes use only the legacy catalog;
- `shadow`: production reads remain legacy; successful legacy writes enqueue Economic Taxonomy work, whose failures do not fail the legacy transaction;
- `dual`: production reads remain legacy; both representations are required, with a transactional outbox making cross-representation completion durable and observable; and
- `economic`: production reads use the sealed Economic Taxonomy version; accepted writes update the Economic Taxonomy path and continue compatibility writes to legacy through the same outbox.

Changing the mode or production `active_version_id` increments `authority_epoch`. Building drafts and processing observations against the current active version do not increment it.

`TaxonomySnapshot` is an immutable in-memory representation loaded exclusively from one sealed version. Its interface supplies identities, aliases, facets, relationships, lifecycle state, and content hash to callers.

### 5.4 Automatic provisional identities

When resolution is confidently `distinct`, automatic processing may create one provisional identity through a minimal draft cloned from the active snapshot. The publication path validates that the base version and candidate fingerprint are still current, obtains the publication lock, seals the new complete snapshot, and atomically advances `active_version_id` and `authority_epoch`. A stale base retries resolution against the new active snapshot. The source observation is committed only after the identity is published, preventing orphan or duplicate identities.

This path cannot merge identities, change an existing defining mechanism, introduce a facet dimension, split an identity, or retire a theme. Those changes require a reviewed proposal.

## 6. Governed facets and naming

Facet dimensions are governed and versioned; facet values are extensible within approved dimensions.

Initial dimensions:

```text
industry, product, technology, end_market, commodity, customer,
value_chain_role, shipping_segment, vessel_class, geography,
policy_driver, macro_driver, infrastructure_layer
```

Each dimension declares `scope` as `theme`, `constituent`, or `both`. For example, `value_chain_role=producer` may define a producer-oriented Economic Theme and may also describe one security's role in that theme.

Naming occurs after resolution:

1. reviewed manual override;
2. deterministic facet-composition rule;
3. constrained semantic naming; or
4. `requires_naming_review` when no safe name can be generated.

Source wording becomes a versioned alias. Renaming adds a new theme revision and retains the previous name as an alias unless review explicitly rejects it.

## 7. Structured extraction and claim validation

An `ExposureCandidate` contains:

```text
display_name_hint
economic_mechanism
compound
plausibly_multi_security
facet_claims[]
composition_support
constituent_claims[]
development_candidate
resolved_specificity
unresolved_narrower_candidates[]
evidence_refs[]
```

The existing grounding and untrusted-source protections remain upstream authorities. Existing claim-review vocabulary maps into the Economic Taxonomy domain as follows:

```text
supported   -> direct
inferred    -> inferred
unsupported -> unsupported
absent      -> absent (development only)
provider or coverage failure -> unresolved
```

Validation evaluates exposure support, each defining facet, compound composition, constituent role, development, and specificity independently. Unsupported composition rejects a compound identity. Unsupported development does not reject an otherwise supported exposure. Unsupported narrower specificity remains audit-only.

## 8. Durable work, candidates, and retry state

Shadow operation must not reuse `ContentItemPipelineState`; that state belongs to the legacy per-pipeline extractor.

```text
economic_taxonomy_work
  id
  source_kind             content_item | social_work
  source_id
  source_revision
  extraction_policy_version
  resolver_policy_version
  status                  pending | in_progress | processed | failed_retryable | failed_terminal
  attempt_count, lease_token, lease_until, next_attempt_at
  error_code, error_message
  claimed_authority_epoch
  created_at, updated_at, processed_at

economic_exposure_candidates
  id, work_id, candidate_ordinal, candidate_fingerprint
  candidate_json, claim_review_json
  resolution_outcome, resolution_json
  resolved_theme_id, taxonomy_version_id
  review_state, created_at, updated_at

economic_theme_embeddings
  taxonomy_version_id, economic_theme_id
  embedding, embedding_model, model_version
  semantic_content_hash, is_stale, created_at, updated_at

taxonomy_write_outbox
  id, event_key, source_kind, source_id, source_revision
  target_representation      legacy | economic
  payload_json, claimed_authority_epoch
  status, attempt_count, lease_token, lease_until, next_attempt_at
  error_code, error_message, created_at, updated_at, completed_at
```

The work uniqueness key is `(source_kind, source_id, source_revision, extraction_policy_version, resolver_policy_version)`. `source_revision` hashes the admitted primary content, attachment/evidence revision, preparation metadata, and saved Social input identity. Provider failures preserve the candidate/work audit and remain retryable.

The write outbox is inserted in the same transaction as the authoritative write. `event_key` makes delivery idempotent. Dual-mode cutover cannot proceed while required events are pending, leased, or dead-lettered.

## 9. Resolution

Candidate retrieval uses aliases, normalized lexical terms, compatible defining facets, embeddings, constituent overlap when useful, and existing relationships. It returns a bounded candidate set and retrieval reasons; it never returns an identity decision.

The semantic resolver emits:

```text
equivalent | specialization | broader | related | distinct | ambiguous
```

Only validated `equivalent` may reuse an identity automatically, and only when defining facets and economic mechanism are compatible. Ambiguous results create a review proposal. Provider failure remains unresolved and cannot fall back to string equality or embedding auto-merge.

## 10. Observations, source families, and developments

```text
theme_observations
  id, economic_theme_id
  source_kind, source_id, source_revision
  source_family_key
  claim_fingerprint
  observation_kind          primary | derived
  root_observation_id
  derivation_path, relationship_assertion_ids
  support_status, evidence_refs
  taxonomy_version_id
  extraction_policy_version, derivation_policy_version
  observed_at, extracted_at

theme_observation_lenses
  observation_id
  lens                      technical | fundamental | narrative
  eligibility_provenance

economic_theme_development_links
  observation_id
  development_observation_id
```

A source revision may produce multiple primary observations only for distinct supported exposure claims. Related broader/narrower/component observations are derived from one primary root. All roots from the same admitted source revision share `source_family_key`, so source-family counts remain one even when the source discusses multiple independent themes.

Propagation is one semantic hop plus explicitly approved compound/component paths. It never recursively floods a hierarchy.

The existing development-event module remains authoritative. Economic observations link to its observations rather than creating a second mutable development history. During dual mode, legacy and Economic Theme links are both written.

Metrics report direct observations, derived observations, unique roots, and unique source families separately.

## 11. Constituents and SecurityMaster identity

`security_id` means `stock_universe.id`, the persistent row resolved through SecurityMaster rules. Constituent evidence that cannot resolve to a `StockUniverse` row remains in the candidate audit and does not create a constituent exposure.

```text
theme_constituent_exposures
  taxonomy_version_id, economic_theme_id, security_id
  role_dimension_key, role_value
  support_status, evidence_refs
  source_observation_id, observed_at
```

Only admitted evidence may populate roles. Price strength does not establish business exposure or materiality.

## 12. Lifecycle policy

Lifecycle is versioned policy, not a lens score.

- A supported, plausibly multi-security exposure may create a `provisional` identity.
- Automatic establishment requires at least two unique source families, observations on at least two dates, and either two supported constituent identities or reviewed evidence explicitly establishing multi-security breadth.
- A reviewed operation may establish or retain a theme with recorded reason.
- A theme becomes `dormant` after 30 days without a direct root observation.
- A new direct root observation reactivates a dormant theme.
- `retired` is only a reviewed structural operation; inactivity alone never retires a theme.

Lifecycle transitions are append-only audit events and produce a new taxonomy version when they change published semantic state.

## 13. Reviewed operations and proposals

```text
taxonomy_proposals
  id, proposal_type, base_version_id
  before_json, after_json, affected_ids
  preview_hash, status
  evidence_refs, created_at, updated_at

taxonomy_operations
  id, proposal_id, parent_version_id, result_version_id
  operation_type, before_json, after_json
  actor, reason, applied_at, superseded_by_operation_id

taxonomy_migration_runs
  id, source_snapshot_at, source_high_watermarks
  target_version_id, status, content_hash
  created_at, reviewed_at, published_at

taxonomy_migration_dispositions
  migration_run_id, legacy_theme_cluster_id
  disposition, proposed_theme_id
  proposal_json, reason, review_state, reviewer, reviewed_at
```

Proposal types include new dimension, ambiguous identity, equivalence, split, defining-mechanism correction, retirement, and migration disposition. Preview hashes detect stale review. Applied operations create a complete draft snapshot; they never mutate a published snapshot.

## 14. Analytical lenses

One Economic Theme can be measured through:

- Technical Attention;
- Fundamental Momentum;
- Narrative Attention;
- Emerging; and
- Broad Confirmation.

`ThemePipelineMetrics` is keyed by `(economic_theme_id, lens, date, taxonomy_version_id)`. Signals such as VCP or breakout contribute to Technical Attention without becoming Economic Themes. Social Strength and Market Strength remain independent measures as required by the project domain model.

## 15. Social integration

The Social projection module is a producer, not only a reader, and must participate in shadow and dual modes.

- Saved Social extraction work is converted into source-level Economic Taxonomy work.
- Social theme claims use the same retrieval/resolution module as legacy content.
- `SocialThemeAssociation` gains nullable `economic_theme_id` during migration while retaining `theme_cluster_id` for rollback compatibility.
- Administrator decisions and evidence-work IDs remain authoritative and are not recreated in a parallel store.
- In shadow mode, Social writes legacy production records and Economic Taxonomy shadow records.
- In dual/economic mode, every accepted Social write maintains both mappings until a later cleanup project ends rollback compatibility.

## 16. Migration, cutover, and rollback

### 16.1 Required order

1. Add immutable schema, authority row, work/candidate storage, and pure policy.
2. Run legacy and Social shadow extraction/resolution.
3. Run the contrast benchmark and inspect drift.
4. Build a migration run with one disposition per active legacy identity.
5. Review splits, retirements, new dimensions, and unresolved mappings.
6. Transition to `dual`: production readers remain legacy by definition, while the durable outbox requires both representations to converge.
7. Build target-version UI snapshots and downstream projections.
8. Drain or fence old-epoch work, replay the final delta, and publish atomically.
9. Observe economic authority while continuing legacy compatibility writes.
10. Roll back by switching the authority row and matching snapshot pointers; keep Economic Taxonomy artifacts intact.

### 16.2 Writer fencing

Workers record `claimed_authority_epoch`. Before commit they lock and re-read the authority row. If the epoch changed, the transaction aborts and the work returns to retryable state. Publication therefore cannot race an in-flight old-mode writer into a mixed state.

### 16.3 Atomic reader publication

Theme UI snapshot revisions include `authority_epoch` and `taxonomy_version_id`. Target snapshots are built before publication. The authority row and theme snapshot pointers switch in one database transaction under the taxonomy advisory lock. APIs include authority epoch and taxonomy version in responses and refuse mismatched cached payloads.

### 16.4 Delta replay

Migration runs store high-watermarks for legacy content, Social work, development work, and structural operations. Final replay processes every source revision after the shadow snapshot, then verifies the high-watermarks while holding the publication lock.

### 16.5 Rollback compatibility

This project keeps compatibility writes to legacy Theme Catalog records after economic cutover. Consequently rollback does not expose a stale legacy catalog. Ending compatibility writes or deleting legacy tables requires a separate reviewed project.

## 17. Interfaces and adapters

New modules expose four deep interfaces:

- `EconomicTaxonomyProcessor.process(SourceRevision) -> ProcessingResult`
- `EconomicTaxonomyAuthority.snapshot() -> TaxonomySnapshot`
- `EconomicTaxonomyOperations.preview/apply(...)`
- `EconomicTaxonomyCutover.prepare/publish/rollback(...)`

Legacy extraction, Social projection, development processing, UI snapshots, stock-theme reads, digest, assistant, and MCP consumers use adapters at these seams. Callers do not manipulate taxonomy tables directly.

## 18. Failure outcomes

Stable outcomes include:

```text
unsupported_exposure
unsupported_composition
unresolved_specificity
ambiguous_identity
candidate_dimension
split_review_required
resolver_unavailable
claim_review_unavailable
authority_epoch_changed
source_revision_changed
stale_review_preview
publication_validation_failed
```

Uncertainty is persisted and reviewable. It never silently becomes equivalence or an established identity.

## 19. Testing and release gates

Unit and integration coverage must include:

- compound support and co-occurrence rejection;
- specificity and mechanism contrast cases;
- alias and embedding retrieval without identity decisions;
- immutable published snapshots and stale preview rejection;
- one source family across multiple roots and derived observations;
- Social and legacy producer parity;
- development-authority links;
- lifecycle transitions;
- authority-epoch writer fencing;
- UI snapshot/version coherence;
- post-snapshot delta replay;
- atomic publication failure and rollback; and
- SQLite migration round-trips plus real PostgreSQL concurrency tests.

The contrast benchmark covers Memory/HBM/AI Memory/AI HBM, both AI cybersecurity mechanisms, petroleum versus metals refining, crude versus product tankers, Copper/Copper Miners/downstream consumers, technical pseudo-themes, and Rate-Cut Beneficiaries. Results bind to taxonomy, extraction, resolver, naming, and derivation policy versions.

CI must run the PostgreSQL authority/concurrency suite with an explicitly configured disposable database. Skipped PostgreSQL variants do not satisfy the publication gate.

## 20. Non-goals

- Deleting legacy theme, mention, Social, or development records.
- Inferring issuer revenue materiality.
- Replacing evidence admission, grounding, SecurityMaster, Social administration, or development-event history.
- Recursive ontology propagation.
- A general asset master beyond the current `StockUniverse`-backed SecurityMaster identity.

## 21. Final decision

Implement structured economic-exposure extraction and semantic resolution behind a global Economic Theme identity. Published taxonomy content is represented by complete immutable snapshots. Source-level work produces persisted candidates and provenance-preserving observations; lens associations prevent duplicate extraction across technical and fundamental pipelines. A database authority epoch, writer fencing, dual-mode adapters, versioned UI snapshots, Social producer integration, and continuing legacy compatibility writes make shadow migration, cutover, and rollback coherent.
