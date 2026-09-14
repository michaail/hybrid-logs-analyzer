<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Frontend role signals

- **Plan**: context/changes/testing-frontend-role-signals/plan.md
- **Scope**: Phase 1–3 of 3
- **Date**: 2026-09-14
- **Verdict**: APPROVED
- **Findings**: 0 critical 1 warnings 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | WARNING |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — §2 risk #6 rewrite landed with Phase 3 despite freeze

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: context/foundation/test-plan.md:55, :66
- **Detail**: Phase 3 said do not edit §1–§2 (already backported). The working tree already held a research backport of risk #6 (Select is not a role 403; buttons stay visible). That backport was staged with the Phase 3 cookbook commit (`056cefb`) because `test-plan.md` was in the touched set. No file:line was added to §2. Content matches research; the freeze was still crossed at commit time.
- **Fix A ⭐ Recommended**: Keep the backport. It is the intended §2 guidance from research; reverting would restore the stale “denied actions stay denied in the UI” line.
  - Strength: Cookbook and risk map stay consistent; no file:line in §2.
  - Tradeoff: Strategy section was edited in an implement commit rather than a dedicated research/refresh commit.
  - Confidence: HIGH — research Open Questions / backport notes asked for this wording.
  - Blind spot: None significant.
- **Fix B**: Revert §2 to the pre-backport rows.
  - Strength: Literal freeze compliance.
  - Tradeoff: Restores incorrect Select/availability guidance that Phase 3’s cookbook then has to contradict.
  - Confidence: LOW — would make §2 fight §6.3.
  - Blind spot: Readers of §2 alone would again treat disabled Select as Operator deny.
- **Decision**: PENDING

### F2 — §7 publication E2E bullet mentions the Operator Banner spec

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: context/foundation/test-plan.md:368
- **Detail**: Phase 3 listed §6.7 for the Operator Banner spec, not §7. §7’s “publication E2E is limited to eligible publish and ineligible reject” line was extended so it does not contradict the new spec. Analysis, intake, Test C, and screenshots stay excluded.
- **Fix**: Keep the §7 sentence. It only restates §6.7 so negative space does not forbid the shipped Banner spec.
- **Decision**: PENDING

### F3 — Repo-root Playwright artifacts are not gitignored

- **Severity**: 💬 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: .gitignore:33-37
- **Detail**: Ignore rules cover `frontend/test-results/` and `frontend/playwright-report/`. Running Playwright from the repo root (or leftover deliberate-break traces) wrote `test-results/` and `playwright-report/` at the root. Those folders were left unstaged. A leftover `error-context` from the Phase 2 deliberate break (Banners forced to `role="status"`) was later misread as a live alert-locator failure; re-running `operator-denied-register-publish.spec.ts` after the revert is green (3 passed).
- **Fix**: Ignore root `test-results/` and `playwright-report/`, or only invoke E2E via `npm --prefix frontend run test:e2e`.
- **Decision**: PENDING
