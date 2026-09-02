# Repository Guidelines

Hybrid Logs Analyzer is a Python research pipeline for HDFS/BGL anomaly detection. Notebooks support research and comparison; `src/modules/` and `run_ablation.py` contain reusable, reproducible pipeline behavior.

## Critical Boundaries

- Keep shared parsing, enrichment, sequencing, graph, and artifact behavior in `src/modules/`; notebooks in `src/notebooks/` may explore or invoke it but must not become the only implementation of production-facing behavior.
- Preserve the agreed notebook baseline: for identical dataset, model, and configuration, every reported evaluation metric must remain within one percentage point. Make inputs, outputs, configuration, and terminal failure states explicit rather than selecting the newest artifact or relying on notebook state.
- Keep repository code/configuration separate from the ignored workspace data, caches, models, outputs, and run records. Use `--workspace-root` for artifacts and `--code-root` for the checked-out revision; retain `_SUCCESS.json` atomic-cache semantics in @src/modules/artifacts.py.
- Do not pass uploaded or otherwise untrusted model files to the current PyTorch deserializers. Before the planned model-upload flow, require trusted Publisher authorization, a non-executable artifact contract, isolated legacy inference, and no access to application secrets.
- Treat @context/foundation/prd.md as binding for planned web work: scope every model, log, run, result, and audit query by authorized project; never publish, select, or expose an artifact across projects.

## Layout and Configuration

Place reusable code in `src/modules/`, tests in `tests/`, experiment settings in `configs/`. Keep research notebooks usable as a separate R&D path. Put local secrets in the root `.env` copied from @.env.example; never commit it. Consult @README.md for the pipeline stages and Colab workspace layout.

## Environment and Verification

The locked Intel macOS runtime is intentional. Create `.venv` and install @requirements-macos-intel.lock.txt; change this lock only in an explicit compatibility task that checks Intel wheels and notebook parity. Run `python -m pytest`, `ruff check src tests scripts run_ablation.py`, and `mypy` before completing pipeline changes. Native NumPy/Torch paths can fail under Cursor's restricted sandbox because of shared-memory limits; verify those tests in a normal local terminal and distinguish environment crashes from assertion regressions. Use `python -m pip_audit -r requirements-macos-intel.lock.txt` to review the accepted legacy advisory set.

## Code and Test Conventions

Target Python 3.10, four-space indentation, and 100-character lines as configured in @pyproject.toml and @.editorconfig. Type public module boundaries and use Pydantic models for validated enrichment/configuration records. Add focused pytest coverage for changed reusable behavior; mark tests requiring the Intel ML stack with `@pytest.mark.ml`. Keep commits concise and imperative, following the descriptive checkpoint style in recent history.