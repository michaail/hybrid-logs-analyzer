# Test-plan refresh after S-04–S-06 — Plan Brief

> Full plan: `context/changes/test-plan-refresh-2026-09-13/plan.md`
> Frame brief: `context/changes/test-plan-refresh-2026-09-13/frame.md`

## What & Why

The frozen test-plan ledger, negative space, and cookbook still describe a
pre-S-04 product, so they cannot tell what S-04–S-06 already protect from
the remaining analysis-runner, terminal-status, and provisional/result
gaps. This change rewrites `context/foundation/test-plan.md` through the
refresh folder so the guide matches the shipped HDFS analysis/result
product without commissioning five new test programs.

## Starting Point

Phase 1 isolation is archived and cookbooks exist, but §3 still says
`change opened`. S-04–S-06 tests for dispatch, queued/failed runs, paging,
and provisional pages already live in pytest and are unnamed in §6. §4/§7
still claim ~8 tests, CI without `@ml`, unimplemented S-03, and parity
waiting on S-04.

## Desired End State

A later agent can read the guide and know: isolation is done; risk #7
(analysis execution / result semantics) is named and pointed at existing
oracles; CI is a Torch-free API job plus a separate Ubuntu `@ml` inference
job; leftover object-prefix cleanup and unauthorized-role UI signals are
the only pending rollout phases.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Problem | Reconcile the guide; do not treat isolation as new work | Isolation is already claimed in Phase 1 / §6.2 | Frame |
| §2 update | Append one combined analysis/result risk (#7) | Names the leading unlisted class without eight rows or a frozen silent map | Plan |
| §3 statuses | Complete 1 and 4; narrow 2; keep 3 pending | Only claim completion the archive and `verify.yml` support | Plan |
| Frontend gap | Keep Phase 3 as component tests | Publisher Playwright specs do not prove unauthorized UI | Plan |
| CI wording | Document split jobs; do not call Verify Torch-free | `inference` already runs `-m ml` | Plan |
| Tests in this change | None | Refresh is documentation; name existing oracles | Frame / Plan |
| Exclusions | No new ML, parity, or checksum suites | Refresh interview Q5; S-04 already shipped a release gate | Frame / Plan |

## Scope

**In scope:** `context/foundation/test-plan.md` §1–§8: append risk #7,
fix §3 ledger, correct §4/§5/§7/§8, name S-04–S-06 oracles in §6.

**Out of scope:** new tests, CI YAML, frontend runner, isolation re-test,
ML/parity/checksum expansion, AGENTS.md, lockfile, non-HDFS scope.

## Architecture / Approach

One markdown file, three implementation phases: strategy/ledger/gates,
then cookbook/negative space, then orchestrator/schema verification.
Existing pytest names are cited only in §6, never as §2 anchors.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Strategy, ledger, stack, gates | Risk #7; Phase 1+4 `complete`; narrowed Phase 2; honest CI split | Over-closing Phase 2 or adding a fake §3 row for #7 |
| 2. Cookbook and §7 | Named dispatch/paging/provisional oracles; S-03/S-04 wording fixed | Rewriting isolation as new work or implying new ML suites |
| 3. Orchestrator check | Valid §3 vocabulary; no product/CI diffs | Date stamp without content (repeat of `381b057`) |

**Prerequisites:** frame brief accepted; Phase 1 archive and S-04–S-06
roadmap Done rows available as read-only evidence.
**Estimated effort:** one session across three documentation phases.

## Open Risks & Assumptions

- Leftover-prefix cleanup (risk #5) is still incomplete enough to leave
  Phase 2 `not started`; implement must not mark it complete from env-scrub
  tests alone.
- No `research.md` for this refresh; the plan grounds cookbook names in
  the frame inventory and listed test functions.
- `/10x-test-plan` after this lands should resume at narrowed Phase 2.

## Success Criteria (Summary)

- The guide’s first pending §3 phase is narrowed package-admission leftovers,
  not isolation.
- Risk #7 is visible and mapped to named existing tests in §6.
- §4/§5/§7 no longer contradict shipped slices or the split Verify jobs.
