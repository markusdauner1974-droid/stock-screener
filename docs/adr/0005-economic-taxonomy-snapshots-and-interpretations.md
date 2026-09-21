# Economic taxonomy uses sealed semantic snapshots and selected append-only interpretations

Economic taxonomy semantics are published as sealed snapshots, while runtime evidence and classification history remain append-only. A serving generation selects one taxonomy snapshot, one accepted interpretation set, one evidence manifest, one metrics revision, and one reader snapshot bundle. Readers never combine independently selected “latest” rows.

## Context

ADR-0003 chooses audit-log-based point-in-time reconstruction for `StockUniverse` and stock identifiers. That decision preserves their existing mutable hot path and uniqueness constraints. It does not define the publication model for a semantic graph whose names, aliases, facets, relationships, lifecycle states, legacy mappings, and redirects must change coherently.

Economic taxonomy also needs to preserve corrections and reclassifications. Overwriting observations loses history, while unioning every historical classification makes corrected or superseded evidence remain current. Semantic publication and runtime interpretation history therefore need distinct versioning mechanisms.

## Considered Options

- **Use mutable taxonomy rows plus an audit log** — rejected because graph-wide validation, hashing, and atomic reader publication would require reconstructing a consistent semantic state for every historical read.
- **Snapshot every runtime fact inside each taxonomy version** — rejected because it duplicates high-volume evidence, obscures stable provenance, and makes failed or experimental reprocessing look authoritative.
- **Use sealed semantic snapshots plus append-only runtime facts and explicit interpretation selection** — chosen. Semantic graph state is cloned and sealed; evidence packets, classification runs, claim assignments, observations, developments, decisions, revision logs, and outbox deliveries remain append-only. Each serving generation selects the accepted runtime interpretation.

## Consequences

- A sealed taxonomy version and its owned semantic rows are immutable and hashable.
- Stable Economic Theme UUIDs survive compatible changes; a merge uses a versioned redirect rather than rewriting identity.
- A successful correction creates a new evidence packet and classification run. A serving generation can select it, including a completed run with zero assignments, without deleting the prior interpretation.
- Failed or partial reprocessing does not replace the last accepted interpretation.
- Historical taxonomy reads specify a serving generation or interpretation-set ID.
- Every serving change uses one publication coordinator that atomically switches the taxonomy, interpretation, metrics, and reader pointers.
- `StockUniverse` and stock identifiers continue to follow ADR-0003. This ADR does not introduce spatial row versioning into those domains.
