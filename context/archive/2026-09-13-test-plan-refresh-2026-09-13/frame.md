# Frame Brief: Test-plan refresh after S-04–S-06

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

S-04–S-06 are done, but the written test plan still treats publication,
admission, and role-signal work as the unfinished rollout. Analysis-runner
and configuration changes are the area changed without confidence, and the
additions after S-03 feel under-tested.

## Initial Framing (preserved)

- **User's stated cause or approach**: The plan is stale because S-04–S-06
  landed; five refresh priorities (runner/config, terminal-failure truth,
  dataset/run/result isolation, provisional vs final outcomes, paging/UI
  signals) are the new risk surface.
- **User's proposed direction**: Refresh `context/foundation/test-plan.md`
  around those five priorities, without new ML-job, parity, or
  checksum/compliance coverage, while keeping the untrusted `.pt`
  control-plane boundary.
- **Pre-dispatch narrowing**: The written test plan still describes a
  pre-analysis product, while S-04–S-06 are already done.

## Dimension Map

The observation could originate at any of these dimensions:

1. **Strategy freeze** — §1–§2 never named analysis-runner, terminal-status,
   provisional-outcome, or paging failures; runs/results appear only as
   isolation objects.
2. **Stale bookkeeping** — §3 statuses, §4 test-base counts, and §7
   “S-03 not implemented / parity waits for S-04” make the guide look
   pre-analysis even if the intended ranking were unchanged. ← initial
   “document is behind the product” framing
3. **Cookbook lag** — S-04–S-06 tests already exist; §6 still TBD or
   isolation-only, so the written strategy looks earlier than the suite.
4. **Unfinished original phases** — Phases 2–4 still occupy the live §3
   table as `not started`, so a reader sees a publication-era plan.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| Strategy freeze: §2 has no FR-006 / FR-007 / FR-012 rows | `test-plan.md:33-36`, `:48-55`; `prd.md:124-136`; `roadmap.md:68-70`; grep of `test-plan.md` has no `provisional`, `paging`, or `FR-006` | STRONG |
| Stale bookkeeping: §3/§4/§7 still pre-S-03 | Phase 1 `change opened` vs archived isolation change (`test-plan.md:74`; archive `testing-critical-path-api-isolation/change.md:4-7`); §4 `~8` files / CI skips `@ml` (`test-plan.md:103`) vs 15 `test_*.py` and `verify.yml:30-44` `@ml` inference; §7 S-03 unimplemented / parity waits for S-04 (`test-plan.md:253-255`) vs roadmap Done (`roadmap.md:295-299`) | STRONG |
| Cookbook lag: tests exist, §6 unnamed | Result/provisional/dispatch tests in `tests/test_api.py`, `tests/test_inference_service.py`, `tests/test_shared_state_repository.py`; §6.3/§6.5 still TBD (`test-plan.md:187-211`); no cookbook oracles for terminal status, paging, or provisional vs final | STRONG |
| Unfinished Phases 2–4 occupy §3 | `test-plan.md:75-77` `not started`; no matching `context/changes/` folders; S-04–S-06 archived. Risk #1 and §6.2 already claim runs/results (and tell not to duplicate dataset IDOR) | STRONG |

## Narrowing Signals

- The mismatch seen is ledger/cookbook: the guide still talks as if those
  slices and their tests have not shipped — not “the risk map is blank
  and nothing is tested.”
- Cross-project deny for datasets, runs, and results already looks covered
  in the existing HTTP tests / cookbook (Phase 1 risk #1, §6.2).
- Independent of rewriting the guide, analysis-runner, terminal status, and
  provisional/result semantics now feel like the leading *unlisted* risks.

## Cross-System Convention

The test-plan skill freezes §1–§5 at write time; only §3 status cells move
on resume. Completing a product slice updates `roadmap.md` and
`context/archive/`; it does not rewrite the guide. `/10x-test-plan --refresh`
opens a dated change and must not edit the guide in place until that chain
lands (`.cursor/skills/10x-test-plan/SKILL.md` `--refresh` / freeze rules).
A same-day Playwright E2E edit bumped `Last updated: 2026-09-13` and §8
review dates without correcting §7 product assumptions — false freshness
on top of the freeze.

Independent look (no hypothesized cause named) ranked: (1) this refresh
change is open and has not rewritten the guide yet; (2) intentional
strategy freeze vs decoupled product archive; (3) date-stamp without
§7 catch-up. (1) is why the file is still stale *today*; (2) is why it
went stale when S-04–S-06 shipped.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: the frozen test-plan ledger,
> negative space, and cookbook still describe a pre-S-04 product, so they
> cannot tell what S-04–S-06 already protect from the remaining
> analysis-runner, terminal-status, and provisional/result gaps.

The initial five-priority brief mixed a real ranking shift with a
green-field isolation workstream. Isolation of datasets, runs, and
results is already claimed in Phase 1 / §6.2 — do not plan it as new
coverage. Many result-paging, queued/failed, provisional-without-score,
and dispatch tests already exist and are unnamed in §6; “under-tested
after S-03” is partly a documentation failure. Original Phases 2–4
(admission, frontend signals, CI wiring) are still the pending §3 rows,
but admission/CI wording is itself stale (validator/env-scrub tests and
an Ubuntu `@ml` inference job already exist) — research must reconcile
those rows rather than assume they are empty.

Do not add a new ML-job, parity, or checksum/compliance suite. Keep the
untrusted `.pt` control-plane boundary.

## Confidence

- **HIGH** — all four dimensions have on-disk evidence; independent search
  landed on freeze + unfinished refresh; narrowing ruled isolation-as-new
  out and kept analysis/result semantics as the leading unlisted risks.

## What Changes for /10x-plan

Plan the refresh as a reconciliation of the written guide with the shipped
HDFS analysis/result product: correct ledger/§7/§4, name existing oracles
in §6, re-rank unnamed runner/terminal/provisional scenarios against tests
that already exist, and leave cross-project isolation as claimed Phase 1
work. Do not commission five parallel new test programs.

## References

- Source files: `context/foundation/test-plan.md:33-77`, `:103`, `:187-255`;
  `context/foundation/roadmap.md:68-70`, `:295-299`;
  `context/foundation/prd.md:124-136`;
  `.github/workflows/verify.yml:28-44`;
  `context/archive/2026-09-10-testing-critical-path-api-isolation/change.md`;
  `tests/test_api.py` (result/provisional/dispatch tests unnamed in §6)
- Related research: not present (`context/changes/test-plan-refresh-2026-09-13/research.md`)
- Investigation tasks: frozen risk map `00618f9d-b5f1-432e-b561-85b2cadddc90`;
  stale bookkeeping `8288af85-82d9-47cd-be7b-545a524031c6`;
  existing post-S-03 tests `2bb1c755-6aaf-499c-90c4-b9a2ad4adabf`;
  unfinished original phases `b83cc3b9-6545-4ce3-a3f1-69b4cccba362`;
  independent stale-guide cause `7ebf4db9-cd99-4850-88d2-6a6b0fb094a8`
