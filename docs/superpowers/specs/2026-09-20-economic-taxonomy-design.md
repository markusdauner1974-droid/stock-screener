# Open Multi-Dimensional Economic Taxonomy

**Status:** production-ready after the recorded PostgreSQL rehearsal

**Date:** 2026-09-20

**Revised:** 2026-09-21

**Implementation plan:** `docs/superpowers/plans/2026-09-21-economic-taxonomy.md` implements this revision. Production economic mode remains gated by that plan's Task 19 release checks, the operator procedure in `docs/runbooks/economic-taxonomy-cutover.md`, and a deployment-specific repeat of `docs/runbooks/artifacts/economic-taxonomy-rehearsal-2026-09-21.md`.

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
- derived observations never inflate distinct-source counts;
- every serving generation is reproducible from a taxonomy snapshot, interpretation selection, generation-input cutoff, pinned decision/projection revisions, metrics revision, and reader snapshot;
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
8. **Immutable publication.** Published semantic content, evidence packets, classification attempts, assignments, interpretation sets, and serving-generation payloads are never updated in place.
9. **Explicit current interpretation.** Current reads select exactly one accepted interpretation per source lineage; they never union all historical classifications.
10. **Processing is not serving.** Extraction and taxonomy evolution can advance a processing head, but readers change only when a complete serving generation is atomically published.
11. **One source family, honest corroboration.** Duplicate ingestion routes share a canonical source family. Processing the same source twice never creates two confirmations, and distinct source families are not labeled statistically independent without separate evidence of independence.
12. **Governed restructuring.** Automatic processing may add evidence, attach a candidate to one existing identity, or create a provisional identity. Merges, splits, defining-mechanism changes, new dimensions, and retirement require review.
13. **Every producer is fenced.** Content, Social, development, migration, compatibility, and structural writers use the same pre-commit authority fence.
14. **Route-independent lineage.** Ingestion route is provenance, never part of ordinary source-lineage identity.
15. **Cutoff progress.** A coherent bounded cutoff may publish while later evidence waits for the next generation; continuous writes cannot prevent publication forever.
16. **Authenticated authority.** Semantic review, mode changes, manual publication, and recovery bind actor identity to an authenticated administrator or configured service principal, never to a caller-supplied display string.

## 4. Chosen architecture

The design uses two immutable heads:

- a **processing taxonomy head**, against which new evidence is classified and proposed semantic changes are sealed; and
- a **serving generation**, which bundles a sealed taxonomy snapshot with accepted interpretations, pinned decision/projection revisions, metrics, reader snapshots, and the exact generation-input manifest used to build them.

Provider calls, extraction, resolution, review, catch-up, metrics calculation, and UI snapshot construction happen outside the final publication transaction. A short publication transaction changes all authoritative reader pointers together.

```text
Canonical source family
        |
        v
Immutable admitted evidence packet ----> Lens-eligibility revision
        |
        v
Stable processing request
        |
        v
Reusable extraction + claim-review artifacts
        |
        v
Immutable classification attempt
actual input taxonomy + output taxonomy
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
taxonomy + interpretation set + pinned decisions/projections
+ metrics + UI snapshots + generation-input manifest
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

The semantic snapshot hash is computed from every decision-relevant normalized semantic value: stable theme UUIDs; normalized revision content; aliases; facet-dimension definitions including value type, cardinality, scope, and normalization policy; facet values and assignments; relationship endpoints, type, direction, and discriminator; lifecycle state and policy; dispositions, destinations, claim allocations, and redirects; and all policy identities that can change interpretation. It excludes database row IDs, taxonomy-version IDs, timestamps, actor IDs, review comments, and other incidental metadata. A semantic clone therefore retains the same semantic hash.

A separate artifact-integrity hash covers the complete immutable serialized payload needed to detect corruption, including stable logical record IDs and non-semantic provenance fields. Semantic equality uses the semantic hash; byte/payload integrity uses the artifact-integrity hash. Neither hash includes mutable operational state.

### 5.3 Authority and serving generations

`taxonomy_authority` is a singleton containing:

- `mode`: `legacy`, `shadow`, `dual`, or `economic`;
- `processing_taxonomy_version_id`;
- `processing_head_revision`;
- `serving_generation_id`;
- `authority_epoch`;
- `writes_fenced`; and
- rollback/recovery state.

The immutable payload of `serving_generations` contains:

- sealed taxonomy version;
- accepted interpretation-set ID;
- metrics revision ID;
- generation-input-manifest ID and hash;
- UI/API snapshot bundle ID;
- reader-capability manifest ID;
- semantic content hash; and
- artifact-integrity hash.

Generation status is not part of that payload. `serving_generation_events` records append-only `prepared`, `published`, `superseded`, and `abandoned` transitions. The authority pointer determines the active generation.

Interpretation sets, metrics revisions, and reader snapshot bundles are built as drafts. Their payload tables permit one audited `unsealed -> sealed` transition that writes `sealed_at` and content hashes; after sealing, triggers reject payload insert, update, or delete. A serving generation may reference only sealed artifacts.

Only `taxonomy_authority.serving_generation_id` defines what readers see. The processing head is not a reader pointer.

### 5.4 One publication coordinator

Provisional creation, lifecycle transitions, reviewed merges/splits/renames, ordinary refreshes, migration cutover, and rollback all use `TaxonomyPublicationCoordinator`.

The coordinator has two phases.

**Prepare, outside the final publication transaction:**

1. In a separate short cutoff-capture transaction, acquire the exclusive fence, drain existing writers, and capture the committed generation-input manifest, processing taxonomy version, expected parent generation, and semantic invalidation revision; then release the fence.
2. Select completed classification attempts and exact eligibility, constituent/Social decision, development, mapping, and reviewed-override revisions from that manifest into a new immutable interpretation set.
3. Compute metrics from those pinned inputs only.
4. Build UI/API snapshots tied to the same complete manifest.
5. Stage complete candidate-generation compatibility payloads.
6. Verify required prior-generation compatibility acknowledgements and reusable reader capabilities.
7. Seal every payload artifact, persist the immutable serving-generation payload, and append its `prepared` event.

**Publish, in one short transaction:**

1. Acquire the exclusive taxonomy-writer fence.
2. Lock `taxonomy_authority`.
3. Verify the frozen manifest and artifact hashes, expected parent generation, semantic invalidation revision, compatibility state, and reader capabilities. Ordinary revisions committed after the cutoff do not invalidate the generation.
4. If the parent or a declared semantic invalidator changed, append `abandoned`, release the lock, and prepare again outside the transaction.
5. Atomically switch the serving-generation pointer and all reader snapshot pointers, change mode if requested, increment `authority_epoch`, and append the `published` event.
6. Commit without provider calls or waiting for workers.

An extraction worker does not advance the serving epoch. It records the processing head and authority epoch it observed, performs provider work outside locks, then uses the shared write fence and an optimistic processing-head check to commit its immutable attempt, assignments, and at most one new sealed taxonomy version. All new themes found in one source request are included in that single version. If a concurrent semantic change makes the resolver input stale, the worker records the stale attempt as superseded and re-resolves outside the lock against the new head while reusing unchanged extraction/review artifacts.

A crash after processing-head publication leaves no partially visible reader state. A retry of a successfully committed attempt reuses the same attempt, identities, assignments, and mirror intent. The next serving generation either includes the complete accepted result or none of it.

## 6. Source identity, processing attempts, and interpretations

### 6.1 Route-independent families and lineages

The source model separates these identities:

1. `source_families`: canonical identity of the underlying item, such as a provider post ID or canonical content URL.
2. `source_lineages`: the correction/revision stream whose current interpretation must be selected as one unit.
3. `evidence_packets`: immutable admitted evidence revisions within a lineage.
4. `lens_eligibility_revisions`: immutable declarations of which evidence channels may use a packet.
5. `processing_requests`: stable requests that survive stale-head retries.
6. reusable extraction and claim-review artifacts.
7. `classification_attempts`: resolution against one exact taxonomy/policy input.

For an ordinary parent post and all admitted attachments, the lineage key is derived from the canonical source-family key alone. Legacy and Social route IDs are provenance and never enter the lineage key. A scope suffix is permitted only for an explicitly governed, non-overlapping evidence scope with its own admission-policy key; arbitrary route-specific scopes are invalid.

Legacy content and saved Social work for the same provider post therefore resolve to one family and ordinary lineage. Correcting that lineage to empty through either route retracts its old contribution through every route.

### 6.2 Frozen evidence and revision precedence

An evidence packet stores, or content-addressably references, the exact selected original/translated text, translation version, admitted attachments and extracted-text hashes, company/security grounding snapshot, source metadata/timestamps, preparation version, and canonical packet hash.

The evidence revision hash excludes lens eligibility. Translation, grounding, attachment, or admitted-text changes create a new packet. Adding a narrative, technical, or fundamental eligibility association does not call the extractor again.

Admission assigns a monotonic `evidence_revision_ordinal` inside the lineage transaction. Selection precedence uses this ordinal, not job completion time. A delayed attempt for ordinal 4 cannot replace an accepted correction at ordinal 5.

### 6.3 Requests, reusable artifacts, and exact attempts

`processing_requests` is stable across retry and keyed by lineage, evidence packet, and desired policy bundle.

Raw `extraction_artifacts` are keyed by:

```text
(evidence_packet_id, extraction_policy_version)
```

`claim_review_artifacts` are keyed by:

```text
(extraction_artifact_id,
 claim_review_policy_version,
 facet_catalog_semantic_hash)
```

This makes claim-review policy identity explicit and allows an unrelated taxonomy-head change to reuse extraction and review work.

Each `classification_attempt` is keyed by the reviewed artifact, the actual `input_taxonomy_version_id`, and resolver, naming, and derivation policy versions. It records a nullable `output_taxonomy_version_id` when the attempt introduces identities or edges. Attempt state is append-only through events such as `started`, `completed`, `failed`, and `superseded_before_acceptance`; completed payloads are immutable.

If work starts against H10 and the head advances to H11, the H10 attempt is retained and superseded, while a distinct H11 attempt records the real resolution input. A retry after an H11 attempt committed reuses H11 rather than creating a third attempt. Provider extraction is not repeated when its artifact key is unchanged.

`claim_assignments` contains the immutable claims, theme assignments, composition evidence, constituent roles, support types, and provenance produced by a completed attempt. A successful empty extraction is a completed attempt with zero assignments.

### 6.4 Accepted interpretation selection

Each serving generation references one immutable `interpretation_set`. That set selects zero or one completed classification attempt for every admitted lineage in its generation-input manifest.

Selection rules are:

- an unchanged retry has no additional effect;
- the highest admissible evidence revision ordinal wins unless an authenticated reviewed override selects another completed attempt;
- a delayed older attempt cannot displace a newer accepted correction;
- a new policy or taxonomy attempt remains historical until selected;
- a selected successful empty attempt removes prior current claims while preserving history;
- a partial, failed, review-only, or superseded attempt leaves the prior selection unchanged; and
- historical reads specify a serving generation and reproduce exactly its selected attempt and auxiliary inputs.

Observations and constituent exposures are assignment-derived immutable facts. Current queries join through the generation's selections rather than unioning every historical fact.

### 6.5 Complete generation-bound inputs

The generation-input manifest pins the exact append-only revisions used by historical readers:

- source lineage and evidence packet;
- selected classification attempt and any authenticated interpretation override;
- lens-eligibility revision;
- constituent decision revision;
- Social association/decision projection revision;
- development observation/selection revision;
- taxonomy mapping/redirect snapshot;
- metrics-policy revision; and
- compatibility projection revision/checkpoint.

The reader snapshot bundle may materialize these selections for speed, but it is not a second authority: every payload points back to the pinned manifest entries. Later administrator decisions, eligibility changes, or development corrections appear only in a later generation and cannot alter an older generation.

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

Only selected primary observations count toward distinct-source evidence. Derived observations share their root and source family, remain auditable, and are excluded from direct-confirmation counts. Distinct-source counts do not claim statistical independence.

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
- classification attempt and claim assignment;
- signal type and normalized payload;
- detected/effective times;
- evidence channel and source family; and
- detector policy version.

Signals are not facets and do not create an Economic Theme by themselves.

### 9.4 Retrieval embeddings

`economic_theme_embeddings` is an append-only derived cache keyed by Economic Theme UUID, taxonomy semantic hash, source text hash, embedding model, and model version. It is not semantic authority and is excluded from the semantic snapshot hash. Missing or stale embeddings are recomputed from the sealed theme revision; retrieval must remain correct with lexical/facet candidates when the embedding provider is unavailable.

## 10. Lifecycle

Lifecycle states are:

```text
provisional -> established -> dormant -> reactivated
                           \-> retired
```

Automatic lifecycle evaluation produces a proposed processing snapshot. It never mutates the serving taxonomy directly. Publication uses the common coordinator and includes refreshed interpretations, metrics, and reader snapshots.

V1 default transition thresholds remain policy-versioned and require distinct source families, not ingestion routes:

- provisional to established: at least three direct primary roots from at least two source families on at least two dates within 30 days, plus either two accepted constituent securities or an authenticated reviewed assertion of multi-security breadth;
- established to dormant: no direct primary root for 90 days;
- dormant to reactivated: two direct primary roots from two source families within 14 days; and
- retirement: reviewed operation only.

The 90-day dormancy and two-family reactivation rules are deliberate V1 policy choices. Changing any threshold or the breadth rule creates a new lifecycle policy and processing snapshot; it does not rewrite history.

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

Every operation has an immutable request/preview payload and append-only transition events. It records the before/after semantic and artifact hashes, authenticated actor, reason, affected identities, evidence allocations, compatibility events, and validation result. Proposal decisions and interpretation overrides are append-only revisions; a generation pins the exact accepted revision rather than reading a mutable latest row.

Semantic write endpoints require the existing administrator authorization boundary extended to return `AdminPrincipal(subject=settings.admin_principal_id, auth_method="admin_api_key")` after validating the key. If `ADMIN_PRINCIPAL_ID` is absent, those endpoints fail closed with the same disabled-admin behavior as a missing key. The principal never comes from `X-Admin-Actor` or another caller-supplied string. Automatic eligible provisional processing uses the fixed `system:economic-taxonomy-refresh` service principal. Mode changes, reviewed structural operations, manual publication, and recovery remain administrator-only.

## 12. Social integration

Existing `SocialThemeAssociation` rows and their association-scoped administrator decisions remain immutable historical authority for the legacy representation. No economic uniqueness constraint is added to that table.

A separate `economic_social_associations` projection is unique by global theme and security authority. A many-to-many bridge references all contributing legacy Social association IDs and saved-work/evidence IDs. Many legacy associations may therefore consolidate into one global association without deleting their decisions.

Decision reconciliation is deterministic:

- matching administrator decisions consolidate;
- an administrator rejection prevents accepted global membership;
- conflicting administrator accepted/rejected decisions produce `conflict_review_required`; and
- conflict, proposed, rejected, unpublished, or review-only evidence is excluded from accepted live membership until reconciled.

Global Social associations and administrator decisions are append-only revision streams. Each generation pins the applicable association and decision revision. Updating a live projection never changes the membership returned for an older generation.

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

Existing duplicate `(pipeline, event_key)` identities are preserved through append-only `legacy_development_event_mappings` from old event ID to canonical event ID, pipeline, and migration run. Historical observations and links remain attached to their original rows; current readers resolve through the canonical mapping. No migration deletes or silently repoints historical identity.

Development detection uses `present | absent | unresolved`, independent of exposure support and the existing development classification/uncertainty state. Presence never overwrites claim support or classification. `record_developments()` and its repository boundary are expanded to accept narrative provenance rather than creating a parallel event authority. Each generation pins the selected development-observation revisions.

## 14. Evidence channels and ranking views

Evidence-channel eligibility is not evidence, and evidence channels are not ranking views.

V1 evidence channels are:

```text
technical | fundamental | narrative
```

V1 ranking views are:

```text
technical_attention
fundamental_attention
narrative_attention
emerging
broad_confirmation
```

`Fundamental Attention` is intentionally unsigned: it measures the amount and recency of fundamental evidence, not improvement. Improving-versus-deteriorating direction is deferred to the economic-driver-pack work described in section 21.

All calculations use selected primary observations only. One source family contributes at most one root per theme, channel, and UTC day. Derived observations are reported separately and excluded from raw scores. “Distinct source family” is a deduplication statement, not a claim of statistical independence.

V1 calculations are:

- **Technical Attention:** exponentially decayed technical contribution in 30 days, half-life seven days for roots and five days for accepted signals.
- **Fundamental Attention:** exponentially decayed count of direct fundamental roots in 90 days, half-life 30 days.
- **Narrative Attention:** exponentially decayed count of direct narrative roots in 14 days, half-life three days.
- **Emerging:** for provisional or reactivated themes, `unique_families_last_7d - unique_families_prior_21d / 3`; unavailable unless at least two source families occur on at least two dates in the last seven days.
- **Broad Confirmation:** arithmetic mean of the available technical, fundamental, and narrative percentile scores; unavailable unless at least two channels and two distinct source families supply direct support.

Numerical conventions are fixed for V1:

- use each selected observation or signal's UTC `available_at` timestamp to avoid look-ahead;
- include timestamps in the closed interval `[as_of - window, as_of]`;
- calculate decay as `2 ** (-age_seconds / half_life_seconds)`;
- give every accepted V1 technical signal type weight `1.0`;
- for each `(source_family, theme, UTC day)`, take the maximum decayed technical root-or-signal contribution, so multiple signals or a root plus signals from one source cannot multiply its weight;
- convert non-empty channel raw values to percentile `100 * (average_rank - 1) / (n - 1)`, with average ranks for ties;
- when exactly one theme has an available value, assign percentile `100`; and
- use UUID only for stable display ordering, never to break score ties.

A channel score is `unavailable`, not zero, when it has no selected supporting observation. Missing components are never silently imputed.

Every metrics revision records its formula version, as-of time, interpretation-set ID, generation-input-manifest ID, pinned eligibility revisions, component availability, raw values, and ranked values.

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

### 15.2 Revision log, bounded cutoffs, and generation-input manifests

Every participating producer appends `taxonomy_source_revision_log` in the same transaction as its authoritative change. The row contains producer kind, logical source/lineage key, committed evidence or decision revision, content hash, and authority metadata.

A routine generation first takes the exclusive fence briefly, drains existing shared writers, and captures a committed cutoff plus an immutable generation-input manifest. The fence is then released and every artifact is built from that frozen input set. Later revisions are logged beyond the cutoff and belong to a subsequent generation; they do not invalidate this coherent generation.

The manifest contains sorted exact typed revision tuples, not merely a maximum source or sequence ID. It includes evidence, interpretation, eligibility, decision, development, mapping, override, and projection revisions. UI snapshots, metrics, interpretation selection, and target taxonomy are tied to this same manifest.

Final publication validates manifest integrity, expected parent generation, and a semantic invalidation revision. A newer ordinary evidence/decision revision after the cutoff does not block publication. A reviewed structural change declared incompatible with the prepared taxonomy does. Compare-and-set on the parent generation prevents an older prepared generation from replacing a newer published one.

### 15.3 Outbox identity and target idempotency

Logical event identity excludes the authority epoch. It contains the source lineage, monotonically ordered projection revision, projection kind/version, and target representation. Evidence revision remains payload provenance; delivery attempts record claimed epoch separately.

Each `(source_lineage, target_representation, projection_kind)` advances its projection revision whenever the selected attempt, reviewed allocation/redirect, applicable eligibility, or membership decision changes. Payloads replace that source lineage's complete target contribution and include selected interpretation and mapping versions. An empty payload retracts that lineage without removing support owned by other lineages.

Targets store the last-applied projection revision per lineage. Delivery of projection revision 2 before revision 1 makes revision 1 a successful no-op; it cannot restore stale state. Retrying an event after an epoch change reuses the same logical event identity.

Unselected processing attempts never change the live legacy representation. Shadow mode writes comparison payloads to shadow projection storage only. Preparation durably stages complete candidate-generation payloads without applying them to live legacy state. Their outbox events become deliverable only after that generation is accepted. A mode-changing cutover requires compatibility acknowledgement through the previously accepted generation plus staged payloads for the candidate; routine economic publication may deliver the new generation asynchronously and records rollback as temporarily unavailable until its required mirrors acknowledge.

Compatibility writes carry an origin marker and suppress reverse mirror generation. Economic-to-legacy delivery cannot recursively emit a legacy-to-economic event, or vice versa.

### 15.4 Rollback

Normal rollback prepares a legacy-serving generation, verifies compatibility health, and publishes it through the same coordinator.

If compatibility delivery is unhealthy, rollback is not represented as immediately safe. Authority enters `rollback_recovery`: new authoritative writes are fenced or restricted, missing legacy projections are rebuilt from the current accepted interpretation, ordering and high-watermarks are verified, and only then is the legacy generation published. Operators receive a durable recovery status and retry path.

## 16. Migration and cutover protocol

Migration is online and resumable.

`taxonomy_migration_runs` seals immutable run inputs and policy/snapshot hashes. Progress, pause, failure, review, replay, and completion are append-only `taxonomy_migration_progress_events`; mutable counters may be cached operationally but are not historical authority. Every reviewed disposition/allocation references its migration run and authenticated actor.

### 16.1 Catch-up outside the publication transaction

1. Backfill stable identities, sealed taxonomy snapshots, dispositions, destinations, allocations, redirects, source families, evidence packets, and historical interpretations.
2. Run shadow processing and compare outputs.
3. Enter dual mode only after compatibility and producer-fence tests pass.
4. Replay content, Social, development, and structural revision-log entries outside the publication lock.
5. Drain required outbox deliveries outside the publication lock.
6. Briefly acquire the exclusive fence to capture cutover cutoff C and its exact generation-input manifest, then release it.
7. Build the target interpretation set, pinned auxiliary selections, metrics, UI snapshots, and prepared serving generation from C while later writes continue into the durable `> C` backlog.

The contrast benchmark is executable, not report-only. Every fixture declares required and forbidden identities, relationships, assignments, selections, and retractions; any mismatch exits nonzero. Required fixtures cover pseudo-theme rejection, tanker segmentation, mechanism contrast, specificity, route deduplication, reclassification, and corrected-to-empty selection.

### 16.2 Final barrier

1. Acquire the exclusive writer fence, which drains in-flight shared writers.
2. Lock authority and verify the prepared cutoff manifest's integrity, expected parent generation, semantic invalidation revision, compatibility acknowledgements, snapshot hashes, and reader capability.
3. Do not require equality with revisions committed after C; record those revisions as the mandatory post-cutover catch-up backlog.
4. If the parent or a declared structural invalidator changed, release the lock and repeat preparation outside the transaction.
5. Atomically switch serving and reader pointers, mode, epoch, and catch-up cursor C.
6. Commit, release the fence, and let routine refresh publish `> C` revisions.

No provider call, replay, outbox drain, or worker wait occurs while the exclusive fence is held.

Required race tests include an existing source changing during replay, a lower sequence ID committing late, outbox delivery waiting behind publication, evidence arriving after target snapshot construction, and continuous evidence arrival while multiple generations still make forward progress.

### 16.3 Reader readiness

Every prepared generation references an immutable `reader_capability_manifest` containing required backend reader-contract version, frontend snapshot-contract version, migration version, and successful consumer-contract test artifact.

Economic mode cannot be published unless the authority-aware backend facade, frontend, compatibility adapters, and release-gate tests all satisfy that manifest. Cutover code existing in the repository is not sufficient readiness.

The verified deployed capability is reusable for routine data-only generations. A new capability manifest is required only when a software, schema, or reader-contract version changes.

### 16.4 Automatic routine publication

After economic mode is enabled, a scheduler checks for dirty revision-log entries every minute and coalesces them into at most one routine publication per five-minute window. It captures a cutoff, prepares a generation, and publishes through the same coordinator without a human command when all changes are routine evidence, eligible provisional discovery, accepted decisions, lifecycle evaluation, or metrics refresh.

Unknown dimensions, ambiguous identity, merges, splits, retirements, defining-mechanism changes, and other review-required proposals remain held and are excluded from the automatic generation. Mode changes and recovery remain administrator-only. Automated publication is attributed to the configured `system:economic-taxonomy-refresh` principal.

The scheduler uses compare-and-set on the expected parent generation, retries infrastructure failures with exponential backoff capped at five minutes, and guarantees eventual processing of every committed revision-log entry while the system remains available. It never publishes one generation per source by default.

## 17. Reader and service boundaries

Readers use `EconomicThemeReader`, which resolves the current serving generation once per request/job and supplies:

- taxonomy snapshot;
- accepted interpretation selection;
- constituent projection;
- metrics revision;
- Social reconciliation state;
- pinned eligibility, decision, development, override, and projection revisions;
- legacy mappings and redirects; and
- UI/API snapshot bundle.

No consumer independently reads “latest” rows from these tables. Historical product reads require a generation ID; an interpretation-set ID alone is insufficient because it does not select auxiliary decision/projection revisions.

Writers use:

- `EvidenceAdmissionService` for source-family and packet identity;
- `EconomicTaxonomyProcessor` for extraction and immutable attempts;
- `TaxonomyOperationService` for reviewed semantic changes;
- `TaxonomyPublicationCoordinator` for every serving change;
- `CompatibilityOutboxService` for ordered mirrors; and
- the shared producer-fence helper before commit.

Administrative services accept an `AdminPrincipal` returned by authentication middleware, not an actor name supplied in request data or headers. Automated refresh accepts only the configured taxonomy service principal. Authorization failures occur before preview/application state is written and are audited without treating the rejected caller string as an identity.

## 18. Failure and status contract

Durable failure/status codes include:

- `invalid_schema`
- `unsupported_composition`
- `unknown_dimension`
- `requires_naming_review`
- `ambiguous_identity`
- `stale_processing_head`
- `stale_authority_epoch`
- `stale_projection_revision`
- `authorization_required`
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
- advance the processing head during a provider call; preserve the actual old/new input and output taxonomy versions, accept one attempt, reuse extraction/review artifacts, and produce no duplicate identity or mirror effect;
- same-source policy reclassification preserves all attempts and selects only one;
- corrected-to-empty evidence removes current contributions while preserving history;
- failed or partial reprocessing leaves the last accepted result current;
- the same post through legacy and Social, corrected to empty through one route, leaves no obsolete current contribution through the other route;
- a delayed older attempt cannot replace a newer accepted correction;
- after decision, eligibility, and development changes, G1 reproduces its old results and G2 shows the changes through direct APIs, stock-theme reads, Social baskets, and UI snapshots; and
- historical reads reproduce old and new interpretation sets and pinned auxiliary revisions.

### Mapping and Social

- one legacy `Refining` identity splits petroleum and metals claims into separate destinations;
- later versions preserve the old mapping snapshot;
- many legacy Social associations consolidate to one global association with identical decisions;
- conflicting administrator decisions stay visible and excluded pending reconciliation;
- a new post-cutover Social theme with no legacy cluster creates an ordered compatibility projection;
- administrator-rejected membership stays rejected;
- unpublished Social work cannot become live confirmation;
- exhausted budget prevents provider calls; and
- a Social-native development appears once with narrative provenance; and
- legacy duplicate development events retain old-to-canonical mappings and reproducible channel-specific observations.

### Fencing, cutover, and delivery

- a legacy writer racing cutover cannot commit after the authority switch;
- replaying one compatibility event after an epoch change remains idempotent;
- projection revision 2 followed by revision 1 leaves revision 2 applied;
- unchanged source bytes reclassified to a new or empty accepted projection retract/reassign the complete lineage contribution without removing other sources;
- compatibility delivery cannot recursively mirror itself;
- unselected processing results cannot modify the live legacy representation;
- continuous evidence arrival still allows coherent generations to publish and later revisions to appear eventually;
- declared structural invalidation or a stale parent aborts publication, while ordinary post-cutoff revisions do not;
- blocked outbox work cannot deadlock publication; and
- rollback recovery is durable when compatibility is unhealthy.

### Snapshots and graph

- a sealed version cannot reopen or mutate;
- concurrent draft mutation cannot slip past sealing/hash calculation;
- a row cannot move between versions;
- every version-owned reference resolves inside the same snapshot;
- mappings remain available after later publication;
- semantic clones have the same hash despite different row/version IDs;
- every decision-relevant dimension, relationship discriminator, mapping, and policy field changes the semantic hash while incidental audit metadata does not;
- sealed interpretation, metrics, snapshot, and generation payloads reject mutation while operational transitions remain append-only;
- specialization cycles are rejected; and
- contradictory distinct/equivalent/specialization assertions are rejected.

### Source and measurement

- adding lens eligibility does not invoke extraction;
- the same post through legacy and Social shares one source family;
- old extraction is reproducible after translation or grounding changes;
- eligibility alone does not create a channel score;
- structured technical signals persist with policy provenance;
- multiple root/signal rows from one source family/day cannot multiply technical weight;
- percentile ties, one-theme cohorts, inclusive boundaries, and `available_at` decay match the V1 formula;
- establishment fails without cross-security breadth even when article/source thresholds pass;
- Fundamental Attention rises for either positive or negative fundamental reports and makes no direction claim; and
- missing metric components remain explicitly unavailable.

### Authorization, durable operations, and benchmark

- anonymous or incorrectly authenticated callers cannot preview/apply semantic writes, change mode, publish manually, or start recovery;
- stored operation actors come from `AdminPrincipal` or the configured refresh service principal, never `X-Admin-Actor`;
- operation, proposal, override, migration-progress, and serving-generation transitions are append-only and generation-pinnable;
- embedding cache loss triggers deterministic recomputation/fallback without changing identity; and
- every required benchmark fixture has explicit expected and forbidden outcomes, and any mismatch exits nonzero.

Required PostgreSQL concurrency tests are enumerated by exact node ID in the CI release gate. The gate fails if a required test is missing, not collected, skipped, xfailed, or does not run against PostgreSQL. A green result with zero collected tests or any skip is a failure.

## 20. Relationship to ADR-0003

ADR-0003 remains authoritative for `StockUniverse` and stock-identifier point-in-time reconstruction. Its audit-log decision is not a universal ban on immutable snapshots.

Economic taxonomy semantics use sealed snapshots because an entire graph, alias set, facet set, mapping set, and lifecycle state must be published coherently. Runtime facts remain append-only: evidence packets, processing requests, classification attempts, assignments, observations, developments, decisions, source revision logs, outbox deliveries, and interpretation selections are historical records. Historical reads select a serving generation and its complete generation-input manifest rather than reconstructing an unversioned semantic graph from mutation logs.

This distinction is recorded in a dedicated taxonomy ADR. It does not change the stock-universe hot path or identifier lifecycle.

## 21. Deferred work and entry decisions

The following work is deliberately outside this implementation. These items do not block the V1 taxonomy because V1 uses explicit attention labels, restored cross-security breadth, bounded one-hop derivation, and generation-pinned facts.

### 21.1 Economic driver pack and directional fundamentals

V1 `Fundamental Attention` is unsigned. A later economic-driver pack may add improving/deteriorating direction, driver categories, transmission paths, issuer materiality, and directional aggregation. Before that project starts, its design must settle:

1. **Driver vocabulary:** governed categories for demand, pricing, volume, capacity, cost/input, margin, regulation, financing, and supply; treatment of mixed, neutral, and unknown direction.
2. **Attribution grain:** whether direction is asserted at claim, company, constituent, theme, or development level, and how one claim affecting several levels is represented without duplication.
3. **Materiality:** whether issuer revenue/profit exposure is required, what data supports it, and how estimates/confidence are versioned.
4. **Corroboration:** whether and how publisher ownership, common upstream sources, syndicated text, or correlated analyst reports establish dependence. Distinct source families alone remain only a deduplication count.
5. **Point-in-time behavior:** which of `published_at`, `available_at`, effective period, revision, and restatement controls backtests and corrections.
6. **Aggregation:** polarity scale, weights, decay, netting of conflicting drivers, missing-data behavior, and whether a directional score is absolute or benchmark-relative.
7. **Ground truth and evaluation:** labeled fixtures, reviewer workflow, minimum precision/recall or calibration thresholds, and drift monitoring.
8. **Provider and budget contract:** extraction schema/model versions, fallback behavior, and incremental model-call budget.
9. **Persistence/publication:** append-only driver observations and decisions, generation-input pinning, correction-to-empty behavior, API names, and compatibility with existing `fundamental_attention` history.

The entry gate is an approved driver-pack design/ADR answering all nine items plus a representative labeled dataset. The current taxonomy must not reserve misleading `momentum` fields in anticipation of that work.

### 21.2 Other deferred capabilities

| Deferred capability | Required decision before work starts |
|---|---|
| Retire legacy Theme/Social storage and compatibility writes | Rollback-support end date, data-retention/export policy, consumer inventory showing zero legacy reads, and an irreversible cleanup approval. |
| Automatically approve new dimensions, merges, splits, mechanism changes, or retirement | Reviewer/accountability policy, confidence thresholds, reversible remediation, blast-radius limits, and audited evaluation demonstrating acceptable false-positive cost. |
| Recursive ontology propagation | Maximum depth, cycle semantics, attenuation/deduplication rules, and product evidence that one-hop derivation is insufficient. |
| General asset master beyond `StockUniverse` | Required asset classes, identifier authority, corporate-action lifecycle, market coverage, and migration ownership. |
| Statistical source independence | Definition of dependence, publisher/source graph data, update cadence, and validation showing that the independence signal improves decisions. |

## 22. Non-goals

- Deleting legacy themes or Social associations during this project.
- Treating embeddings as an identity authority.
- Automatically approving review-required structural changes.
- Replacing `StockUniverse` identifier authority.
- Guaranteeing immediate rollback while compatibility projections are known unhealthy.
- Inferring improving or deteriorating fundamentals from eligibility or unsigned attention counts.
- Solving any section 21 entry decision inside the taxonomy migration.

## 23. Implementation-plan alignment gate

The approved implementation plan satisfies this gate by making its Task 0 turn these contracts into executable interfaces, state machines, migrations, and test fixtures before schema work:

1. stable processing requests, reusable extraction/review artifacts, exact classification attempts, and route-independent lineage;
2. complete generation-input selection for eligibility, decisions, developments, overrides, mappings, and compatibility projections;
3. projection-revision ordering and complete-source replacement payloads;
4. bounded-cutoff publication progress and automatic economic-mode refresh;
5. immutable payload sealing versus append-only operational transitions;
6. durable embeddings, proposals, operations, overrides, migration progress, and development provenance;
7. authenticated administrator/service-principal authority;
8. cardinality-safe mapping, redirect, and Social-decision contracts; and
9. executable lifecycle, Fundamental Attention, signal weighting, benchmark, and release-gate contracts.

Task 0 is required to produce failing counterexample tests and schema/interface decisions before the schema tasks begin. It also verifies and updates the already-present `docs/adr/0005-economic-taxonomy-snapshots-and-interpretations.md`; it must not assume the ADR is absent or create a duplicate. Production economic mode remains impossible until authority-aware readers and the full release gate are complete.
