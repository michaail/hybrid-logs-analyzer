"""Focused tests for complete HDFS block evaluation-data materialization."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.modules.artifacts import SUCCESS_FILE
from src.modules.hdfs_evaluation_data import (
    EvaluationDataError,
    EvaluationDataManifest,
    evaluation_stage_config,
    inspect_selected_histories,
    load_evaluation_labels,
    load_selected_block_ids,
    materialize_hdfs_evaluation_data,
    publish_hdfs_evaluation_dataset,
    sha256_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _hdfs_line(date: str, time: str, thread: str, message: str) -> str:
    return f"{date} {time} {thread} INFO dfs.DataNode$DataXceiver: {message}"


def _write_corpus(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_labels(path: Path, rows: list[tuple[str, str]]) -> Path:
    body = "BlockId,Label\n" + "".join(f"{block_id},{label}\n" for block_id, label in rows)
    path.write_text(body, encoding="utf-8")
    return path


def _write_ids(path: Path, block_ids: list[str]) -> Path:
    path.write_text("".join(f"{block_id}\n" for block_id in block_ids), encoding="utf-8")
    return path


def test_interleaved_selected_blocks_retain_complete_source_histories(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
            _hdfs_line("081109", "203616", "149", "Receiving block blk_2 src: /10.0.0.1"),
            _hdfs_line("081109", "203617", "150", "Receiving block blk_1 src: /10.0.0.2"),
            _hdfs_line("081109", "203618", "151", "Receiving block blk_3 src: /10.0.0.1"),
            _hdfs_line("081109", "203619", "152", "Receiving block blk_2 src: /10.0.0.2"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1"), ("blk_2", "0"), ("blk_3", "0")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1", "blk_2"])

    manifest = materialize_hdfs_evaluation_data(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        destination=tmp_path / "out",
    )
    shard = (tmp_path / "out" / manifest.shards[0].name).read_text(encoding="utf-8").splitlines()

    assert [record.block_id for record in manifest.selected_line_counts] == ["blk_1", "blk_2"]
    assert [record.source_line_count for record in manifest.selected_line_counts] == [2, 2]
    assert shard == [
        _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
        _hdfs_line("081109", "203616", "149", "Receiving block blk_2 src: /10.0.0.1"),
        _hdfs_line("081109", "203617", "150", "Receiving block blk_1 src: /10.0.0.2"),
        _hdfs_line("081109", "203619", "152", "Receiving block blk_2 src: /10.0.0.2"),
    ]
    assert all("blk_3" not in line for line in shard)


def test_selected_block_crossing_a_line_prefix_boundary_stays_complete(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
            _hdfs_line("081109", "203616", "149", "Receiving block blk_2 src: /10.0.0.1"),
            _hdfs_line("081109", "203617", "150", "Receiving block blk_1 src: /10.0.0.2"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1"), ("blk_2", "0")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1"])

    manifest = materialize_hdfs_evaluation_data(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        destination=tmp_path / "out",
    )
    shard = (tmp_path / "out" / manifest.shards[0].name).read_text(encoding="utf-8").splitlines()

    assert manifest.selected_line_counts[0].source_line_count == 2
    assert shard == [
        _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
        _hdfs_line("081109", "203617", "150", "Receiving block blk_1 src: /10.0.0.2"),
    ]


def test_partitioning_keeps_whole_blocks_under_shard_limits(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
            _hdfs_line("081109", "203616", "149", "Receiving block blk_1 src: /10.0.0.2"),
            _hdfs_line("081109", "203617", "150", "Receiving block blk_2 src: /10.0.0.1"),
            _hdfs_line("081109", "203618", "151", "Receiving block blk_2 src: /10.0.0.2"),
            _hdfs_line("081109", "203619", "152", "Receiving block blk_3 src: /10.0.0.1"),
            _hdfs_line("081109", "203620", "153", "Receiving block blk_3 src: /10.0.0.2"),
        ],
    )
    labels = _write_labels(
        tmp_path / "labels.csv",
        [("blk_1", "1"), ("blk_2", "0"), ("blk_3", "0")],
    )
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1", "blk_2", "blk_3"])

    manifest = materialize_hdfs_evaluation_data(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        destination=tmp_path / "out",
        max_source_lines=2,
        max_blocks=1,
    )
    shards = [
        (tmp_path / "out" / record.name).read_text(encoding="utf-8").splitlines()
        for record in manifest.shards
    ]

    assert [record.block_count for record in manifest.shards] == [1, 1, 1]
    assert [record.source_line_count for record in manifest.shards] == [2, 2, 2]
    assert all("blk_1" in line for line in shards[0])
    assert all("blk_2" in line for line in shards[1])
    assert all("blk_3" in line for line in shards[2])


def test_first_match_block_identity_does_not_duplicate_reference_lines(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "copy blk_2 linked to blk_1"),
            _hdfs_line("081109", "203616", "149", "Receiving block blk_1 src: /10.0.0.1"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1"), ("blk_2", "0")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1", "blk_2"])

    manifest = materialize_hdfs_evaluation_data(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        destination=tmp_path / "out",
    )
    counts = {record.block_id: record.source_line_count for record in manifest.selected_line_counts}
    shard = (tmp_path / "out" / manifest.shards[0].name).read_text(encoding="utf-8").splitlines()

    assert counts == {"blk_1": 1, "blk_2": 1}
    assert "copy blk_2 linked to blk_1" in shard[0]
    assert "Receiving block blk_1" in shard[1]


def test_source_order_is_preserved_when_timestamps_move_backward(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203620", "148", "Receiving block blk_1 src: /10.0.0.1"),
            _hdfs_line("081109", "203610", "149", "Receiving block blk_1 src: /10.0.0.2"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1"])

    manifest = materialize_hdfs_evaluation_data(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        destination=tmp_path / "out",
    )
    shard = (tmp_path / "out" / manifest.shards[0].name).read_text(encoding="utf-8").splitlines()

    assert shard[0].startswith("081109 203620")
    assert shard[1].startswith("081109 203610")
    assert [warning.kind for warning in manifest.timestamp_warnings] == ["backward_timestamp"]
    assert manifest.timestamp_warnings[0].line_number == 2
    assert manifest.timestamp_warnings[0].previous_line_number == 1


def test_unparseable_timestamp_is_a_warning_and_does_not_reorder(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            "not-a-date xx 148 INFO dfs.DataNode$DataXceiver: Receiving block blk_1 src: /10.0.0.1",
            _hdfs_line("081109", "203616", "149", "Receiving block blk_1 src: /10.0.0.2"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "0")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1"])

    manifest = materialize_hdfs_evaluation_data(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        destination=tmp_path / "out",
    )
    shard = (tmp_path / "out" / manifest.shards[0].name).read_text(encoding="utf-8").splitlines()

    assert shard[0].startswith("not-a-date")
    assert shard[1].startswith("081109 203616")
    assert [warning.kind for warning in manifest.timestamp_warnings] == ["unparseable_timestamp"]
    assert manifest.timestamp_warnings[0].line_number == 1


def test_duplicate_and_invalid_labels_are_rejected(tmp_path: Path) -> None:
    duplicate = _write_labels(tmp_path / "duplicate.csv", [("blk_1", "1"), ("blk_1", "0")])
    invalid = _write_labels(tmp_path / "invalid.csv", [("blk_1", "true")])

    with pytest.raises(EvaluationDataError, match="duplicate BlockId blk_1"):
        load_evaluation_labels(duplicate)
    with pytest.raises(EvaluationDataError, match="binary 0 or 1"):
        load_evaluation_labels(invalid)


def test_loghub_normal_anomaly_labels_are_accepted(tmp_path: Path) -> None:
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "Anomaly"), ("blk_2", "Normal")])
    mapping = load_evaluation_labels(labels)
    assert mapping == {"blk_1": 1, "blk_2": 0}


def test_missing_label_and_duplicate_or_absent_selected_ids_are_rejected(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [_hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1")],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1")])
    missing_label = _write_ids(tmp_path / "missing-label.txt", ["blk_1", "blk_2"])
    duplicate_ids = _write_ids(tmp_path / "duplicate-ids.txt", ["blk_1", "blk_1"])
    absent_history = _write_ids(tmp_path / "absent.txt", ["blk_9"])
    empty_ids = tmp_path / "empty.txt"
    empty_ids.write_text("# only a comment\n", encoding="utf-8")

    with pytest.raises(EvaluationDataError, match="duplicate blk_1"):
        load_selected_block_ids(duplicate_ids)
    with pytest.raises(EvaluationDataError, match="does not contain any identifiers"):
        load_selected_block_ids(empty_ids)
    with pytest.raises(EvaluationDataError, match="blk_2 has no binary label"):
        materialize_hdfs_evaluation_data(
            corpus=corpus,
            labels=labels,
            selected_block_ids=missing_label,
            destination=tmp_path / "out-missing",
        )
    with pytest.raises(EvaluationDataError, match="blk_9 has no binary label"):
        materialize_hdfs_evaluation_data(
            corpus=corpus,
            labels=labels,
            selected_block_ids=absent_history,
            destination=tmp_path / "out-absent-label",
        )

    labelled_absent = _write_labels(tmp_path / "absent-labels.csv", [("blk_9", "0")])
    with pytest.raises(EvaluationDataError, match="blk_9 has no log lines"):
        materialize_hdfs_evaluation_data(
            corpus=corpus,
            labels=labelled_absent,
            selected_block_ids=absent_history,
            destination=tmp_path / "out-absent-lines",
        )


def test_stage_config_includes_input_digests_and_changes_with_content(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [_hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1")],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1"])
    first = evaluation_stage_config(corpus=corpus, labels=labels, selected_block_ids=selected)
    assert first["corpus_sha256"] == sha256_file(corpus)
    corpus.write_text(corpus.read_text(encoding="utf-8").replace("blk_1", "blk_9"), encoding="utf-8")
    second = evaluation_stage_config(corpus=corpus, labels=labels, selected_block_ids=selected)

    assert first["corpus_sha256"] != second["corpus_sha256"]
    assert first["labels_sha256"] == sha256_file(labels)
    assert first["selected_block_ids_sha256"] == sha256_file(selected)
    assert first["schema_version"] == 1


def test_publish_reuses_checksumed_cache_and_rebuilds_when_digest_changes(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
            _hdfs_line("081109", "203616", "149", "Receiving block blk_1 src: /10.0.0.2"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1"])
    workspace = tmp_path / "workspace"

    first = publish_hdfs_evaluation_dataset(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        workspace_root=workspace,
        code_root=REPO_ROOT,
        max_source_lines=10,
        max_blocks=5,
    )
    second = publish_hdfs_evaluation_dataset(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        workspace_root=workspace,
        code_root=REPO_ROOT,
        max_source_lines=10,
        max_blocks=5,
    )
    corpus.write_text(
        "\n".join(
            [
                _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
                _hdfs_line("081109", "203616", "149", "Receiving block blk_1 src: /10.0.0.9"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    third = publish_hdfs_evaluation_dataset(
        corpus=corpus,
        labels=labels,
        selected_block_ids=selected,
        workspace_root=workspace,
        code_root=REPO_ROOT,
        max_source_lines=10,
        max_blocks=5,
    )

    assert first.reused is False
    assert second.reused is True
    assert second.artifact_dir == first.artifact_dir
    assert (first.artifact_dir / SUCCESS_FILE).is_file()
    assert third.reused is False
    assert third.artifact_dir != first.artifact_dir
    assert third.manifest.corpus_sha256 != first.manifest.corpus_sha256
    EvaluationDataManifest.model_validate_json(first.manifest_path.read_text(encoding="utf-8"))


def test_inspect_counts_nonempty_corpus_lines_including_unselected_blocks(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
            "",
            _hdfs_line("081109", "203616", "149", "Receiving block blk_2 src: /10.0.0.1"),
        ],
    )
    inspection = inspect_selected_histories(corpus, ["blk_1"])
    assert inspection.source_line_count == 2
    assert inspection.selected_line_counts == {"blk_1": 1}


def _load_build_script():
    spec = importlib.util.spec_from_file_location(
        "build_hdfs_evaluation_dataset",
        REPO_ROOT / "scripts" / "build_hdfs_evaluation_dataset.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_script_rejects_missing_and_invalid_inputs_before_publish(tmp_path: Path) -> None:
    module = _load_build_script()
    workspace = tmp_path / "workspace"
    missing = module.main(
        [
            "--corpus",
            str(tmp_path / "missing.log"),
            "--labels",
            str(tmp_path / "missing.csv"),
            "--selected-block-ids",
            str(tmp_path / "missing.txt"),
            "--workspace-root",
            str(workspace),
            "--code-root",
            str(REPO_ROOT),
        ]
    )
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [_hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1")],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "true")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1"])
    invalid = module.main(
        [
            "--corpus",
            str(corpus),
            "--labels",
            str(labels),
            "--selected-block-ids",
            str(selected),
            "--workspace-root",
            str(workspace),
            "--code-root",
            str(REPO_ROOT),
        ]
    )

    assert missing == 1
    assert invalid == 1
    assert not list(workspace.rglob(SUCCESS_FILE))


def test_build_script_publishes_atomic_artifact_and_reuses_unchanged_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_build_script()
    corpus = _write_corpus(
        tmp_path / "corpus.log",
        [
            _hdfs_line("081109", "203615", "148", "Receiving block blk_1 src: /10.0.0.1"),
            _hdfs_line("081109", "203616", "149", "Receiving block blk_2 src: /10.0.0.1"),
        ],
    )
    labels = _write_labels(tmp_path / "labels.csv", [("blk_1", "1"), ("blk_2", "0")])
    selected = _write_ids(tmp_path / "ids.txt", ["blk_1", "blk_2"])
    workspace = tmp_path / "workspace"
    argv = [
        "--corpus",
        str(corpus),
        "--labels",
        str(labels),
        "--selected-block-ids",
        str(selected),
        "--workspace-root",
        str(workspace),
        "--code-root",
        str(REPO_ROOT),
        "--max-source-lines",
        "10",
        "--max-blocks",
        "5",
    ]

    assert module.main(argv) == 0
    first = capsys.readouterr().out
    assert module.main(argv) == 0
    second = capsys.readouterr().out
    manifests = list(workspace.rglob("manifest.json"))
    success = list(workspace.rglob(SUCCESS_FILE))

    assert "published" in first
    assert "reused" in second
    assert len(manifests) == 1
    assert len(success) == 1
    manifest = EvaluationDataManifest.model_validate_json(manifests[0].read_text(encoding="utf-8"))
    assert (manifests[0].parent / "selected-block-ids.txt").is_file()
    assert [record.name for record in manifest.shards]
    for shard in manifest.shards:
        assert (manifests[0].parent / shard.name).is_file()


def test_parity_module_delegates_shard_writing_to_evaluation_data() -> None:
    from src.modules import hdfs_evaluation_data, hdfs_parity

    assert not hasattr(hdfs_parity, "_write_test_shards")
    assert hdfs_parity.write_evaluation_shards is hdfs_evaluation_data.write_evaluation_shards
    assert hdfs_parity.partition_selected_block_ids is hdfs_evaluation_data.partition_selected_block_ids
