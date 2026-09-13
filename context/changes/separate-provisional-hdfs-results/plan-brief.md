# Separate Provisional HDFS Results — Plan Brief

> Full plan: `context/changes/separate-provisional-hdfs-results/plan.md`

## What & Why

An admitted HDFS upload can contain block histories that extend beyond its available lines.
S-06 will prevent those histories from appearing as ordinary anomalies or normal outcomes:
unselected blocks become separately inspectable provisional results with context and a reason.

The chosen policy is explicitly a heuristic, not proof that an HDFS lifecycle has ended.
Membership in a server-pinned F-03 evaluation-data catalog makes a result **heuristically
final**; a block absent from that catalog is provisional and never receives a score.

## Starting Point

The current frozen inference function groups and scores every block, then the private runner
persists only detected anomaly rows. The existing result endpoint and dialog provide
project-scoped anomaly paging, run-wide counts, source context, and provenance, but have no
provisional outcome type.

## Desired End State

An Operator opens a completed HDFS run and sees heuristic anomaly/normal counts distinct from
provisional histories and unassigned context lines. They can open a separately paginated
provisional panel to see each block's reason and bounded source-log context, but no score,
threshold, or anomaly level.

Every completed split result records the exact F-03 catalog manifest SHA-256 and policy version
used by the isolated inference service. If that configured catalog is missing or changes, the
run fails safely rather than selecting a newer artifact or changing classifications silently.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Result semantics | `heuristically final` vs `provisional` | Block-ID membership does not prove a complete lifecycle, so an unqualified final label would be misleading. |
| Catalog source | Explicit F-03 manifest path + SHA-256 | Maintains deterministic provenance without selecting a newest runtime artifact. |
| Membership rule | Block ID is present in the selected-ID catalog | This is the user-selected, consciously limited heuristic. |
| Missing membership | Provisional `not_in_reference_catalog` | Supports mixed runs without inventing events or an optimistic decision. |
| Scoring | Skip all provisional blocks | Enforces that a provisional history has no model decision and avoids needless ML work. |
| No-ID lines | Report only an unassigned-context count | Makes dropped HDFS bookkeeping context visible without assigning it to an invented block. |
| Persistence/API | Dedicated table and separately paged GET route | Keeps the existing anomaly schema, score filters, and keyset paging focused on scored results. |

## Scope

**In scope:**

- FR-012/US-03 and documentation amendment for the heuristic policy.
- Integrity-checked F-03 catalog loading by the private inference service.
- Additive storage/migration, API, typed frontend contract, and dialog panel for provisional
  results.
- Regression, project-isolation, migration, and real inference-subprocess coverage.

**Out of scope:**

- Lifecycle-event detection, time watermarks, source-history backfill, or a claim of proof.
- Runtime newest-artifact discovery, Operator-provided catalog uploads, catalog-management UI,
  historical run reclassification, non-HDFS datasets, and model training.

## Architecture / Approach

At run execution, the private service verifies the deployment-pinned F-03 manifest and its
selected-ID file, then partitions annotated HDFS sequences before graph construction. Only
catalog-member IDs enter the GAE scorer. The completed-run transaction writes anomaly rows,
provisional context rows, counts, and policy provenance atomically; FastAPI serves separate
pages, and React loads provisional rows only when the Operator opens their panel.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Policy and catalog | Honest requirements, docs, typed pinned-catalog loader | Misrepresenting the heuristic as lifecycle evidence |
| 2. Persistence | Additive table, provenance/count columns, atomic paging | Cursor or transaction cross-contamination |
| 3. Inference split | Pre-graph partitioning and no-score provisional records | Accidentally changing frozen parity behavior |
| 4. API and UI | Separate authorized endpoint and paged results panel | Mixing provisional rows with anomaly semantics |
| 5. Regression/rollout | Real service-process test and deployment guide | Native ML environment and migration order |

**Prerequisites:** A valid F-03 evaluation-data artifact must be generated in ignored workspace
storage and its manifest path/SHA-256 made available only to the inference service.

**Estimated effort:** ~3–5 implementation sessions across five reviewable phases.

## Open Risks & Assumptions

- The chosen block-ID membership heuristic can classify a truncated history with a known ID as
  heuristic-final. The UI and documentation must make that residual risk explicit.
- Catalog artifacts are generated runtime data: retain the artifact and checksum outside Git for
  reproducibility.
- The full PyTorch suite and new subprocess test need a normal local ML environment, not
  Cursor's restricted native-library sandbox.

## Success Criteria (Summary)

- A mixed HDFS run stores scoreless provisional context separately and excludes it from
  heuristic anomaly/normal counts.
- Operators can inspect provisional pages only within authorized projects and never see a
  provisional score.
- Catalog changes fail safely, existing parity stays stable when unfiltered, and migration
  preserves historical runs.
