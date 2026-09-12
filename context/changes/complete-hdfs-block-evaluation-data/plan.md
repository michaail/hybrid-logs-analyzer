# Complete HDFS block evaluation data Implementation Plan

## Overview

Create reproducible HDFS evaluation inputs by projecting an immutable approved source
corpus onto an explicit ordered list of block identifiers. Each selected block will
retain every source line assigned to it by the established first-match block-ID rule;
the builder will publish bounded shard files plus a manifest carrying provenance and
validation evidence.

This implements FR-013. It deliberately does not decide whether a block in an
arbitrary Operator upload is lifecycle-complete or change anomaly/normal result
classification; that work remains S-06 / FR-012.

## Current State Analysis

The controlled parity gate already counts selected block lines across the full corpus,
partitions blocks under frozen inference limits, and writes temporary complete-history
shards. That behavior is private to `src/modules/hdfs_parity.py` and disappears after
the parity command exits, so it cannot serve as a reusable, inspectable evaluation
dataset artifact.

The pipeline identifies a line's sequence owner as the first `blk_*` identifier found
in it (`src/modules/parser/drain_parser.py:53-57`). HDFS sequencing later groups those
lines by block ID (`src/modules/sequencer.py:114-128`). The existing label loader
overwrites duplicate IDs and treats arbitrary values as normal
(`src/modules/hdfs_parity.py:80-109`, `604-607`), which is unsuitable for
quality-evaluation input. The full parity release already establishes the immutable
corpus, labels, and ordered held-out IDs that the new artifact must preserve
(`context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md:62-139`).

## Desired End State

Given explicit paths to the approved HDFS corpus, labels, and ordered selected IDs, a
maintainer can run one documented command and obtain an atomically published
workspace artifact containing:

- the original selected-ID file;
- deterministic bounded `.log` shards, with every selected block entirely in one
  shard and its retained lines in original source-file order;
- a machine-readable manifest with source, label, selection, and shard SHA-256
  evidence; per-block line counts; and timestamp-quality warnings.

The artifact is complete *within the approved corpus*: every line whose first HDFS
block-ID match is selected appears exactly once in its assigned shard. This is
reproducible evaluation evidence, not proof that a real HDFS block lifecycle ended.
The parity gate reuses this materialization path while retaining its frozen-parser
coverage validation and existing metric checks.

### Key Discoveries:

- Temporary complete-block extraction already exists in
  `src/modules/hdfs_parity.py:270-430`, including failure when a selected ID has no
  source lines and partitioning below source-line/block limits.
- Raw-line truncation can split a block because parser methods accept `max_lines`
  (`src/modules/parser/drain_parser.py:80-106`, `161-209`); the new builder must
  always scan the entire approved corpus instead.
- The frozen inference path rejects a source shard above 100,000 non-empty lines or
  25,000 blocks (`src/modules/hdfs_inference.py:28-31`, `113-145`), so materialized
  shards must respect those limits.
- `ArtifactStore` publishes outputs atomically only after `_SUCCESS.json` is written
  (`src/modules/artifacts.py:66-170`). Its normal input metadata is mtime/size-based,
  so evaluation-data stage configuration must also include full input SHA-256 values.
- The held-out split is ordered and immutable: 86,260 IDs with a recorded SHA-256
  (`context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md:106-139`).

## What We're NOT Doing

- Classifying uploaded blocks as finalized or provisional, changing result counts, or
  adding a results UI/API; S-06 owns those FR-012 / US-03 behaviors.
- Proving HDFS lifecycle termination, applying inactivity watermarks, or introducing
  terminal-event heuristics.
- Regenerating the approved held-out split, changing model scoring, or changing the
  first-match block-identity rule.
- Accepting line-prefix samples as anomaly-quality data, importing another log source,
  or making full-corpus data available through the browser upload path.
- Regenerating `requirements-macos-intel.lock.txt`.

## Implementation Approach

Extract the generic data-building responsibilities from the parity module into a
typed `src/modules/` boundary. It will validate selected IDs and labels strictly,
make a counting pass over the whole corpus, partition by complete blocks, and make a
second streaming pass to write source-order shard records. A dedicated CLI wraps this
builder in an `ArtifactStore` stage rooted at the supplied workspace; its
checksum-inclusive stage configuration keeps cache reuse safe and preserves
`_SUCCESS.json` publication semantics.

`hdfs_parity` will keep release-specific responsibilities—unpacking the trusted
bundles, frozen-parser coverage checks, score calculation, and metric comparison—but
delegate selection, strict labels, partitioning, and shard writing to the shared
builder. This retains the current release gate without a second implementation of
complete-history extraction.

## Critical Implementation Details

Source-file order is the canonical event order for an artifact. The builder must not
sort selected records by timestamp; it records unparseable timestamps and backward
timestamp transitions as manifest warnings, allowing source evidence to remain
available without falsely claiming timestamp validation succeeded.

Every cache-stage configuration must contain SHA-256 values of corpus, labels, and
the raw selected-ID file before `ArtifactStore.stage()` is called. The store's default
size/mtime metadata alone is insufficient for a release-quality corpus contract.

## Phase 1: Define and materialize the evaluation-data contract

### Overview

Create the reusable typed module that validates the immutable inputs and produces
complete, bounded, source-order evaluation artifacts without loading ML dependencies.

### Changes Required:

#### 1. Evaluation-data module

**File**: `src/modules/hdfs_evaluation_data.py`

**Intent**: Add the sole reusable implementation for turning an approved HDFS corpus
and explicit selected block IDs into complete-history shard files and provenance
records. It replaces the parity module's data-specific private helpers while keeping
model/parity behavior out of the new module.

**Contract**: Provide typed Pydantic manifest/validation records and public operations
to load an ordered ID file, strictly load labels, inspect selected source histories,
partition complete blocks, and materialize shard files. A selected ID is valid only
when unique, represented by one or more first-match corpus lines, and backed by
exactly one `0` or `1` label. The manifest records schema version; corpus, label, and
selected-ID SHA-256 values; non-empty corpus-line count; selected-ID count/order
digest; per-block retained-line counts; per-shard file digest/counts; configured
limits; and timestamp warnings.

#### 2. Atomic workspace artifact publication

**File**: `src/modules/artifacts.py`

**Intent**: Reuse the established atomic cache publication behavior for evaluation
artifacts without weakening source provenance.

**Contract**: Keep the existing `_SUCCESS.json` behavior unchanged. The evaluation
builder supplies a stage configuration whose full input SHA-256 values and shard
limits participate in the existing fingerprint, so changes to input contents create
a distinct artifact even if a path, size, or mtime is reused.

#### 3. Focused materialization tests

**File**: `tests/test_hdfs_evaluation_data.py`

**Intent**: Define executable behavior for the new data contract before consumers
depend on it.

**Contract**: Cover interleaved selected blocks, blocks crossing a hypothetical
line-prefix boundary, shard-boundary partitioning, source-order preservation,
first-match-only identity, strict duplicate/missing/invalid labels, duplicate or
absent selected IDs, input-digest changes, and timestamp warning—not reorder—paths.
Use small text fixtures and avoid ML imports.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_hdfs_evaluation_data.py` passes.
- `ruff check src/modules/hdfs_evaluation_data.py src/modules/artifacts.py tests/test_hdfs_evaluation_data.py` passes.
- `mypy src/modules/hdfs_evaluation_data.py src/modules/artifacts.py tests/test_hdfs_evaluation_data.py` passes.

#### Manual Verification:

- Build a tiny interleaved fixture and inspect its manifest to confirm every selected
  block's source lines are complete and retain input-file order.
- Confirm a timestamp anomaly appears as a manifest warning while the generated shard
  remains in original source order.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual checks succeeded before
proceeding.

---

## Phase 2: Expose and consolidate the controlled workflow

### Overview

Provide an explicit, reproducible command for creating durable evaluation data and
move the parity release gate onto the same materialization path.

### Changes Required:

#### 1. Evaluation-data build command

**File**: `scripts/build_hdfs_evaluation_dataset.py`

**Intent**: Add a maintainable, non-notebook entry point for creating the FR-013
artifact from explicit inputs under the configured workspace root.

**Contract**: Require corpus, labels, and ordered selected-ID paths; accept
`--workspace-root` and `--code-root`; reject ambiguous or invalid inputs before
publication; invoke the shared builder through `ArtifactStore`; and print the
published artifact/manifest path. Output stays under ignored workspace artifacts and
never infers a “newest” corpus, release, or ID list.

#### 2. Shared parity materialization

**File**: `src/modules/hdfs_parity.py`

**Intent**: Remove duplicated selected-block validation, partitioning, and shard
writing from the parity module while preserving its checksum, frozen-parser, scoring,
and metric-gate behavior.

**Contract**: Delegate strict selected-ID/label loading and bounded complete-history
shard construction to `hdfs_evaluation_data`. Keep `verify_hdfs_release()`'s
explicit-path API, temporary release unpacking, all-source frozen-parser validation,
immutable expected-record protection, and report format compatible with existing
callers. Parity may materialize temporary shards through the shared builder; it does
not publish or replace a release artifact.

#### 3. Command and parity integration tests

**Files**: `tests/test_hdfs_evaluation_data.py`,
`tests/test_hdfs_inference_parity.py`

**Intent**: Protect both public creation and existing controlled verification against
future divergence.

**Contract**: Test CLI argument handling and atomically published output using a
temporary workspace. Retain the release-gate fixture assertion that reduced source
and block limits create multiple shards yet score every selected line exactly once;
assert it runs through the shared materialization contract rather than the retired
private implementation.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_hdfs_evaluation_data.py tests/test_hdfs_inference_parity.py` passes.
- `ruff check src/modules/hdfs_evaluation_data.py src/modules/hdfs_parity.py scripts/build_hdfs_evaluation_dataset.py tests/test_hdfs_evaluation_data.py tests/test_hdfs_inference_parity.py` passes.
- `mypy src/modules/hdfs_evaluation_data.py src/modules/hdfs_parity.py scripts/build_hdfs_evaluation_dataset.py tests/test_hdfs_evaluation_data.py tests/test_hdfs_inference_parity.py` passes.

#### Manual Verification:

- Run the new CLI against an approved fixture with an explicit workspace root and
  verify that rerunning unchanged inputs returns the same successful cache artifact.
- Run the existing parity command against the golden release and confirm its report
  format and pass/fail exit behavior remain unchanged.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual checks succeeded before
proceeding.

---

## Phase 3: Record reproducibility evidence and operating guidance

### Overview

Document how to create and validate the data artifact and establish the controlled
full-corpus evidence needed before this foundation is considered complete.

### Changes Required:

#### 1. Evaluation-data operating documentation

**File**: `README.md`

**Intent**: Document the dedicated build command, artifact contents, required
explicit inputs, and distinction between complete-within-approved-corpus evaluation
data and S-06 runtime lifecycle classification.

**Contract**: Place the workflow beside the existing HDFS inference/parity guidance.
State that line-prefix samples are smoke-test-only, production limits drive sharding,
source order is retained, timestamp-quality problems are manifest warnings, and the
builder never chooses a source corpus or split implicitly.

#### 2. Approved baseline provenance

**File**: `context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md`

**Intent**: Record immutable provenance for the selected baseline's generated
evaluation-data artifact after it has been built and independently verified.

**Contract**: Append the generated workspace-relative artifact location, manifest
SHA-256, source/label/selected-ID digest matches, selected-block and shard counts,
and the controlled command used. Do not alter approved model metrics, historical
checksums, or the held-out ID list.

#### 3. Final verification coverage

**Files**: `tests/test_hdfs_evaluation_data.py`,
`tests/test_hdfs_inference_parity.py`

**Intent**: Make the artifact's documented failure conditions and parity
compatibility durable.

**Contract**: Ensure focused tests cover rejected malformed evaluation inputs and
the `release_gate` test remains opt-in. The actual 11-million-line corpus build and
parity command are documented manual release checks because the source data is
workspace-local and ML/native execution is not a default test dependency.

### Success Criteria:

#### Automated Verification:

- `python -m pytest tests/test_hdfs_evaluation_data.py tests/test_hdfs_inference_parity.py` passes.
- `ruff check src/modules/hdfs_evaluation_data.py src/modules/hdfs_parity.py scripts/build_hdfs_evaluation_dataset.py tests/test_hdfs_evaluation_data.py tests/test_hdfs_inference_parity.py` passes.
- `mypy` passes for the project configuration.

#### Manual Verification:

- Build the approved corpus from the immutable labels and held-out ID file in a normal
  local terminal; verify the manifest records the baseline SHA-256 values, 86,260
  selected IDs, and no missing selected source history.
- Run the controlled full-corpus parity command against the same release and archive
  its comparison report only if checksum, exact-threshold, and metric-tolerance gates
  pass.
- Review the README and baseline record to confirm they make no claim that arbitrary
  Operator uploads are lifecycle-complete.

**Implementation Note**: After completing this phase and all automated verification
passes, pause for human confirmation that the manual checks succeeded before marking
the change complete.

## Testing Strategy

### Unit Tests:

- Build complete histories for selected IDs whose source lines are interleaved with
  unselected IDs; verify all and only first-match selected lines are emitted once.
- Reject duplicate selected IDs, missing source histories, missing/duplicate labels,
  and non-binary label values.
- Verify deterministic partitioning respects both block and non-empty-line limits,
  never splits a block, and creates deterministic manifest/shard hashes.
- Preserve raw source order; record, rather than reorder or discard, malformed and
  backward timestamps.

### Integration Tests:

- Invoke the dedicated CLI against a temporary workspace and verify `_SUCCESS.json`,
  manifest, selected-ID copy, and declared shard outputs are atomically published.
- Exercise `verify_hdfs_release()` with the golden release under reduced frozen
  limits, preserving existing report/checksum/metric behavior while using shared
  materialization.

### Manual Testing Steps:

1. In a normal local terminal, run the builder against the approved `HDFS_full.log`,
   `anomaly_label.csv`, and immutable `test_block_ids.txt`.
2. Inspect its manifest and confirm its recorded input digests match
   `baseline.md`, every selected ID has a positive line count, and any timestamp
   warnings are explicitly visible.
3. Run `scripts/verify_hdfs_parity.py` with the generated data inputs and confirm the
   approved release still meets its unchanged parity gate.

## Performance Considerations

The builder must stream rather than load the full corpus: one whole-corpus inspection
pass obtains selected-block counts and timestamp warnings, then a second pass writes
bounded shards. It may hold selected IDs, counts, and shard assignments in memory but
not all source rows. The normal production caps remain 100,000 non-empty source lines
and 25,000 blocks per shard; no web upload or live-path latency target applies.

## Migration Notes

No database or existing data migration is required. Historical source files and
releases remain untouched. Each input-digest combination creates a separate
workspace-local artifact; prior cache entries may be retained as provenance.

## References

- Product requirement: `context/foundation/prd.md:131-145`
- Roadmap foundation and scope boundary: `context/foundation/roadmap.md:132-146`,
  `218-230`
- Approved release inputs and held-out split: `context/archive/2026-09-11-run-parity-hdfs-analysis/baseline.md:62-139`
- Existing complete-history extraction: `src/modules/hdfs_parity.py:270-430`
- HDFS identity and sequencing: `src/modules/parser/drain_parser.py:53-57`,
  `src/modules/sequencer.py:114-128`
- Atomic artifact publication: `src/modules/artifacts.py:66-170`
- Existing parity coverage: `tests/test_hdfs_inference_parity.py:426-489`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step
> lands. Do not rename step titles.

### Phase 1: Define and materialize the evaluation-data contract

#### Automated

- [x] 1.1 Focused evaluation-data tests pass
- [x] 1.2 Evaluation-data lint passes
- [x] 1.3 Evaluation-data type checking passes

#### Manual

- [x] 1.4 Inspect a tiny complete-history manifest and shards
- [x] 1.5 Verify timestamp warnings retain source order

### Phase 2: Expose and consolidate the controlled workflow

#### Automated

- [ ] 2.1 Evaluation-data and parity integration tests pass
- [ ] 2.2 Consolidated lint passes
- [ ] 2.3 Consolidated type checking passes

#### Manual

- [ ] 2.4 Verify the explicit CLI artifact cache behavior
- [ ] 2.5 Verify unchanged golden parity-command behavior

### Phase 3: Record reproducibility evidence and operating guidance

#### Automated

- [ ] 3.1 Final focused tests pass
- [ ] 3.2 Final lint passes
- [ ] 3.3 Project type checking passes

#### Manual

- [ ] 3.4 Build and inspect the approved full-corpus artifact
- [ ] 3.5 Run and retain successful controlled full-corpus parity evidence
- [ ] 3.6 Review documented boundary from runtime lifecycle completeness
