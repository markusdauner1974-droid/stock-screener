# Open Multi-Dimensional Economic Taxonomy

**Status:** Revised contracts for review

**Date:** 2026-09-20

**Revised:** 2026-09-21

**Implementation plan:** `docs/superpowers/plans/2026-09-21-economic-taxonomy.md` is held pending approval of this revision. It must be rewritten before schema work begins.

**Replaces:** Pipeline-scoped/L1-L2 theme identity after a staged cutover; it does not delete legacy records.

## 1. Intent and success criteria

The Theme Catalog needs one global identity for each durable investable exposure, independent of whether the evidence arrived through technical, fundamental, or Social research. The system must distinguish semantic identity from evidence, classifications, developments, signals, facets, constituent roles, and analytical scores.

The change succeeds when:

- `AI Memory`, `Memory`, `HBM`, and `AI HBM` can coexist without accidental equivalence;
- co-occurrence of AI and memory does not create `AI Memory` without evidence connecting them;
- `AI-Powered Cybersecurity` and `AI Security` stay distinct when their economic mechanisms differ;
- technical, fundamental, and narrative evidence can attach to the same global identity;
- Social research can discover or attach to that identity without corrupting legacy Social decisions;
- a correction or reclassification replaces the current interpretation without deleting history;
- derived observations never inflate independent-evidence counts;
- every serving generation is immutable and reproducible from a taxonomy snapshot, interpretation selection, evidence cutoff, metrics revision, and reader snapshot;
- every authority-changing operation uses the same publication coordinator; and
- migration, publication, cutover, and rollback expose one coherent authority at a time.

## 2. Domain definition

An **Economic Theme** is a durable investable exposure shared, or plausibly shareable, across multiple securities through a coherent economic transmission mechanism. A mechanism may involve a product, technology, commodity, end market, customer, supply chain, geography, policy, regulation, macro driver, infrastructure requirement, or industry economics.

Technical setups, strategies, and screening attributes are not Economic Themes. VCP, breakouts, relative-strength leadership, undercut-and-rally, high short interest, and similar concepts are structured signals.

An Economic Theme states **what exposure exists**. A development states **what changed**. A facet describes **how the exposure is structured**. A constituent role states **how one security participates**. An evidence channel states **where support came from**. A ranking view states **how the exposure currently measures**.

## 3. Invariants

1. **Global identity.** One Economic Theme is shared by technical, fundamental, and narrative research.
2. **First-class compounds.** A supported compound such as `AI Memory` can coexist with its related themes.
3. **Relationship support.** Co-occurrence alone cannot support a compound.
4. **Narrowest supported specificity.** Missing specificity is unknown, not negative evidence.
5. **Similarity retrieves; semantics resolves.** Lexical and embedding similarity cannot authorize equivalence.
6. **Economic mechanism beats wording.** Similar names with different mechanisms remain distinct or ambiguous.
7. **Separate namespaces.** Economic Themes, facets, developments, signals, constituent roles, evidence channels, and ranking views cannot substitute for one another.
8. **Immutable publication.** Published semantic content, evidence packets, classification runs, assignments, interpretation sets, and serving generations are never updated in place.
9. **Explicit current interpretation.** Current reads select exactly one accepted interpretation per source lineage; they never union all historical classifications.
10. **Processing is not serving.** Extraction and taxonomy evolution can advance a processing head, but readers change only when a complete serving generation is atomically published.
11. **One source family, honest independence.** Duplicate ingestion routes share a canonical source family. Processing the same source twice never creates two independent confirmations.
12. **Governed restructuring.** Automatic processing may add evidence, attach a candidate to one existing identity, or create a provisional identity. Merges, splits, defining-mechanism changes, new dimensions, and retirement require review.
13. **Every producer is fenced.** Content, Social, development, migration, compatibility, and structural writers use the same pre-commit authority fence.

## 4. Chosen architecture

The design uses two immutable heads:

- a **processing taxonomy head**, against which new evidence is classified and proposed semantic changes are sealed; and
- a **serving generation**, which bundles a sealed taxonomy snapshot with accepted interpretations, metrics, reader snapshots, and the exact evidence manifest used to build them.

Provider calls, extraction, resolution, review, catch-up, metrics calculation, and UI snapshot construction happen outside the final publication transaction. A short publication transaction changes all authoritative reader pointers together.

```text
Canonical source family
        |
        v
Immutable admitted evidence packet ----> Lens-eligibility revision
        |
        v
Immutable classification run
        |
        v
Immutable claim assignments (zero or more)
        |
        +----> processing taxonomy head / reviewed proposals
        |
        v
Accepted interpretation set
        |
        v
Prepared serving generation
taxonomy + interpretation set + metrics + UI snapshots + evidence manifest
        |
        v
Short fenced publication transaction
        |
        v
Authoritative serving generation
```

This separation removes the crash window in which a newly visible identity exists without the evidence that justified it. It also prevents a source containing several new themes from invalidating its own work after every provisional identity.

## 5. Stable identity and sealed semantic snapshots

### 5.1 Stable identity

`economic_themes` stores identity only:

- UUID primary key;
- creation metadata; and
- immutable identity provenance.

Names, definitions, lifecycle state, aliases, facets, and relationships belong to a taxonomy version. Stable UUIDs survive renames, lifecycle changes, and compatible semantic refinement. A merge retires an identity through a versioned redirect; it does not reuse or rewrite the old UUID.

### 5.2 Taxonomy snapshots

`taxonomy_versions` is a state machine:

```text
draft -> sealed
```

A sealed version cannot return to draft. A draft is never served directly.

Version-owned rows include:

- complete `economic_theme_revisions` for every theme visible in that version;
- aliases;
- normalized facet values and theme-facet links;
- canonical relationships;
- lifecycle state;
- legacy dispositions, destinations, claim allocations, and redirects required by that version; and
- policy versions needed to interpret the snapshot.

Database constraints and deferred validation enforce:

- every version-owned reference targets a row present in the same snapshot;
- rows cannot be moved between versions;
- a sealed version and all of its owned rows are immutable;
- sealing takes a lock that prevents a concurrent draft mutation from slipping past validation or hashing;
- `specialization` edges are acyclic;
- an active `distinct` assertion cannot coexist with equivalence, a redirect, or a specialization between the same identities; and
- canonical relationship direction is unique.

The semantic snapshot hash is computed from sorted, normalized semantic values only: stable theme UUIDs, normalized revision content, alias values, facet dimension/value pairs, relationship endpoints/types, lifecycle state, dispositions, destinations, claim allocations, redirects, and policy identifiers. It excludes database row IDs, taxonomy-version IDs, timestamps, actor IDs, review comments, and other incidental metadata. A semantic clone therefore retains the same hash.

### 5.3 Authority and serving generations

`taxonomy_authority` is a singleton containing:

- `mode`: `legacy`, `shadow`, `dual`, or `economic`;
- `processing_taxonomy_version_id`;
- `processing_head_revision`;
- `serving_generation_id`;
- `authority_epoch`;
- `writes_fenced`; and
- rollback/recovery state.

`serving_generations` is immutable and contains:

- sealed taxonomy version;
- accepted interpretation-set ID;
- metrics revision ID;
- evidence-manifest ID and hash;
- UI/API snapshot bundle ID;
- reader-capability manifest ID;
- semantic content hash; and
- `prepared`, `published`, `superseded`, or `abandoned` state.

Only `taxonomy_authority.serving_generation_id` defines what readers see. The processing head is not a reader pointer.

### 5.4 One publication coordinator

Provisional creation, lifecycle transitions, reviewed merges/splits/renames, ordinary refreshes, migration cutover, and rollback all use `TaxonomyPublicationCoordinator`.

The coordinator has two phases.

**Prepare, outside the publication lock:**

1. Select a sealed processing taxonomy version.
2. Select completed classification runs into a new immutable interpretation set.
3. Build an exact committed evidence manifest.
4. Compute metrics from that interpretation set only.
5. Build UI/API snapshots tied to the same taxonomy, interpretation set, and evidence manifest.
6. Verify required compatibility deliveries and reader capabilities.
7. Persist a `prepared` serving generation.

**Publish, in one short transaction:**

1. Acquire the exclusive taxonomy-writer fence.
2. Lock `taxonomy_authority`.
3. Recompute the committed evidence-manifest hash and verify that the prepared processing head, compatibility state, and reader capabilities have not changed.
4. If any input changed, abandon the transaction and repeat preparation outside the lock.
5. Atomically switch the serving-generation pointer and all reader snapshot pointers, change mode if requested, increment `authority_epoch`, and mark the generation published.
6. Commit without provider calls or waiting for workers.

An extraction worker does not advance the serving epoch. It records the processing head and authority epoch it observed, performs provider work outside locks, then uses the shared write fence and an optimistic processing-head check to commit its immutable run, assignments, and at most one new sealed taxonomy version. All new themes found in one source run are included in that single version. If a concurrent semantic change makes the resolver input stale, the worker re-resolves outside the lock.

A crash after processing-head publication leaves no partially visible reader state. A retry uses stable idempotency keys to reuse the same evidence packet, classification run, identities, and assignments. The next serving generation either includes the complete accepted result or none of it.

## 6. Source identity, frozen inputs, and interpretations

### 6.1 Separate source identities

The source model separates four identities:

1. `source_families`: canonical identity of the underlying item, such as a provider post ID or canonical content URL.
2. `evidence_packets`: immutable admitted evidence revisions.
3. `classification_runs`: processing of one evidence packet under one policy bundle and processing taxonomy version.
4. `lens_eligibility_revisions`: immutable declarations of which evidence channels may use the packet.

Legacy content and saved Social work for the same provider post resolve to one source family. Route-specific provenance remains attached to that family and packet, but it does not count as independent support.

### 6.2 Frozen evidence packets

An evidence packet stores, or content-addressably references, the exact inputs used for a run:

- selected original text;
- selected translated text and translation version;
- admitted attachments and extracted text hashes;
- company/security grounding snapshot;
- source metadata and timestamps;
- preparation/normalization version; and
- a canonical packet hash.

The evidence revision hash excludes lens eligibility. Translation, grounding, attachment, or admitted-text changes create a new evidence packet. Adding a narrative, technical, or fundamental eligibility association does not call the extractor again.

### 6.3 Immutable runs and assignments

`classification_runs` is keyed idempotently by:

```text
(evidence_packet_id,
 extraction_policy_version,
 resolver_policy_version,
 naming_policy_version,
 derivation_policy_version,
 processing_taxonomy_version_id)
```

It records `in_progress`, `completed`, `failed`, or `superseded_before_acceptance`. A completed run is immutable. Partial or failed runs never become current.

`claim_assignments` contains the immutable claims, theme assignments, composition evidence, constituent roles, support types, and provenance produced by a completed run. A successful empty extraction is represented by a completed run with zero assignments, not by deleting previous rows.

### 6.4 Accepted interpretation selection

Each serving generation references one immutable `interpretation_set`. That set selects zero or one completed classification run for every admitted source lineage included in its evidence manifest.

Selection rules are:

- an unchanged retry resolves to the existing run and has no additional effect;
- a new policy or taxonomy can create a new run, but it is historical until a serving generation selects it;
- a new accepted evidence revision supersedes the prior selected revision for current reads;
- a selected successful empty run removes the old claims from current metrics and membership while preserving the prior interpretation;
- a partial or failed reprocessing attempt leaves the last accepted selection unchanged; and
- historical reads specify a serving generation or interpretation-set ID and reproduce exactly that selection.

Observations and constituent exposures are assignment-derived immutable facts. Current queries join through the serving generation's interpretation set rather than unioning every historical fact.

## 7. Facets, support states, and extraction outcomes

### 7.1 Governed facet dimensions

V1 approved dimensions are:

- `industry`
- `technology`
- `product`
- `commodity`
- `end_market`
- `customer`
- `supply_chain`
- `geography`
- `policy`
- `regulation`
- `macro`
- `infrastructure`

An unknown dimension does not become an approved facet and does not turn an otherwise valid extraction into a generic parse failure. The raw candidate and value are persisted, a governed `dimension_proposal` is created, and the affected candidate remains review-only until the proposal is resolved.

Canonical normalization distinguishes economic meaning:

- `end_market=artificial_intelligence` means demand serving AI workloads;
- `industry=memory_semiconductors` means participation in memory-semiconductor economics;
- `product=hbm` means direct HBM product exposure; and
- `technology=artificial_intelligence` is reserved for cases where AI technology itself is the defining mechanism.

Thus `AI Memory` is normally grounded by `industry=memory_semiconductors` plus `end_market=artificial_intelligence`; `AI HBM` adds `product=hbm`. Synonyms normalize to these governed values before identity resolution.

### 7.2 Separate support types

Exposure claims use:

```text
direct | inferred | unsupported | unresolved
```

Development detection uses a separate type:

```text
present | absent | unresolved
```

`absent` is not an exposure-support value.

### 7.3 Extraction result contract

The parser returns one of:

```text
accepted_candidates
successful_empty
review_required
failed
```

`review_required` reasons include `unknown_dimension`, `requires_naming_review`, `unsupported_composition`, and `ambiguous_structure`. Review-required candidates remain durable and reproducible.

## 8. Semantic resolution and relationship direction

Retrieval may use normalized names, aliases, facets, lexical similarity, embeddings, and existing graph neighbors. The resolver decides semantics.

Resolver outcomes are stated from the **proposed candidate relative to the existing target**:

- `equivalent`: reuse the target identity;
- `specialization`: candidate is narrower than target;
- `broader`: candidate is broader than target;
- `related`: distinct identities with a supported non-hierarchical relationship;
- `distinct`: no positive relationship is asserted; or
- `ambiguous`: human review is required.

For example, proposed `Copper` relative to existing `Copper Miners` is `broader`. Proposed `Copper Miners` relative to existing `Copper` is `specialization`.

Automatic resolution may reuse one identity or create one provisional identity plus valid edges. It cannot merge existing identities, split an identity, change a defining mechanism, approve a new facet dimension, or retire an identity.

## 9. Observations, constituents, and technical signals

### 9.1 Observations

`theme_observations` references a `claim_assignment_id` and records:

- target theme;
- observation kind (`primary`, `derived_parent`, `derived_related`);
- evidence channel;
- root claim ID;
- derivation path and policy version; and
- observed/effective timestamps.

The idempotency key includes the immutable assignment/run identity. It does not attempt to collapse classifications from different policies into one row.

Only selected primary observations count as independent evidence. Derived observations share their root and source family, remain auditable, and are excluded from direct-confirmation counts.

### 9.2 Constituents

`theme_constituent_exposures` also references a claim assignment and stores:

- `stock_universe.id` as the security authority;
- role, confidence, directness, rationale, and source provenance;
- proposed/accepted/rejected state; and
- administrator decision provenance.

Current membership is a projection from selected assignments plus reviewed decisions. Reclassification never overwrites historical exposure rows.

### 9.3 Structured signals

`theme_signal_observations` stores VCP, breakout, relative-strength leadership, and other supported signal types with:

- theme and security IDs;
- classification run and claim assignment;
- signal type and normalized payload;
- detected/effective times;
- evidence channel and source family; and
- detector policy version.

Signals are not facets and do not create an Economic Theme by themselves.

## 10. Lifecycle

Lifecycle states are:

```text
provisional -> established -> dormant -> reactivated
                           \-> retired
```

Automatic lifecycle evaluation produces a proposed processing snapshot. It never mutates the serving taxonomy directly. Publication uses the common coordinator and includes refreshed interpretations, metrics, and reader snapshots.

V1 default transition thresholds remain policy-versioned and require distinct source families, not ingestion routes:

- provisional to established: at least three direct primary roots from at least two source families on at least two dates within 30 days;
- established to dormant: no direct primary root for 90 days;
- dormant to reactivated: two direct primary roots from two source families within 14 days; and
- retirement: reviewed operation only.

Changing thresholds creates a new lifecycle policy and processing snapshot; it does not rewrite history.

## 11. Migration mappings and reviewed structural operations

### 11.1 Cardinality-safe migration model

Each legacy theme has one version-scoped `legacy_identity_disposition`:

```text
mapped | split_required | merged_equivalent | not_a_theme | deferred
```

A disposition has zero, one, or many `legacy_destination_mappings`. A reviewed exclusion such as `not_a_theme` legitimately has none.

`legacy_claim_allocations` assigns individual legacy claims, observations, or source associations to one destination or to a reviewed exclusion. These allocations are required for a split; an identity-level split alone cannot determine where historical evidence belongs.

`economic_theme_redirects` provides version-scoped canonical resolution for merges between Economic Themes created before or after migration. A one-to-many split does not use a single redirect; current resolution follows claim allocations and preserves the retired source identity for historical reads.

Complete migration coverage means every legacy identity has a reviewed disposition and every current claim affected by a split has an allocation. It does not mean every identity maps to exactly one theme.

When a new taxonomy version is cloned, dispositions, destinations, allocations, and redirects are copied as semantic snapshot data, then changed only in the new draft.

### 11.2 Reviewed operations

Merge, split, rename, facet correction, lifecycle override, relationship correction, and retirement operations produce a new sealed processing snapshot. The serving change occurs only through the publication coordinator.

Every operation records the before/after semantic hashes, actor, reason, affected identities, evidence allocations, compatibility events, and validation result.

## 12. Social integration

Existing `SocialThemeAssociation` rows and their association-scoped administrator decisions remain immutable historical authority for the legacy representation. No economic uniqueness constraint is added to that table.

A separate `economic_social_associations` projection is unique by global theme and security authority. A many-to-many bridge references all contributing legacy Social association IDs and saved-work/evidence IDs. Many legacy associations may therefore consolidate into one global association without deleting their decisions.

Decision reconciliation is deterministic:

- matching administrator decisions consolidate;
- an administrator rejection prevents accepted global membership;
- conflicting administrator accepted/rejected decisions produce `conflict_review_required`; and
- conflict, proposed, rejected, unpublished, or review-only evidence is excluded from accepted live membership until reconciled.

A new post-cutover global Social association does not require a pre-existing legacy association. It begins as `pending_legacy_mirror`; an idempotent compatibility event creates or reuses a legacy compatibility cluster and association. The global association can be reviewed, but it does not enter accepted live membership until the required mirror acknowledgement exists while rollback compatibility is required.

Social admission rules are explicit:

- only published, succeeded saved work that passes the Social live-admission policy can contribute to live narrative metrics;
- unpublished results, rejected evidence, and exploratory work remain review-only;
- constituent decisions remain independent from evidence admission; and
- source-family deduplication prevents the same post arriving through legacy and Social from counting twice.

All additional model calls reserve and reconcile the existing durable Social LLM budget and attempt records using stable operation keys. Provider work occurs before the short locked projection transaction. Budget exhaustion returns a durable blocked result and makes no provider call.

## 13. Development authority

The existing development event authority is extended to represent an `analysis_channel` of `technical`, `fundamental`, or `narrative`; existing technical/fundamental values migrate without semantic change. Social evidence is never mislabeled as technical.

Social/economic-native developments enter the same event table and deduplication path using canonical source-family and event keys. A development is created once, can link directly to Economic Themes, and receives legacy links only through the compatibility adapter. Reprocessing or dual-write delivery cannot create a second event history.

Development support uses `present | absent | unresolved`, independent of exposure support. `record_developments()` and its repository boundary are expanded to accept narrative provenance rather than creating a parallel event authority.

## 14. Evidence channels and ranking views

Evidence-channel eligibility is not evidence, and evidence channels are not ranking views.

V1 evidence channels are:

```text
technical | fundamental | narrative
```

V1 ranking views are:

```text
technical_attention
fundamental_momentum
narrative_attention
emerging
broad_confirmation
```

All calculations use selected primary observations only. One source family contributes at most one root per theme, channel, and UTC day. Derived observations are reported separately and excluded from raw scores.

V1 calculations are:

- **Technical Attention:** exponentially decayed count of direct technical roots in 30 days, half-life seven days, plus accepted structured technical signals, half-life five days.
- **Fundamental Momentum:** exponentially decayed count of direct fundamental roots in 90 days, half-life 30 days.
- **Narrative Attention:** exponentially decayed count of direct narrative roots in 14 days, half-life three days.
- **Emerging:** for provisional or reactivated themes, `unique_families_last_7d - unique_families_prior_21d / 3`; unavailable unless at least two source families occur on at least two dates in the last seven days.
- **Broad Confirmation:** arithmetic mean of the available technical, fundamental, and narrative percentile scores; unavailable unless at least two channels and two distinct source families supply direct support.

Channel raw values are converted to deterministic 0-100 percentile ranks across eligible themes for the same as-of time, with equal raw values receiving the same rank and UUID order used only for stable output ordering. A channel score is `unavailable`, not zero, when it has no selected supporting observation. Missing components are never silently imputed.

Every metrics revision records its formula version, as-of time, interpretation-set ID, evidence-manifest ID, eligibility revision, component availability, raw values, and ranked values.

## 15. Producer fencing, outbox ordering, and rollback

### 15.1 Shared pre-commit write fence

Every participating producer uses one protocol:

1. Perform network/provider work outside the database transaction.
2. Begin the short write transaction and acquire the shared transaction-level taxonomy advisory lock.
3. Lock and reread `taxonomy_authority`; verify the expected mode, epoch, and write permission.
4. Acquire producer-specific locks and persist domain changes, a source-revision-log entry, and any outbox event atomically.
5. Commit, releasing the shared lock.

The final publication transaction takes the exclusive form of the same advisory lock. It therefore waits for earlier writers to drain and prevents an old-mode transaction from committing after the switch.

The global lock order is:

```text
taxonomy writer fence
-> taxonomy authority row
-> producer-specific registry/grouping locks
-> source/work/domain rows
-> outbox rows
```

No code may acquire these in reverse order. Existing Social/grouping transactions must be refactored to enter through this order.

### 15.2 Evidence revision log and manifests

Every participating producer appends `taxonomy_source_revision_log` in the same transaction as its authoritative change. The row contains producer kind, logical source key, committed revision, content hash, and authority metadata.

An evidence manifest contains the sorted exact revision tuples and a hash, not merely a maximum source or sequence ID. During final publication, the exclusive writer fence first drains all shared holders. Only then is the committed manifest reread, so a lower allocated ID cannot commit late behind the barrier.

UI snapshots, metrics, interpretation selection, and target taxonomy are all tied to this same manifest.

### 15.3 Outbox identity and target idempotency

Logical event identity excludes the authority epoch. It contains the source logical identity, source revision, projection kind/version, and target representation. Delivery attempts record the claimed epoch separately.

Targets store a last-applied ordered source revision or equivalent compare-and-set token. Delivery of revision 2 before revision 1 makes revision 1 a successful no-op; it cannot restore stale state. Retrying an event after an epoch change reuses the same logical event identity.

Compatibility writes carry an origin marker and suppress reverse mirror generation. Economic-to-legacy delivery cannot recursively emit a legacy-to-economic event, or vice versa.

### 15.4 Rollback

Normal rollback prepares a legacy-serving generation, verifies compatibility health, and publishes it through the same coordinator.

If compatibility delivery is unhealthy, rollback is not represented as immediately safe. Authority enters `rollback_recovery`: new authoritative writes are fenced or restricted, missing legacy projections are rebuilt from the current accepted interpretation, ordering and high-watermarks are verified, and only then is the legacy generation published. Operators receive a durable recovery status and retry path.

## 16. Migration and cutover protocol

Migration is online and resumable.

### 16.1 Catch-up outside the publication transaction

1. Backfill stable identities, sealed taxonomy snapshots, dispositions, destinations, allocations, redirects, source families, evidence packets, and historical interpretations.
2. Run shadow processing and compare outputs.
3. Enter dual mode only after compatibility and producer-fence tests pass.
4. Replay content, Social, development, and structural revision-log entries outside the publication lock.
5. Drain required outbox deliveries outside the publication lock.
6. Build the target interpretation set, metrics, UI snapshots, and prepared serving generation from one evidence manifest.

### 16.2 Final barrier

1. Acquire the exclusive writer fence, which drains in-flight shared writers.
2. Lock authority and read the exact committed revision manifest.
3. If it differs from the prepared generation, release the lock and repeat catch-up/preparation outside the transaction.
4. Verify compatibility acknowledgement, projection high-watermarks, snapshot hashes, and reader capability.
5. Atomically switch serving and reader pointers, mode, and epoch.
6. Commit and release the fence.

No provider call, replay, outbox drain, or worker wait occurs while the exclusive fence is held.

Required race tests include an existing source changing during replay, a lower sequence ID committing late, outbox delivery waiting behind publication, and evidence arriving after target snapshot construction.

### 16.3 Reader readiness

Every prepared generation references an immutable `reader_capability_manifest` containing required backend reader-contract version, frontend snapshot-contract version, migration version, and successful consumer-contract test artifact.

Economic mode cannot be published unless the authority-aware backend facade, frontend, compatibility adapters, and release-gate tests all satisfy that manifest. Cutover code existing in the repository is not sufficient readiness.

## 17. Reader and service boundaries

Readers use `EconomicThemeReader`, which resolves the current serving generation once per request/job and supplies:

- taxonomy snapshot;
- accepted interpretation selection;
- constituent projection;
- metrics revision;
- Social reconciliation state;
- legacy mappings and redirects; and
- UI/API snapshot bundle.

No consumer independently reads “latest” rows from these tables. Historical reads require a generation ID or interpretation-set ID.

Writers use:

- `EvidenceAdmissionService` for source-family and packet identity;
- `EconomicTaxonomyProcessor` for extraction and immutable runs;
- `TaxonomyOperationService` for reviewed semantic changes;
- `TaxonomyPublicationCoordinator` for every serving change;
- `CompatibilityOutboxService` for ordered mirrors; and
- the shared producer-fence helper before commit.

## 18. Failure and status contract

Durable failure/status codes include:

- `invalid_schema`
- `unsupported_composition`
- `unknown_dimension`
- `requires_naming_review`
- `ambiguous_identity`
- `stale_processing_head`
- `stale_authority_epoch`
- `budget_exhausted`
- `conflict_review_required`
- `compatibility_pending`
- `reader_not_ready`
- `manifest_changed`
- `publication_validation_failed`
- `rollback_recovery_required`
- `provider_retryable`
- `provider_terminal`

Unknown dimensions and naming-review results retain their candidates. Retryable provider failures retain the previous accepted interpretation. Dead-lettering never makes partial classifications current.

## 19. Required counterexample and invariant tests

The implementation is not complete without tests for:

### Publication and interpretation

- interrupt immediately after provisional processing publication; retry yields one identity, one accepted interpretation, coherent pointers, and one logical compatibility event;
- one source introduces several new themes without invalidating itself;
- same-source policy reclassification preserves both runs and selects only one;
- corrected-to-empty evidence removes current contributions while preserving history;
- failed or partial reprocessing leaves the last accepted result current; and
- historical reads reproduce old and new interpretation sets.

### Mapping and Social

- one legacy `Refining` identity splits petroleum and metals claims into separate destinations;
- later versions preserve the old mapping snapshot;
- many legacy Social associations consolidate to one global association with identical decisions;
- conflicting administrator decisions stay visible and excluded pending reconciliation;
- a new post-cutover Social theme with no legacy cluster creates an ordered compatibility projection;
- administrator-rejected membership stays rejected;
- unpublished Social work cannot become live confirmation;
- exhausted budget prevents provider calls; and
- a Social-native development appears once with narrative provenance.

### Fencing, cutover, and delivery

- a legacy writer racing cutover cannot commit after the authority switch;
- replaying one compatibility event after an epoch change remains idempotent;
- revision 2 followed by revision 1 leaves revision 2 applied;
- compatibility delivery cannot recursively mirror itself;
- changed manifests abort publication and retry outside the lock;
- blocked outbox work cannot deadlock publication; and
- rollback recovery is durable when compatibility is unhealthy.

### Snapshots and graph

- a sealed version cannot reopen or mutate;
- concurrent draft mutation cannot slip past sealing/hash calculation;
- a row cannot move between versions;
- every version-owned reference resolves inside the same snapshot;
- mappings remain available after later publication;
- semantic clones have the same hash despite different row/version IDs;
- specialization cycles are rejected; and
- contradictory distinct/equivalent/specialization assertions are rejected.

### Source and measurement

- adding lens eligibility does not invoke extraction;
- the same post through legacy and Social shares one source family;
- old extraction is reproducible after translation or grounding changes;
- eligibility alone does not create a channel score;
- structured technical signals persist with policy provenance; and
- missing metric components remain explicitly unavailable.

Required PostgreSQL concurrency tests are enumerated by exact node ID in the CI release gate. The gate fails if a required test is missing, not collected, skipped, xfailed, or does not run against PostgreSQL. A green result with zero collected tests or any skip is a failure.

## 20. Relationship to ADR-0003

ADR-0003 remains authoritative for `StockUniverse` and stock-identifier point-in-time reconstruction. Its audit-log decision is not a universal ban on immutable snapshots.

Economic taxonomy semantics use sealed snapshots because an entire graph, alias set, facet set, mapping set, and lifecycle state must be published coherently. Runtime facts remain append-only: evidence packets, classification runs, assignments, observations, developments, decisions, source revision logs, outbox deliveries, and interpretation selections are historical records. Historical reads select a serving generation and interpretation set rather than reconstructing an unversioned semantic graph from mutation logs.

This distinction is recorded in a dedicated taxonomy ADR. It does not change the stock-universe hot path or identifier lifecycle.

## 21. Non-goals

- Deleting legacy themes or Social associations during this project.
- Treating embeddings as an identity authority.
- Automatically approving new dimensions, merges, splits, or retirements.
- Replacing `StockUniverse` identifier authority.
- Guaranteeing immediate rollback while compatibility projections are known unhealthy.
- Inferring technical or fundamental momentum from channel eligibility alone.

## 22. Plan rewrite gate

Before schema implementation, the implementation plan must add a focused Task 0 that turns these contracts into executable interfaces, state machines, migrations, and test fixtures:

1. publication transaction and serving-generation contract;
2. frozen evidence, classification-run, and interpretation-selection contract;
3. cardinality-safe mapping, redirect, and Social-decision contract;
4. producer fencing, committed-manifest, outbox ordering, and recovery contract; and
5. Social admission/budget, development authority, signal persistence, and V1 measurement contract.

Task 0 must produce failing counterexample tests and schema/interface decisions before the existing schema tasks begin. Production economic mode remains impossible until authority-aware readers and the full release gate are complete.
