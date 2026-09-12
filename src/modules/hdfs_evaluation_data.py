"""Reproducible HDFS evaluation datasets from complete selected-block histories.

This module projects an approved source corpus onto an explicit ordered list of
block identifiers. Completeness means every first-match source line for a selected
block is retained; it does not prove that a real HDFS lifecycle ended.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.modules.artifacts import ArtifactStore
from src.modules.parser.drain_parser import DrainParser

SCHEMA_VERSION = 1
EVALUATION_STAGE = "evaluation-data"
MANIFEST_NAME = "manifest.json"
SELECTED_IDS_NAME = "selected-block-ids.txt"
DEFAULT_MAX_SOURCE_LINES = 100_000
DEFAULT_MAX_BLOCKS = 25_000
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_TIMESTAMP_FORMAT = "%d%m%y %H%M%S"


class EvaluationDataError(ValueError):
    """Raised when evaluation inputs are missing, malformed, or incomplete."""


class EvaluationModel(BaseModel):
    """Closed evaluation-schema base that rejects unspecified fields."""

    model_config = ConfigDict(extra="forbid")


class TimestampWarning(EvaluationModel):
    """A timestamp-quality issue that does not reorder retained source lines."""

    kind: Literal["unparseable_timestamp", "backward_timestamp"]
    line_number: int = Field(ge=1)
    block_id: str = Field(min_length=1)
    previous_line_number: int | None = Field(default=None, ge=1)
    detail: str = Field(min_length=1)


class BlockLineCount(EvaluationModel):
    """Retained first-match source-line count for one selected block."""

    block_id: str = Field(min_length=1)
    source_line_count: int = Field(gt=0)


class EvaluationShardRecord(EvaluationModel):
    """One bounded shard containing complete selected-block histories."""

    name: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    source_line_count: int = Field(gt=0)
    block_count: int = Field(gt=0)


class SelectedHistoryInspection(EvaluationModel):
    """Whole-corpus inspection of selected first-match source histories."""

    source_line_count: int = Field(ge=0)
    selected_line_counts: dict[str, int]
    timestamp_warnings: list[TimestampWarning]


class EvaluationDataManifest(EvaluationModel):
    """Provenance and validation evidence for one evaluation-data artifact."""

    schema_version: int = Field(ge=1)
    corpus_sha256: str = Field(pattern=_SHA256_PATTERN)
    labels_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_block_ids_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_block_ids_order_sha256: str = Field(pattern=_SHA256_PATTERN)
    selected_block_count: int = Field(gt=0)
    source_line_count: int = Field(ge=0)
    max_source_lines: int = Field(gt=0)
    max_blocks: int = Field(gt=0)
    selected_line_counts: list[BlockLineCount]
    shards: list[EvaluationShardRecord]
    timestamp_warnings: list[TimestampWarning]


class EvaluationPublishResult(EvaluationModel):
    """Atomically published evaluation-data artifact location and reuse flag."""

    artifact_dir: Path
    manifest_path: Path
    reused: bool
    manifest: EvaluationDataManifest


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a regular file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluation_stage_config(
    *,
    corpus: Path,
    labels: Path,
    selected_block_ids: Path,
    max_source_lines: int = DEFAULT_MAX_SOURCE_LINES,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> dict[str, Any]:
    """Return ArtifactStore stage configuration that includes input SHA-256 values."""

    if max_source_lines <= 0 or max_blocks <= 0:
        raise EvaluationDataError("Shard limits must be positive.")
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_sha256": sha256_file(corpus),
        "labels_sha256": sha256_file(labels),
        "selected_block_ids_sha256": sha256_file(selected_block_ids),
        "max_source_lines": max_source_lines,
        "max_blocks": max_blocks,
    }


def load_selected_block_ids(path: Path) -> list[str]:
    """Load an ordered selected-block ID list, rejecting duplicates and empty files."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvaluationDataError("Selected block-id file is missing or unreadable.") from error
    block_ids: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in seen:
            raise EvaluationDataError(f"Selected block-id list contains duplicate {stripped}.")
        seen.add(stripped)
        block_ids.append(stripped)
    if not block_ids:
        raise EvaluationDataError("Selected block-id file does not contain any identifiers.")
    return block_ids


def load_evaluation_labels(path: Path) -> dict[str, int]:
    """Load BlockId → {0,1} labels, rejecting duplicates and non-binary values."""

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise EvaluationDataError("Labels CSV must include a header row.")
            columns = {name.lower(): name for name in reader.fieldnames if name}
            id_column = next(
                (columns[name] for name in ("blockid", "block_id") if name in columns),
                None,
            )
            label_column = next(
                (columns[name] for name in ("label", "anomaly", "is_anomaly") if name in columns),
                None,
            )
            if id_column is None or label_column is None:
                raise EvaluationDataError("Labels CSV must include BlockId and Label columns.")
            mapping: dict[str, int] = {}
            for row_number, row in enumerate(reader, start=2):
                block_id = str(row.get(id_column) or "").strip()
                if not block_id:
                    raise EvaluationDataError(f"Labels CSV row {row_number} has an empty BlockId.")
                if block_id in mapping:
                    raise EvaluationDataError(f"Labels CSV contains duplicate BlockId {block_id}.")
                mapping[block_id] = _parse_strict_binary_label(row.get(label_column), row_number)
    except EvaluationDataError:
        raise
    except OSError as error:
        raise EvaluationDataError("Labels file is missing or unreadable.") from error
    if not mapping:
        raise EvaluationDataError("Labels CSV does not contain any block rows.")
    return mapping


def inspect_selected_histories(
    corpus: Path,
    selected_block_ids: Sequence[str],
) -> SelectedHistoryInspection:
    """Count selected first-match lines and collect timestamp warnings in source order."""

    selected = set(selected_block_ids)
    selected_line_counts = {block_id: 0 for block_id in selected_block_ids}
    last_timestamp: dict[str, datetime] = {}
    last_line_number: dict[str, int] = {}
    warnings: list[TimestampWarning] = []
    source_line_count = 0
    try:
        with corpus.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw in enumerate(handle, start=1):
                line = raw.rstrip("\n")
                if not line:
                    continue
                source_line_count += 1
                block_id = DrainParser.extract_hdfs_block_id(line)
                if block_id is None or block_id not in selected:
                    continue
                selected_line_counts[block_id] += 1
                parsed = _parse_hdfs_timestamp(line)
                if parsed is None:
                    warnings.append(
                        TimestampWarning(
                            kind="unparseable_timestamp",
                            line_number=line_number,
                            block_id=block_id,
                            detail="Selected source line has no parseable HDFS timestamp.",
                        )
                    )
                    continue
                previous = last_timestamp.get(block_id)
                if previous is not None and parsed < previous:
                    warnings.append(
                        TimestampWarning(
                            kind="backward_timestamp",
                            line_number=line_number,
                            block_id=block_id,
                            previous_line_number=last_line_number[block_id],
                            detail=(
                                "Selected source line timestamp precedes an earlier "
                                "source line for the same block."
                            ),
                        )
                    )
                last_timestamp[block_id] = parsed
                last_line_number[block_id] = line_number
    except OSError as error:
        raise EvaluationDataError("Corpus file is missing or unreadable.") from error
    return SelectedHistoryInspection(
        source_line_count=source_line_count,
        selected_line_counts=selected_line_counts,
        timestamp_warnings=warnings,
    )


def partition_selected_block_ids(
    *,
    selected_block_ids: Sequence[str],
    selected_line_counts: Mapping[str, int],
    max_source_lines: int = DEFAULT_MAX_SOURCE_LINES,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> list[list[str]]:
    """Partition complete selected blocks below both shard limits."""

    if max_source_lines <= 0 or max_blocks <= 0:
        raise EvaluationDataError("Shard limits must be positive.")
    partitions: list[list[str]] = []
    current_partition: list[str] = []
    current_line_count = 0
    for block_id in selected_block_ids:
        line_count = int(selected_line_counts.get(block_id, 0))
        if line_count <= 0:
            raise EvaluationDataError(f"Selected block {block_id} has no log lines in the corpus.")
        if line_count > max_source_lines:
            raise EvaluationDataError(
                f"Selected block {block_id} exceeds the evaluation source-line limit."
            )
        exceeds_block_limit = len(current_partition) >= max_blocks
        exceeds_source_limit = current_line_count + line_count > max_source_lines
        if current_partition and (exceeds_block_limit or exceeds_source_limit):
            partitions.append(current_partition)
            current_partition = []
            current_line_count = 0
        current_partition.append(block_id)
        current_line_count += line_count
    if current_partition:
        partitions.append(current_partition)
    return partitions


def write_evaluation_shards(
    *,
    corpus: Path,
    partitions: Sequence[Sequence[str]],
    destination: Path,
) -> list[Path]:
    """Write complete selected-block histories into bounded shard files in source order."""

    if not partitions:
        raise EvaluationDataError("Evaluation materialization requires at least one shard.")
    destination.mkdir(parents=True, exist_ok=True)
    block_to_shard = {
        block_id: shard_index
        for shard_index, partition in enumerate(partitions)
        for block_id in partition
    }
    paths = [destination / _shard_name(index) for index in range(len(partitions))]
    handles = [path.open("w", encoding="utf-8") for path in paths]
    try:
        with corpus.open("r", encoding="utf-8", errors="replace") as source:
            for raw in source:
                line = raw.rstrip("\n")
                if not line:
                    continue
                block_id = DrainParser.extract_hdfs_block_id(line)
                if block_id is None:
                    continue
                shard_index = block_to_shard.get(block_id)
                if shard_index is not None:
                    handles[shard_index].write(line + "\n")
    except OSError as error:
        raise EvaluationDataError("Unable to write evaluation shards from the corpus.") from error
    finally:
        for handle in handles:
            handle.close()
    return paths


def materialize_hdfs_evaluation_data(
    *,
    corpus: Path,
    labels: Path,
    selected_block_ids: Path,
    destination: Path,
    max_source_lines: int = DEFAULT_MAX_SOURCE_LINES,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> EvaluationDataManifest:
    """Validate inputs and write shards, a selected-ID copy, and a provenance manifest."""

    ordered_ids = load_selected_block_ids(selected_block_ids)
    label_map = load_evaluation_labels(labels)
    missing_labels = [block_id for block_id in ordered_ids if block_id not in label_map]
    if missing_labels:
        raise EvaluationDataError(
            f"Selected block {missing_labels[0]} has no binary label in the labels CSV."
        )
    inspection = inspect_selected_histories(corpus, ordered_ids)
    partitions = partition_selected_block_ids(
        selected_block_ids=ordered_ids,
        selected_line_counts=inspection.selected_line_counts,
        max_source_lines=max_source_lines,
        max_blocks=max_blocks,
    )
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(selected_block_ids, destination / SELECTED_IDS_NAME)
    shard_paths = write_evaluation_shards(
        corpus=corpus,
        partitions=partitions,
        destination=destination,
    )
    shard_records = [
        EvaluationShardRecord(
            name=path.name,
            sha256=sha256_file(path),
            source_line_count=_count_nonempty_lines(path),
            block_count=len(partition),
        )
        for path, partition in zip(shard_paths, partitions, strict=True)
    ]
    selected_line_counts = [
        BlockLineCount(
            block_id=block_id,
            source_line_count=inspection.selected_line_counts[block_id],
        )
        for block_id in ordered_ids
    ]
    _assert_written_histories_match(
        shard_paths=shard_paths,
        partitions=partitions,
        selected_line_counts=inspection.selected_line_counts,
    )
    manifest = EvaluationDataManifest(
        schema_version=SCHEMA_VERSION,
        corpus_sha256=sha256_file(corpus),
        labels_sha256=sha256_file(labels),
        selected_block_ids_sha256=sha256_file(selected_block_ids),
        selected_block_ids_order_sha256=_order_digest(ordered_ids),
        selected_block_count=len(ordered_ids),
        source_line_count=inspection.source_line_count,
        max_source_lines=max_source_lines,
        max_blocks=max_blocks,
        selected_line_counts=selected_line_counts,
        shards=shard_records,
        timestamp_warnings=inspection.timestamp_warnings,
    )
    (destination / MANIFEST_NAME).write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def publish_hdfs_evaluation_dataset(
    *,
    corpus: Path,
    labels: Path,
    selected_block_ids: Path,
    workspace_root: Path,
    code_root: Path,
    max_source_lines: int = DEFAULT_MAX_SOURCE_LINES,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> EvaluationPublishResult:
    """Atomically publish evaluation data through ArtifactStore using checksumed inputs."""

    stage_config = evaluation_stage_config(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected_block_ids,
        max_source_lines=max_source_lines,
        max_blocks=max_blocks,
    )
    store = ArtifactStore(workspace_root, "hdfs", code_root)

    def build(temp_dir: Path) -> dict[str, Path]:
        manifest = materialize_hdfs_evaluation_data(
            corpus=corpus,
            labels=labels,
            selected_block_ids=selected_block_ids,
            destination=temp_dir,
            max_source_lines=max_source_lines,
            max_blocks=max_blocks,
        )
        outputs = {
            "manifest": temp_dir / MANIFEST_NAME,
            "selected_block_ids": temp_dir / SELECTED_IDS_NAME,
        }
        for shard in manifest.shards:
            outputs[shard.name] = temp_dir / shard.name
        return outputs

    outputs, _success, reused = store.stage(
        stage=EVALUATION_STAGE,
        stage_config=stage_config,
        inputs=[corpus, labels, selected_block_ids],
        build=build,
    )
    manifest_path = outputs["manifest"]
    manifest = EvaluationDataManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    return EvaluationPublishResult(
        artifact_dir=manifest_path.parent,
        manifest_path=manifest_path,
        reused=reused,
        manifest=manifest,
    )


def _parse_strict_binary_label(value: object, row_number: int) -> int:
    if isinstance(value, bool) or value is None:
        raise EvaluationDataError(f"Labels CSV row {row_number} is not a binary 0 or 1 value.")
    stripped = str(value).strip().lower()
    if stripped in {"0", "normal"}:
        return 0
    if stripped in {"1", "anomaly", "anomalous"}:
        return 1
    raise EvaluationDataError(f"Labels CSV row {row_number} is not a binary 0 or 1 value.")


def _parse_hdfs_timestamp(line: str) -> datetime | None:
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(f"{parts[0]} {parts[1]}", _TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _order_digest(block_ids: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(block_ids).encode("utf-8")).hexdigest()


def _shard_name(index: int) -> str:
    return f"shard-{index:03d}.log"


def _count_nonempty_lines(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.rstrip("\n"):
                count += 1
    return count


def _assert_written_histories_match(
    *,
    shard_paths: Sequence[Path],
    partitions: Sequence[Sequence[str]],
    selected_line_counts: Mapping[str, int],
) -> None:
    written_counts = {block_id: 0 for block_id in selected_line_counts}
    expected_owners = {
        block_id: shard_index
        for shard_index, partition in enumerate(partitions)
        for block_id in partition
    }
    for shard_index, path in enumerate(shard_paths):
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.rstrip("\n")
                if not line:
                    continue
                block_id = DrainParser.extract_hdfs_block_id(line)
                if block_id is None or expected_owners.get(block_id) != shard_index:
                    raise EvaluationDataError(
                        f"Evaluation shard {path.name} contains an unexpected source line."
                    )
                written_counts[block_id] += 1
    for block_id, expected_count in selected_line_counts.items():
        if written_counts[block_id] != expected_count:
            raise EvaluationDataError(
                f"Selected block {block_id} did not retain a complete source history."
            )
