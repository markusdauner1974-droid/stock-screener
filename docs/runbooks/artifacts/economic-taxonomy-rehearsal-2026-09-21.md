# Economic Taxonomy V1 PostgreSQL rehearsal — 2026-09-21

This artifact records the Task 19 cutover and recovery rehearsal. It is release
evidence for the implementation, not authorization to reuse the recorded IDs in
production. Production must repeat the runbook against its own backup, provider
binding, evidence cutoff, reader capability, and benchmark export.

## Environment and gate

- Git branch: `feat/economic-taxonomy`
- Database engine: PostgreSQL in a disposable local container
- Gate database: `ci_task19` (empty and disposable)
- Rehearsal target database: `ci_task19_target` (empty before migration)
- Migration result: Alembic head `0054`
- Exact PostgreSQL contract gate: all 21 required nodes passed with zero skips,
  xfails, xpasses, missing nodes, or non-PostgreSQL substitutions
- Final portable reader consumer-test hash:
  `d04bdf17cdf2d84e8f1ec9f64cf98cc144c89fa003ed448c0ecbcd51cd88f5e3`
- Final portable reader capability manifest:
  `a3391b7b-4fd2-4d8e-8e28-5d3734ec3276`

The publication sequence below originally used capability manifest
`54a132da-a2c1-4acb-b8b3-f80b6ef4240a` with equivalent consumer contents. The
final gate registered the new manifest after normalizing the hash to use
repository-relative paths, making it stable across checkout locations.

The target was seeded with a legacy Refining cluster whose two mentions require
Petroleum Refining and Metals Refining allocations, duplicate legacy AI Memory
clusters, duplicate Social associations for MU with conflicting accepted and
rejected administrator decisions, and legacy authority at epoch 1. Focused
contract coverage additionally exercises a Social-native development,
corrected-to-empty evidence, and generation-scoped UI snapshots.

## Reviewed migration and Social reconciliation

| Artifact | Recorded value |
|---|---|
| Sealed taxonomy version | `dd7aeaf3-0749-4482-89c7-4a0e12a3e3f7` |
| Taxonomy semantic hash | `5bb13c4d527180b4902f105d9bb7c73f31f07c45ee4026198ecc4a34dc980f9d` |
| Taxonomy artifact hash | `01c42a9fbedf83018a2edb5306cae26e940d97400e61e893fe59c78e04f73ffa` |
| Migration run | `e09cad64-cf9f-44c2-a90d-1205bd81d785` |
| Replay-manifest hash | `8847834d6f2f9f479638c8025eb86e2f012aee6ac42322866e89c36535caf6d4` |
| Petroleum Refining theme | `9a8add2c-4ff5-4444-a815-a312476274a1` |
| Metals Refining theme | `f6c39b22-0560-4abb-bffa-de027e6fe185` |
| Reconciled Social association | `1b8e921c-fd7f-43e0-89c1-1a1db93effb5` |

The split stayed incomplete until each Refining mention was explicitly
allocated. Both legacy AI Memory identities were reviewed as equivalent to one
global identity. The Social projection first produced immutable revision
`022f4f1c-b548-436b-9c3d-33add621d196` with
`conflict_review_required`; it did not become live. An explicit administrator
decision produced accepted revision
`fa9c0bf0-15fa-4249-8148-8dc768ab56e7`. Both revisions remain queryable.

## Publication sequence

| Mode | Generation | Interpretation | Input manifest / hash | Metrics | Reader snapshot / hash |
|---|---|---|---|---|---|
| shadow | `254ddb43-82e2-4cec-a9b7-718cc1439aca` | `dfef275d-773a-4c6b-8d0a-8d2bdc5c8100` | `4b665b8c-fdb5-4e19-900c-42b81629cf4c` / `8665a0da1dd43bdaa37aa0929b4f64d41d727d01a7aca5ff33f8415e0b237532` | `f719b02b-6d0d-4af7-8eb2-cb12ef55f7b6` | `1e9d8c2d-6874-46f0-92f5-921cec3038c9` / `6b9a6b11ab6e56bb5f045ce9cf5f664df6725cdf7326d9a83383f3618116f870` |
| dual | `02598e42-762b-461a-a5a7-c4110ab341f2` | `79fca5a2-17d4-4c22-acc7-615f32eedf14` | `d7a63c15-bf64-446c-b408-68e18aef3fb3` / `cee348a8055f89fca8ace32359e88073182976fd7219448dc3d120f210f8b279` | `6d4cbf6b-c5d9-4829-a36e-ee006476d02c` | `46b5ddbd-5e3e-4d1a-b95b-e9e5b1159709` / `663f35cec5b9aa8bd154829d7b894ce7a02276d8a7f1ddeaa8a6761f9b4b34db` |
| economic | `73b74209-695b-4332-a359-836dc4095219` | `11a0a391-f2e5-4a36-a55d-713d7793695b` | `40dc6f29-c9af-4905-8ee2-44514d53e0c6` / `6cc0a799556f0ea3a46d1bcf4e1e14cd31523434b35faab29378442701108220` | `8c2cb532-b96c-42f4-9632-16c53c8a8ae1` | `1641d02d-6ddb-47a5-8306-a108dae91f63` / `4ea5866ff8fa0af7cbda8c9708992b0b09d22dd718190ff9f20748b1dd793712` |

After economic publication the authority was at epoch 4 with rollback state
`ready`; both reader pointers selected the economic snapshot. The economic
catalog hash was
`f9936afe9ccd78b9c4ce628ea2df2cdcca434a06399f901b2b7d7db8ee2073b2`.

## Ordering, rollback, and recovery evidence

An out-of-order compatibility checkpoint used lineage
`rehearsal:out-of-order`: revision 2 applied, revision 1 was a stale no-op, and
the retained payload was `{"themes":["new"]}` at revision 2.

The pre-cutover legacy reader hash was
`2b65635247e33036754e58353988a2276c7d29a54a44233b219f426f799988bd`.
Normal rollback published generation
`d492c703-2a79-4efb-adf3-a4d687421b68`, advanced authority to epoch 5 in
`legacy` mode with rollback state `ready`, and reproduced the exact legacy hash.
The superseded economic snapshot remained reproducible.

Recovery was then rehearsed by republishing economic generation
`f97003d2-66b7-447f-99f0-f939a23a9caf`, staging an unacknowledged compatibility
event `2773558b-0734-4518-8efd-c1d5151d9820`, and observing epoch 6 with
`temporarily_unavailable`. Rollback entered `rollback_recovery`, rebuilt the
ordered legacy projection, recorded recovery revision
`5e95ba62-8801-4668-93e8-6614089b1709`, and published legacy generation
`79804812-5be7-4932-b9d8-675d31ec1df8` at epoch 7 with rollback state `ready`.
The `rehearsal:rollback-recovery` checkpoint retained revision 1 and its
payload.

## Outcome and production prerequisites

The migration cardinalities, Social decision preservation, immutable
interpretations, atomic reader pointers, stale-delivery protection, normal
rollback, and unhealthy-delivery recovery all behaved as specified.

Production still must satisfy the runbook's environment-specific gates. In
particular, the worker must build the default extraction, review, resolution,
and Social-budget pipeline from a sanctioned provider credential (or install an
explicit `configure_economic_taxonomy_pipeline(...)` override), complete a
synthetic provider request, and generate the non-tautological shadow benchmark
export. These are explicit pre-shadow stop conditions, not deferred product
work. No capability listed in the runbook's Deferred Work Boundary is required
for V1 cutover.
