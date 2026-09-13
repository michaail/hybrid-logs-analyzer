# Inspect HDFS analysis results — Plan Brief

> Full plan: `context/changes/inspect-hdfs-analysis-results/plan.md`

## What & Why

This S-05 change turns the existing completed-run output into an operator-ready HDFS
investigation surface. It exposes traceable anomaly blocks, their model/version provenance,
scores, thresholds, and bounded source-log context without changing the validated scoring path.

The current system stores this evidence but returns it as an unbounded loose API shape and hides
the context/model trace in the browser. Pagination and typed contracts make results useful for
large runs without weakening project isolation.

## Starting Point

S-04 persists only detected HDFS block anomalies plus whole-run summary counts. It already stores
capped source context, but `GET .../results` returns all anomalies and the existing dialog shows
only the generic block reference, score, and threshold.

## Desired End State

An Operator can inspect one bounded page of anomalies at a time, filter by block ID or score, and
move deterministically across pages. Each result clearly identifies the scored HDFS block and
shows expandable contextual lines in scoring order, while the dialog surfaces its exact run and
model identity plus expandable immutable provenance.

Normal, rejected, and invalid counts remain clear run-wide summaries. Provisional outcomes and
historical rejected uploads remain separate work, so this view does not mislabel incomplete
histories as final decisions.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Change identity | Rename to `inspect-hdfs-analysis-results` | It exactly matches roadmap S-05 and preserves lifecycle tracking | Plan |
| Slice boundary | Finalized anomaly inspection only | Provisional blocks are S-06; rejected uploads have no result row | Roadmap / Plan |
| Block field | Add `block_id`, retain `record_reference` | Clear HDFS semantics without a needless compatibility break | Plan |
| Provenance | Essentials visible; checksums/bundle in disclosure | Meets traceability needs without crowding routine reviews | Plan |
| Log evidence | Expandable, scoring-order context with source lines | Uses already persisted bounded evidence and preserves score semantics | Research / Plan |
| Large result access | Keyset pages of 50, maximum 100 | Bounds payloads and remains deterministic at 25,000 blocks | Plan |
| Verification | API/repository tests plus TypeScript build and manual UI script | Fits the current test toolchain without adding another frontend runner | Plan |

## Scope

**In scope:**
- Typed read-only results API, result-page query validation, cursors, and supporting indexes.
- Model/run/dataset/bundle provenance, anomaly block alias, bounded source context, and summary UI.
- Regression tests, current CI inclusion, and result-semantics documentation.

**Out of scope:**
- Scoring, model loading, normal or provisional result persistence, historical rejected-upload data,
  per-step progress, BGL, and new test tooling.

## Architecture / Approach

`Results dialog → typed GET /results query → project-scoped storage page + model trace`

The result route reads only the existing durable run, model, summary, and anomaly rows. A
forward-only index migration supports whitelisted keyset query paths; the React dialog refetches
only the selected page and renders raw context as escaped text.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Typed result contract | Canonical S-05 identity, typed API, keyset query, indexes | Equal-score/null-score cursor correctness |
| 2. Operator inspection UI | Filters, paging, traceability, expandable context | Dense technical evidence remains usable on small screens |
| 3. Regression and guidance | Tests, CI coverage, and documentation | Preventing scope drift into upload history or S-06 |

**Prerequisites:** S-04 is complete; a completed HDFS run with stored anomaly rows is available for
manual verification.
**Estimated effort:** ~2–3 focused implementation sessions across three phases.

## Open Risks & Assumptions

- Existing historical rows may have missing score/context fields, so the typed read projection must
  keep them readable without treating absent evidence as final data.
- The current stored 20-line × 500-character cap is sufficient for this MVP; a full raw-log detail
  endpoint is deliberately not introduced.

## Success Criteria (Summary)

- Operators can inspect project-scoped, traceable, paginated HDFS anomaly evidence.
- Query filters and ordering do not duplicate, omit, or expose rows across projects.
- The UI clearly separates whole-run summaries, upload-time rejection, and the later provisional
  result category.
