"""Frozen HDFS inference composition shared by the private service and parity tools.

This module is the production scoring path. It never fits Drain, never enriches
templates, and never zero-fills missing embeddings. Torch is imported only inside
the scoring function so API processes can import sibling modules safely.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.modules.inference_bundle import (
    DRAIN_CONFIG_NAME,
    DRAIN_PARSER_NAME,
    EMBEDDINGS_NAME,
    NODE_FEATURE_EXTRA_DIM,
)
from src.modules.model_package import ModelPackageManifest

FEATURE_ATOL = 1.0e-5
FEATURE_RTOL = 1.0e-5
SCORE_ATOL = 1.0e-5
SCORE_RTOL = 1.0e-5
MAX_CONTEXT_LINES = 20
MAX_RAW_CHARS = 500
MAX_SOURCE_LINES = 100_000
MAX_BLOCKS = 25_000


class HdfsInferenceError(RuntimeError):
    """Typed frozen-inference failure before the service maps it to a public code."""

    def __init__(self, code: str, *, cause: str | None = None) -> None:
        self.code = code
        self.cause = cause
        super().__init__(cause or code)


@dataclass(frozen=True)
class SourceLine:
    """One capped raw log line retained as block evidence."""

    line_number: int | None
    raw: str


@dataclass(frozen=True)
class BlockInferenceSnapshot:
    """Per-block graph, score, decision, and source references after frozen inference."""

    block_id: str
    score: float
    decision: bool
    num_nodes: int
    num_edges: int
    edge_index: tuple[tuple[int, ...], tuple[int, ...]]
    node_features: tuple[tuple[float, ...], ...]
    edge_features: tuple[tuple[float, ...], ...]
    matched_line_count: int
    source_lines: tuple[SourceLine, ...]


@dataclass(frozen=True)
class FrozenHdfsInferenceResult:
    """Complete processing trace for a raw HDFS log and a trusted v2 release."""

    threshold: float
    parser_checksum: str
    drain_config_checksum: str
    embeddings_checksum: str
    artifact_checksum: str
    source_line_count: int
    annotated_line_count: int
    blocks: tuple[BlockInferenceSnapshot, ...]

    def as_snapshot(self) -> dict[str, Any]:
        """JSON-serialisable processing oracle used by the golden fixture."""

        return {
            "tolerances": {
                "feature_atol": FEATURE_ATOL,
                "feature_rtol": FEATURE_RTOL,
                "score_atol": SCORE_ATOL,
                "score_rtol": SCORE_RTOL,
            },
            "threshold": self.threshold,
            "checksums": {
                "drain_parser.bin": self.parser_checksum,
                "drain.ini": self.drain_config_checksum,
                "embeddings.npz": self.embeddings_checksum,
                "model.pt": self.artifact_checksum,
            },
            "source_line_count": self.source_line_count,
            "annotated_line_count": self.annotated_line_count,
            "ordered_block_ids": [block.block_id for block in self.blocks],
            "blocks": [_block_snapshot(block) for block in self.blocks],
        }


def score_frozen_hdfs_log(
    *,
    manifest: ModelPackageManifest,
    bundle_dir: Path,
    log_path: Path,
    artifact_path: Path,
    batch_size: int = 1,
) -> FrozenHdfsInferenceResult:
    """Annotate, graph, and score a raw HDFS log from materialized v2 artefacts."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")
    source_line_count = _count_nonempty_lines(log_path)
    if source_line_count > MAX_SOURCE_LINES:
        raise HdfsInferenceError("INFERENCE_FAILED", cause="source line limit exceeded")

    from src.modules.dataset import MissingClusterEmbedding, build_pyg_dataset
    from src.modules.models.gae import AttributeAwareGAE, compute_anomaly_scores
    from src.modules.parser.drain_parser import DrainParser, UnmatchedLogLine
    from src.modules.sequencer import build_sequences
    from torch_geometric.loader import DataLoader

    import numpy as np
    import torch

    parser_path = bundle_dir / DRAIN_PARSER_NAME
    config_path = bundle_dir / DRAIN_CONFIG_NAME
    embeddings_path = bundle_dir / EMBEDDINGS_NAME
    try:
        parser = DrainParser.load(str(parser_path), config_path=str(config_path))
        annotated = parser.annotate_file(str(log_path), unmatched="fail")
    except UnmatchedLogLine:
        raise
    except Exception as error:
        raise HdfsInferenceError("PARSER_FAILED", cause=type(error).__name__) from error

    annotated_line_count = 0 if annotated.empty else int(len(annotated))
    sequences = build_sequences(annotated, "hdfs") if not annotated.empty else {}
    if len(sequences) > MAX_BLOCKS:
        raise HdfsInferenceError("INFERENCE_FAILED", cause="block limit exceeded")
    embeddings = load_frozen_embeddings(embeddings_path)
    embed_width = next(iter(embeddings.values())).shape[0] if embeddings else 0
    expected_node_dim = embed_width + NODE_FEATURE_EXTRA_DIM
    if embeddings and expected_node_dim != manifest.architecture.node_dim:
        raise HdfsInferenceError(
            "PREPROCESSING_BUNDLE_UNAVAILABLE",
            cause="embedding width does not match architecture.node_dim",
        )
    use_edge_features = manifest.architecture.edge_dim > 1
    if sequences:
        try:
            graphs = build_pyg_dataset(
                sequences,
                {block_id: 0 for block_id in sequences},
                embeddings,
                use_edge_features=use_edge_features,
                dataset="hdfs",
                missing_embedding="fail",
                on_graph_error="fail",
                hdfs_feature_contract=manifest.architecture.feature_contract,
            )
        except MissingClusterEmbedding:
            raise
        except HdfsInferenceError:
            raise
        except Exception as error:
            raise HdfsInferenceError("INFERENCE_FAILED", cause=type(error).__name__) from error
    else:
        graphs = []

    normalise_edge_attributes(
        graphs, manifest.architecture.edge_mean, manifest.architecture.edge_std
    )
    try:
        model = AttributeAwareGAE(
            node_dim=manifest.architecture.node_dim,
            edge_dim=manifest.architecture.edge_dim,
            hidden_dim=manifest.architecture.hidden_dim,
            latent_dim=manifest.architecture.latent_dim,
            gine_aggregation=manifest.architecture.gine_aggregation,
            node_transformation=manifest.architecture.node_transformation,
        )
        payload = torch.load(artifact_path, map_location="cpu", weights_only=True)
        if not isinstance(payload, dict):
            raise TypeError("state dict must be a mapping")
        model.load_state_dict(payload)
        model.eval()
    except HdfsInferenceError:
        raise
    except Exception as error:
        raise HdfsInferenceError("MODEL_LOAD_FAILED", cause=type(error).__name__) from error

    threshold = float(manifest.metrics.best_threshold)
    block_ids = list(sequences.keys())
    if graphs:
        try:
            loader = DataLoader(graphs, batch_size=batch_size, shuffle=False)
            scores, _labels = compute_anomaly_scores(
                model,
                loader,
                torch.device("cpu"),
                alpha=manifest.scoring.alpha,
                beta=manifest.scoring.beta,
                gamma=manifest.scoring.gamma,
            )
            scores_list = [float(value) for value in np.asarray(scores).reshape(-1)]
        except Exception as error:
            raise HdfsInferenceError("INFERENCE_FAILED", cause=type(error).__name__) from error
    else:
        scores_list = []

    if len(scores_list) != len(block_ids):
        raise HdfsInferenceError(
            "INFERENCE_FAILED",
            cause="score count does not match block count",
        )

    blocks: list[BlockInferenceSnapshot] = []
    for index, (block_id, score) in enumerate(zip(block_ids, scores_list, strict=True)):
        graph = graphs[index]
        edge_index = _edge_index_tuple(graph)
        blocks.append(
            BlockInferenceSnapshot(
                block_id=str(block_id),
                score=score,
                decision=score > threshold,
                num_nodes=int(getattr(graph, "num_nodes", graph.x.size(0))),
                num_edges=int(graph.edge_index.size(1)),
                edge_index=edge_index,
                node_features=_feature_matrix(graph.x),
                edge_features=_feature_matrix(getattr(graph, "edge_attr", None)),
                matched_line_count=int(len(sequences[block_id])),
                source_lines=_source_lines(sequences[block_id]),
            )
        )
    return FrozenHdfsInferenceResult(
        threshold=threshold,
        parser_checksum=_sha256_file(parser_path),
        drain_config_checksum=_sha256_file(config_path),
        embeddings_checksum=_sha256_file(embeddings_path),
        artifact_checksum=_sha256_file(artifact_path),
        source_line_count=source_line_count,
        annotated_line_count=annotated_line_count,
        blocks=tuple(blocks),
    )


def load_frozen_embeddings(path: Path) -> dict[int, Any]:
    """Load canonical cluster embeddings without allowing pickled objects."""

    import numpy as np

    try:
        with np.load(path, allow_pickle=False) as payload:
            cluster_ids = np.asarray(payload["cluster_ids"])
            vectors = np.asarray(payload["embeddings"], dtype=np.float32)
    except Exception as error:
        raise HdfsInferenceError(
            "PREPROCESSING_BUNDLE_UNAVAILABLE",
            cause=type(error).__name__,
        ) from error
    return {int(cluster_id): vectors[index] for index, cluster_id in enumerate(cluster_ids)}


def normalise_edge_attributes(
    graphs: list[Any],
    edge_mean: list[float] | None,
    edge_std: list[float] | None,
) -> None:
    """Apply the package's frozen edge mean/std in place."""

    if edge_mean is None or edge_std is None:
        return
    import torch

    mean = torch.tensor(edge_mean, dtype=torch.float32)
    std = torch.tensor(edge_std, dtype=torch.float32)
    for graph in graphs:
        edge_attr = getattr(graph, "edge_attr", None)
        if edge_attr is not None and edge_attr.numel() > 0:
            graph.edge_attr = (edge_attr.float() - mean) / std


def compare_processing_parity(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> list[str]:
    """Return mismatch reasons; an empty list means the golden contract held.

    Numerical feature and score comparisons use the documented absolute/relative
    tolerances in ``expected["tolerances"]`` (defaults: 1e-5). Topology, block
    order, source references, parser checksums, and threshold decisions are exact.
    """

    mismatches: list[str] = []
    raw_tolerances = expected.get("tolerances")
    tolerances: Mapping[str, Any] = raw_tolerances if isinstance(raw_tolerances, Mapping) else {}
    feature_atol = float(tolerances.get("feature_atol", FEATURE_ATOL))
    feature_rtol = float(tolerances.get("feature_rtol", FEATURE_RTOL))
    score_atol = float(tolerances.get("score_atol", SCORE_ATOL))
    score_rtol = float(tolerances.get("score_rtol", SCORE_RTOL))

    raw_expected_checksums = expected.get("checksums")
    raw_actual_checksums = actual.get("checksums")
    expected_checksums: Mapping[str, Any] = (
        raw_expected_checksums if isinstance(raw_expected_checksums, Mapping) else {}
    )
    actual_checksums: Mapping[str, Any] = (
        raw_actual_checksums if isinstance(raw_actual_checksums, Mapping) else {}
    )
    parser_expected = expected_checksums.get("drain_parser.bin")
    parser_actual = actual_checksums.get("drain_parser.bin")
    if parser_expected != parser_actual:
        mismatches.append("PARSER_CHECKSUM: frozen Drain snapshot digest changed")

    if actual.get("source_line_count") != expected.get("source_line_count"):
        mismatches.append("LINE_COUNTS: source_line_count changed")
    if actual.get("annotated_line_count") != expected.get("annotated_line_count"):
        mismatches.append("LINE_COUNTS: annotated_line_count changed")
    if actual.get("source_line_count") != actual.get("annotated_line_count"):
        mismatches.append("LINE_COUNTS: not every source line matched a frozen template")

    expected_ids = [str(item) for item in expected.get("ordered_block_ids") or []]
    actual_ids = [str(item) for item in actual.get("ordered_block_ids") or []]
    if actual_ids != expected_ids:
        mismatches.append("ORDERED_BLOCKS: block order or identity changed")

    if not _floats_equal(actual.get("threshold"), expected.get("threshold")):
        mismatches.append("THRESHOLD: decision threshold is not exactly equal")

    expected_blocks = list(expected.get("blocks") or [])
    actual_blocks = list(actual.get("blocks") or [])
    if len(actual_blocks) != len(expected_blocks):
        mismatches.append("ORDERED_BLOCKS: block count changed")
        return mismatches

    for actual_block, expected_block in zip(actual_blocks, expected_blocks, strict=True):
        block_id = str(actual_block.get("block_id"))
        if str(expected_block.get("block_id")) != block_id:
            mismatches.append(f"ORDERED_BLOCKS: expected {expected_block.get('block_id')} got {block_id}")
            continue
        if int(actual_block.get("num_nodes", -1)) != int(expected_block.get("num_nodes", -2)):
            mismatches.append(f"GRAPH_TOPOLOGY: {block_id} node count changed")
        if int(actual_block.get("num_edges", -1)) != int(expected_block.get("num_edges", -2)):
            mismatches.append(f"GRAPH_TOPOLOGY: {block_id} edge count changed")
        if actual_block.get("edge_index") != expected_block.get("edge_index"):
            mismatches.append(f"GRAPH_TOPOLOGY: {block_id} edge_index changed")
        if not _matrices_close(
            actual_block.get("node_features"),
            expected_block.get("node_features"),
            atol=feature_atol,
            rtol=feature_rtol,
        ):
            mismatches.append(f"GRAPH_FEATURES: {block_id} node features drifted")
        if not _matrices_close(
            actual_block.get("edge_features"),
            expected_block.get("edge_features"),
            atol=feature_atol,
            rtol=feature_rtol,
        ):
            mismatches.append(f"GRAPH_FEATURES: {block_id} edge features drifted")
        if not _floats_close(
            actual_block.get("score"),
            expected_block.get("score"),
            atol=score_atol,
            rtol=score_rtol,
        ):
            mismatches.append(f"SCORES: {block_id} score drifted")
        expected_decision = bool(expected_block.get("decision"))
        actual_score = float(actual_block.get("score", 0.0))
        actual_threshold = float(actual.get("threshold", 0.0))
        actual_decision = bool(actual_block.get("decision"))
        if actual_decision != (actual_score > actual_threshold):
            mismatches.append(f"DECISIONS: {block_id} decision is not score > threshold")
        if actual_decision != expected_decision:
            mismatches.append(f"DECISIONS: {block_id} threshold decision changed")
        if int(actual_block.get("matched_line_count", -1)) != int(
            expected_block.get("matched_line_count", -2)
        ):
            mismatches.append(f"SOURCE_REFERENCES: {block_id} matched_line_count changed")
        if actual_block.get("source_lines") != expected_block.get("source_lines"):
            mismatches.append(f"SOURCE_REFERENCES: {block_id} source lines changed")
    return mismatches


def _block_snapshot(block: BlockInferenceSnapshot) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "score": block.score,
        "decision": block.decision,
        "num_nodes": block.num_nodes,
        "num_edges": block.num_edges,
        "edge_index": [list(row) for row in block.edge_index],
        "node_features": [list(row) for row in block.node_features],
        "edge_features": [list(row) for row in block.edge_features],
        "matched_line_count": block.matched_line_count,
        "source_lines": [
            {"line_number": line.line_number, "raw": line.raw} for line in block.source_lines
        ],
    }


def _source_lines(frame: Any) -> tuple[SourceLine, ...]:
    rows = frame.to_dict("records") if hasattr(frame, "to_dict") else []
    evidence: list[SourceLine] = []
    for row in rows[:MAX_CONTEXT_LINES]:
        raw = str(row.get("raw") or "")[:MAX_RAW_CHARS]
        line_number = int(row["line_number"]) if row.get("line_number") is not None else None
        evidence.append(SourceLine(line_number=line_number, raw=raw))
    return tuple(evidence)


def _count_nonempty_lines(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.rstrip("\n"):
                count += 1
    return count


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _edge_index_tuple(graph: Any) -> tuple[tuple[int, ...], tuple[int, ...]]:
    payload = graph.edge_index.detach().cpu().tolist()
    if not payload:
        return ((), ())
    return (tuple(int(value) for value in payload[0]), tuple(int(value) for value in payload[1]))


def _feature_matrix(tensor: Any) -> tuple[tuple[float, ...], ...]:
    if tensor is None:
        return ()
    if getattr(tensor, "numel", lambda: 0)() == 0:
        return ()
    rows = tensor.detach().cpu().tolist()
    if not rows:
        return ()
    if isinstance(rows[0], list):
        return tuple(tuple(float(value) for value in row) for row in rows)
    return (tuple(float(value) for value in rows),)


def _floats_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return float(left) == float(right)


def _floats_close(left: Any, right: Any, *, atol: float, rtol: float) -> bool:
    if left is None or right is None:
        return left is right
    left_value = float(left)
    right_value = float(right)
    return abs(left_value - right_value) <= atol + rtol * abs(right_value)


def _matrices_close(left: Any, right: Any, *, atol: float, rtol: float) -> bool:
    left_rows = _as_matrix(left)
    right_rows = _as_matrix(right)
    if len(left_rows) != len(right_rows):
        return False
    for left_row, right_row in zip(left_rows, right_rows, strict=True):
        if len(left_row) != len(right_row):
            return False
        for left_value, right_value in zip(left_row, right_row, strict=True):
            if not _floats_close(left_value, right_value, atol=atol, rtol=rtol):
                return False
    return True


def _as_matrix(value: Any) -> Sequence[Sequence[float]]:
    if not value:
        return []
    return value
