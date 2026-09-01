---
project: "Log Anomaly Detection System"
checked_at: 2026-09-01T12:49:58Z
health_status: needs-attention
context_type: brownfield
language_family: python
stack_assessment_available: true
checks_run:
  - lockfile
  - dependency_audit
  - outdated_deps
  - test_runner
  - ci_cd
  - configuration
audit_findings:
  critical: 0
  high: 0
  moderate: 60
  low: 0
test_runner_detected: true
ci_provider: null
recommended_fixes: 3
---

## Dependency Health

### Lockfile

Status: present (`requirements-macos-intel.lock.txt`)  
Package manager: pip

The lock contains the complete local runtime and development environment verified on Intel (`x86_64`) macOS with Python 3.11.4. The maintained inputs remain `requirements.txt`, `requirements-macos-intel.txt`, and `requirements-dev.txt`. `python -m pip check` reports no broken requirements.

The older ML versions are intentional compatibility pins. Do not regenerate the lock as a routine upgrade; review Intel wheel availability and run the native test suite whenever changing it.

### Security Audit

Tool: `.venv/bin/python -m pip_audit -r requirements-macos-intel.lock.txt`  
Summary: 0 CRITICAL, 0 HIGH, 60 MODERATE, 0 LOW  
Direct vs transitive: 58 advisories affect direct requirements; 2 affect the transitive `langchain-core` dependency.

`pip-audit` did not provide CVSS scores or native severity labels for these advisories, so the audit rules classify them as MODERATE rather than inferring severity.

- **transformers 4.30.2** — 32 advisories. This version is coupled to the legacy Sentence Transformers environment.
- **torch 2.2.2** — 22 advisories. This is the verified Intel build and includes advisories relevant to unsafe model deserialization.
- **langchain-openai 0.3.7** — 2 advisories.
- **langchain-core 0.3.86** — 2 transitive advisories.
- **pyarrow 18.1.0** — 1 advisory.
- **python-dotenv 1.0.1** — 1 advisory.

The version constraint explains why these cannot be fixed by blindly upgrading. It does not remove the risk: the legacy ML runtime must not load untrusted serialized model files or be exposed directly to unauthenticated traffic.

### Outdated Dependencies

Packages with major version gaps: 9 direct packages.

These gaps are intentional Intel compatibility constraints, not automatic upgrade recommendations. The largest differences are:

- **pyarrow**: 18.1.0 → 25.0.1 (7 major versions)
- **sentence-transformers**: 2.2.2 → 6.0.1 (4 major versions)
- **openai**: 1.63.2 → 3.6.0 (2 major versions)

Review upgrades only through a separate compatibility task that confirms Intel wheels and preserves notebook-baseline results.

## Test Suite

Test runner: pytest  
Tests found: 4 tests  
Test execution: not attempted for the complete native suite; 2 dependency-light tests passing

Configuration: `pyproject.toml`  
Framework: pytest 9.1.1

`.venv/bin/python -m pytest --collect-only` succeeds and discovers all four tests. `.venv/bin/python -m pytest tests/test_artifacts.py` passes both artifact-store tests.

The complete suite imports Intel NumPy and PyTorch native libraries. Cursor's restricted execution sandbox denies their shared-memory operations, so the native parser and ML smoke tests cannot be evaluated reliably here. Run the complete suite in a normal local terminal:

```bash
source .venv/bin/activate
python -m pytest
```

The previous root-module collection failure is resolved: `tests/test_pipeline_smoke.py` imports the repository-root `run_ablation.py` consistently and defers optional ML imports until the marked ML test runs.

## CI/CD

Provider: not detected  
Configuration: not found

| Stage | Status | Notes |
| --- | --- | --- |
| Lint | ✗ | Ruff works locally; no CI configuration |
| Test | ✗ | pytest works locally; no CI configuration |
| Build | ✗ | no CI configuration |
| Type check | ✗ | mypy works locally; no CI configuration |
| Security | ✗ | pip-audit works locally; no CI configuration |

No CI/CD configuration was detected. This is expected to be addressed in the infrastructure and deployment lesson. The local lint, type, collection, and dependency checks now provide a stable development baseline.

## Configuration

### High severity

No high-severity local configuration gaps detected.

### Medium severity

No medium-severity local configuration gaps detected.

### Low severity

- **Root environment example** — `src/.env.example` exists, but `README.md` directs users to create `.env` at the repository root. Fix: add a root `.env.example` or change the documented and runtime convention to use the `src/` location consistently.

### Present configuration

- **`pyproject.toml`** — configures pytest, Ruff, mypy, and the Pydantic mypy plugin.
- **`requirements-macos-intel.lock.txt`** — pins the complete verified Intel development environment.
- **`.editorconfig`** — defines consistent editor whitespace and line-ending behavior.
- **`.gitignore`** — excludes secrets, `.venv`, generated artifacts, Python caches, and tool caches.
- **Ruff** — `ruff check src tests scripts run_ablation.py` passes.
- **mypy** — checks 29 project source files successfully with project package bases and the Pydantic plugin.
- **Pydantic** — remains pinned to 2.10.6; its mypy plugin validates typed model constructors statically.

## Stack Assessment Cross-Reference

Stack assessment: `context/foundation/stack-assessment.md`  
Agent readiness from stack assessment: ready-with-compensation

| Stack-assessment gap | Health-check finding | Status |
| --- | --- | --- |
| Python type safety | mypy and the Pydantic plugin pass across 29 project files. | Mitigated locally |
| Notebook-led conventions | Reusable modules and tests exist, but no project-specific instruction file defines production boundaries. | Still open |
| Test dependency declaration | pytest is pinned in development requirements and the complete Intel lock. | Mitigated |
| Recommended agent instructions | No `AGENTS.md` or `CLAUDE.md` exists; course rules are not project coding conventions. | Not yet addressed |

## Recommended Fixes

### Fix before agent work (Category A)

### 1. Contain the legacy ML dependency risk

**Impact**: The pinned Intel-compatible environment has 60 known advisories. The planned Publisher model-upload flow would be unsafe if arbitrary serialized model files reached `torch.load`, because model deserialization can execute code.  
**Severity**: high  
**Effort**: significant (> 1 hour)  
**Fix**:

- Accept model packages only from trusted Publishers while the legacy runtime remains.
- Define a non-executable model artifact contract; prefer tensor-only formats or load a validated state dictionary with `weights_only=True` where compatible.
- Never pass a user-uploaded artifact to the existing `weights_only=False` checkpoint loader.
- Run legacy inference in an isolated process with minimal filesystem access, no application secrets, and no unnecessary network access.
- Record the accepted advisory set and revisit it when an Intel-compatible upgrade path is tested.

### 2. Complete the native test run

**Impact**: Collection, linting, typing, and dependency-light tests pass, but the native parser and ML paths still need verification outside the restricted sandbox.  
**Severity**: medium  
**Effort**: quick (< 5 min)  
**Fix**:

```bash
source .venv/bin/activate
python -m pytest
```

Record any failure before changing the lock; a native-library crash is an environment compatibility issue, while an assertion failure is a project regression.

### 3. Align the environment-template location

**Impact**: Agents and contributors may create configuration in the wrong directory because documentation and the existing template disagree.  
**Severity**: low  
**Effort**: quick (< 5 min)  
**Fix**:

Move or copy `src/.env.example` to `.env.example` at the repository root, or update all configuration loading and documentation to use `src/.env`.

### Addressed in upcoming lessons (Category B)

### CI/CD pipeline

**Lesson**: [Sprint Zero z Agentem: infrastruktura, walking skeleton i pierwszy deploy (M1L5)](https://platforma.przeprogramowani.pl/external/10xdevs-3/m1-l5)  
**What you'll do there**: Run the verified Ruff, mypy, pytest, and pip-audit commands automatically.

### Project-specific agent instructions

**Lesson**: [Agent Onboarding: Agents.md, AI Rules i feedback loops (M1L4)](https://platforma.przeprogramowani.pl/external/10xdevs-3/m1-l4)  
**What you'll do there**: Document Python typing, Pydantic boundaries, notebook-versus-production responsibilities, trusted model handling, and test expectations.

### Deployment configuration

**Lesson**: [Sprint Zero z Agentem: infrastruktura, walking skeleton i pierwszy deploy (M1L5)](https://platforma.przeprogramowani.pl/external/10xdevs-3/m1-l5)  
**What you'll do there**: Isolate the legacy ML runtime from the web-facing application and define its operational controls.

## Summary

Health status: needs-attention

The local development baseline is now reproducible and substantially healthier: the exact Intel environment is locked, dependency consistency passes, pytest collects four tests, Ruff passes, and mypy plus the Pydantic plugin checks 29 source files. Remaining attention is concentrated in the known legacy-dependency advisories and the unverified native test paths. Contain model-deserialization risk and run the full suite in a normal terminal before starting the production upload workflow; CI/CD, agent instructions, and deployment isolation follow in upcoming lessons.
