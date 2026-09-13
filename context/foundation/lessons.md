# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## A/B test a Cursor rule before adding it

- **Context**: When proposing or adding a new Cursor rule in .cursor/rules
- **Problem**: Rules accumulate untested; they add prompt noise and maintenance cost even when the agent already follows the convention without them
- **Rule**: Before adding a Cursor rule, run an A/B test; discard it when the agent already follows the convention without it.
- **Applies to**: implement

## Delete unused code after impl-review, with operator confirmation

- **Context**: applies after implementing last phase and after running 10x-impl-review
- **Problem**: codebase gets cluttered with unused/dead code
- **Rule**: Based on the 10x-impl-review perform a code check to delete unused/dead code paths. Verify with operator first
- **Applies to**: implement, impl-review

## Roll back object storage after every failed admission

- **Context**: Upload/admission paths that write object-store data and then create database records.
- **Problem**: Validation/duplicate cases were considered, but other database insert and partial cleanup failures could leave orphaned objects.
- **Rule**: Validate before storage writes; create the database record last; on any subsequent failure delete the written prefix and test that no objects remain.
- **Applies to**: plan, implement, impl-review

## Exercise real isolated subprocesses in ML integration tests

- **Context**: Model validators, inference workers, and other production subprocess boundaries that ordinary tests stub.
- **Problem**: Stubbed API fixtures can pass while the actual command/module wiring is broken.
- **Rule**: Add @pytest.mark.ml integration coverage that invokes the real subprocess command path; do not treat stubbed HTTP tests as proof of production wiring.
- **Applies to**: plan, implement, impl-review

## Keep generated runtime data out of Git, retain verifiable provenance

- **Context**: Colab outputs, release exports, model/evaluation binaries, and large datasets.
- **Problem**: Generated artifacts were committed despite the repository/workspace boundary; reproducibility still needs stable identity.
- **Rule**: Store generated runtime artifacts only in ignored workspace paths; record their paths and SHA-256 checksums in manifests, baselines, or documentation before committing related code.
- **Applies to**: plan, implement, impl-review
