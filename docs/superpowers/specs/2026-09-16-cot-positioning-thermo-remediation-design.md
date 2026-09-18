# COT Positioning Thermo-Review Remediation

**Date:** 2026-09-16

**Status:** Approved direction; implementation authorized

**Builds on:** `2026-09-16-cot-positioning-design.md`

## Context

The COT feature implements the approved live and static product behavior. A
strict maintainability review found six structural problems: the snapshot read
fans out through per-instrument history calls, no-change detection ignores
versioned derivation inputs, the application ports do not describe the real
dependencies, static global artifacts are wired through copy-paste branches,
COT source metadata has several owners, and retry/static helper refactors move
or duplicate complexity instead of removing it.

This remediation changes internal ownership only. It preserves the curated 31
instruments, CFTC Futures Only sources, calculations, database schema, public
API payloads, frontend behavior, task names, static paths, and fallback policy.

## Goals

- Make publication reuse depend on the complete versioned input signature.
- Serve the live snapshot with bounded batch reads rather than 31 histories.
- Replace `Any` application dependencies with narrow typed protocols and DTOs.
- Give report-family dataset metadata and schema versions one canonical owner.
- Parameterize common global static-artifact discovery and fallback mechanics.
- Collapse duplicate CFTC retry loops and duplicate static JSON helpers.
- Remove the one-call RRG wrapper that only relocates exception translation.

## Non-goals

- Changing any COT chart, table, label, range, price classification, or route.
- Adding a new price provider or making price availability block publication.
- Changing tables or migrating published COT rows.
- Generating GitHub Actions YAML or building a generic workflow framework.
- General refactoring outside code touched by the COT integration.

## Canonical COT metadata

`CotDatasetDefinition` is the sole backend owner of each report family's CFTC
dataset ID, label, public URL, and participant field mapping. Provider fetch,
validation, catalog responses, and history metadata consume that definition.

`CotInstrumentSpec` replaces positional string tuples with typed category,
report-family, and price-mapping values. Exceptional metadata such as Canola's
TradingView URL lives in its own spec entry rather than a slug conditional.

All COT version constants remain in `domain/cot/models.py`. Static contracts
import `STATIC_COT_SCHEMA_VERSION` instead of redeclaring it.

## Typed application boundaries

The application layer exposes separate protocols for:

- `CotWriteRepository`: run creation, validation inputs, publication signature,
  publication, no-change, and failure transitions;
- `CotReadRepository`: publication, history, and batched snapshot rows;
- `CotPriceReader`: one-symbol and multi-symbol cached price reads;
- `CotPriceHydratorPort`: typed best-effort hydration results.

Read protocols return application DTOs/protocol records rather than `Any`.
Composition remains responsible for SQLAlchemy implementations.

## Version-aware publication identity

No-change detection compares a `CotPublicationSignature` containing:

- source row fingerprints;
- registry version;
- calculation version;
- schema version.

The SQL repository builds the stored signature from the currently published
run and persisted rows. Any source correction or version change forces a fresh
derivation and publication. Identical signatures retain the existing pointer.

## Batched snapshot read

The snapshot repository query returns the most recent 52 report weeks for the
focal participant of every active instrument in curated order. The query
service fetches publication once, builds all rows in one pass, and requests
cached prices through one batch price-reader call. The existing single-history
path remains unchanged for chart requests and static per-instrument export.

The 52-week batch preserves the existing one-year price-coverage semantics;
only the most recent 12 net values are exposed as the table trend.

The snapshot endpoint continues returning the exact existing payload. Cache
behavior remains publication-keyed.

## Static global-artifact mechanics

`StaticGlobalArtifactSpec` describes the common mechanics for independently
published root assets: logical key, GitHub artifact name, directory name,
manifest filename, validator, validation error, and as-of-date field.

Fallback download and validation scripts iterate the canonical specifications
instead of maintaining COT- and Options-specific discovery branches. Product
composition remains in `StaticCotSection` and `StaticOptionsSection` because
their compatibility and manifest rules differ. The workflow continues naming
the two concrete artifacts explicitly, which is required by GitHub Actions,
but Python orchestration no longer duplicates selection mechanics.

Shared `static_artifact_io` helpers own finite JSON loading, safe rooted path
resolution, and isolated JSON writing. COT and Options contracts supply their
own error constructors and semantic validation.

## Provider and RRG cleanup

`CftcCotSource` has one bounded request/retry operation returning decoded JSON
plus retry count. Page and count methods provide only request parameters and
payload decoders, preventing retry-policy drift.

The existing optional-section handler translates RRG source failures into its
canonical unavailable payload. The lower-level RRG source remains independent
of site-export policy, while the 40-line wrapper module and pass-through service
method are removed.

## Verification

Every behavioral correction starts with a focused failing test. New coverage
proves:

- version-only changes force publication;
- identical complete signatures retain no-change behavior;
- snapshot construction uses one batched repository read and one price batch;
- concrete repositories and fakes conform to the typed ports;
- all report-family metadata comes from one definition;
- global artifact discovery/validation handles both Options and COT specs;
- page and count requests share retry semantics;
- direct and combined static COT output remains byte-contract compatible.

Final verification runs focused COT/static suites, the complete backend test
suite, frontend tests and lint, production frontend build, and `git diff --check`.
