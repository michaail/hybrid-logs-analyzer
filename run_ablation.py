#!/usr/bin/env python3
"""Run reproducible HDFS/BGL ablations locally or from Google Colab.

The code checkout and the data workspace are intentionally independent:

* ``--code-root`` contains this repository and versioned configuration.
* ``--workspace-root`` contains ignored raw data, cache artifacts, models, and
  result files.  In Colab it normally points to ``/content/workspace``.

Stages publish only after all declared outputs exist, so a disconnected Colab
runtime can safely resume from the latest successful stage cache.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.modules.artifacts import ArtifactStore
from src.modules.dataset import (
    build_pyg_dataset,
    compute_embeddings,
    save_graph_dataset,
    split_dataset,
)
from src.modules.enrichment import enrich_templates, load_enriched_templates
from src.modules.parser import BGLParser, DrainParser
from src.modules.sequencer import build_sequences, load_sequences, save_sequences
from src.modules.utils import get_device, seed_everything


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML experiment configuration and retain its source location."""
    config_path = Path(path).resolve()
    with config_path.open() as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError(f"Configuration must be a mapping: {config_path}")
    config["__pipeline__"] = {
        "config_path": str(config_path),
        "code_root": str(config_path.parent.parent),
        "workspace_root": os.environ.get("PIPELINE_WORKSPACE_ROOT"),
    }
    return config


def apply_overrides(config: dict[str, Any], overrides: list[str]) -> dict[str, Any]:
    """Apply ``section.key=value`` YAML overrides without mutating *config*."""
    updated = copy.deepcopy(config)
    for override in overrides:
        if "=" not in override:
            raise ValueError(f"Expected KEY=VALUE override, received: {override!r}")
        dotted_key, raw_value = override.split("=", maxsplit=1)
        keys = dotted_key.split(".")
        if not all(keys):
            raise ValueError(f"Invalid override key: {dotted_key!r}")
        target: dict[str, Any] = updated
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            if not isinstance(target[key], dict):
                raise ValueError(f"Override path is not a mapping: {dotted_key!r}")
            target = target[key]
        target[keys[-1]] = yaml.safe_load(raw_value)
    return updated


def get_run_tag(config: dict[str, Any]) -> str:
    """Return an explicit run id or a timestamped, human-readable one."""
    experiment = config["experiment"]
    requested = experiment.get("run_id")
    if requested:
        return _safe_name(str(requested))
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{_safe_name(experiment['name'])}"


def stage1_parse(
    config: dict[str, Any],
    run_tag: str | None = None,
    *,
    workspace_root: str | Path | None = None,
    code_root: str | Path | None = None,
) -> Path:
    """Parse a raw log once and return the annotated-Parquet artifact."""
    return _stage1_artifacts(
        config, workspace_root=workspace_root, code_root=code_root
    )["annotated"]


def stage2_enrich(
    config: dict[str, Any],
    run_tag: str | None = None,
    *,
    source_run_tag: str | None = None,
    workspace_root: str | Path | None = None,
    code_root: str | Path | None = None,
) -> Path:
    """Create (or reuse) templates enriched by the configured LLM."""
    workspace, code = _roots(config, workspace_root, code_root)
    dataset = _dataset(config)
    stage1 = _stage1_artifacts(config, workspace_root=workspace, code_root=code)
    store = ArtifactStore(workspace, dataset, code)
    ablation = config["ablation"]
    stage_config = {
        "dataset": dataset,
        "llm_enrichment_enabled": bool(ablation["llm_enrichment_enabled"]),
        "enrichment_model_size": ablation["enrichment_model_size"],
    }

    def build(temp_dir: Path) -> dict[str, Path]:
        destination = temp_dir / "templates.json"
        with stage1["templates"].open() as handle:
            templates = json.load(handle)
        if ablation["llm_enrichment_enabled"]:
            enrich_templates(
                templates,
                dataset,
                model_size=str(ablation["enrichment_model_size"]),
            )
        destination.write_text(json.dumps(templates, indent=2))
        return {"templates": destination}

    outputs, _, reused = store.stage(
        stage="stage2_enrich",
        stage_config=stage_config,
        inputs=[stage1["templates"]],
        build=build,
    )
    _announce("stage2_enrich", reused)
    return outputs["templates"]


def stage3_sequence(
    config: dict[str, Any],
    run_tag: str | None = None,
    *,
    source_run_tag: str | None = None,
    workspace_root: str | Path | None = None,
    code_root: str | Path | None = None,
) -> Path:
    """Build (or reuse) explicit HDFS blocks or BGL time-window sequences."""
    workspace, code = _roots(config, workspace_root, code_root)
    dataset = _dataset(config)
    stage1 = _stage1_artifacts(config, workspace_root=workspace, code_root=code)
    store = ArtifactStore(workspace, dataset, code)
    sequencing = config.get("sequencing", {}).get(dataset, {})
    stage_config = {"dataset": dataset, **sequencing}

    def build(temp_dir: Path) -> dict[str, Path]:
        frame = _read_parquet(stage1["annotated"])
        sequences = build_sequences(frame, dataset, **sequencing)
        if not sequences:
            raise ValueError(f"No {dataset.upper()} sequences were built from {stage1['annotated']}")
        flat_sequences = pd.concat(sequences.values(), ignore_index=True)
        destination = temp_dir / "sequences.parquet"
        save_sequences(flat_sequences, destination)
        return {"sequences": destination}

    outputs, _, reused = store.stage(
        stage="stage3_sequence",
        stage_config=stage_config,
        inputs=[stage1["annotated"]],
        build=build,
    )
    _announce("stage3_sequence", reused)
    return outputs["sequences"]


def stage45_build_dataset(
    config: dict[str, Any],
    run_tag: str | None,
    templates_path: str | Path,
    sequences_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    code_root: str | Path | None = None,
) -> Path:
    """Build the PyG graph bundle from explicit template and sequence artifacts."""
    workspace, code = _roots(config, workspace_root, code_root)
    dataset = _dataset(config)
    templates_path = Path(templates_path).resolve()
    sequences_path = Path(sequences_path).resolve()
    raw_dir = workspace / config["paths"]["raw_dir"]
    labels_path = raw_dir / "anomaly_label.csv"
    inputs = [templates_path, sequences_path]
    if dataset == "hdfs":
        inputs.append(labels_path)
    ablation = config["ablation"]
    stage_config = {
        "dataset": dataset,
        "seed": config["experiment"]["seed"],
        "embeddings": ablation["embeddings"],
        "use_edge_features": ablation["graph"]["use_edge_features"],
    }
    store = ArtifactStore(workspace, dataset, code)

    def build(temp_dir: Path) -> dict[str, Path]:
        templates, _, cluster_to_enriched = load_enriched_templates(templates_path)
        _, sequences = load_sequences(sequences_path, dataset)
        labels = _sequence_labels(
            dataset=dataset,
            sequences=sequences,
            labels_path=labels_path if dataset == "hdfs" else None,
        )
        embeddings, cluster_ids, _ = compute_embeddings(
            templates,
            cluster_to_enriched,
            tfidf_enabled=bool(ablation["embeddings"]["tfidf_enabled"]),
            sbert_enabled=bool(ablation["embeddings"]["sbert_enabled"]),
        )
        cluster_embeddings = {
            cluster_id: embedding
            for cluster_id, embedding in zip(cluster_ids, embeddings, strict=True)
        }
        data_list = build_pyg_dataset(
            sequences,
            labels,
            cluster_embeddings,
            use_edge_features=bool(ablation["graph"]["use_edge_features"]),
            dataset=dataset,
        )
        if not data_list:
            raise ValueError("Graph builder produced no examples.")
        idx_train, idx_val, idx_test = split_dataset(
            data_list, seed=int(config["experiment"]["seed"])
        )
        node_dim = int(data_list[0].x.shape[1])
        edge_dim = int(data_list[0].edge_attr.shape[1])
        graph_path = temp_dir / "graph_dataset.pt"
        save_graph_dataset(
            data_list,
            idx_train,
            idx_val,
            idx_test,
            graph_path,
            node_dim=node_dim,
            edge_dim=edge_dim,
            embed_dim=int(embeddings.shape[1]),
        )
        np.savez_compressed(
            temp_dir / "embeddings.npz",
            cluster_ids=np.asarray(cluster_ids),
            embeddings=embeddings,
        )
        meta = {
            "dataset": dataset,
            "n_total": len(data_list),
            "n_train": len(idx_train),
            "n_val": len(idx_val),
            "n_test": len(idx_test),
            "anomaly_rate": float(np.mean([item.y.item() for item in data_list])),
            "node_dim": node_dim,
            "edge_dim": edge_dim,
            "embed_dim": int(embeddings.shape[1]),
            "embedding_flags": ablation["embeddings"],
            "use_edge_features": bool(ablation["graph"]["use_edge_features"]),
        }
        meta_path = temp_dir / "dataset_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2))
        return {
            "graph_dataset": graph_path,
            "embeddings": temp_dir / "embeddings.npz",
            "dataset_meta": meta_path,
        }

    outputs, _, reused = store.stage(
        stage="stage45_build_dataset",
        stage_config=stage_config,
        inputs=inputs,
        build=build,
    )
    _announce("stage45_build_dataset", reused)
    return outputs["graph_dataset"]


def stage6_train(
    config: dict[str, Any],
    run_tag: str | None,
    graph_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    code_root: str | Path | None = None,
) -> dict[str, Any]:
    """Train the selected GAE variant and return metrics plus training history."""
    workspace, code = _roots(config, workspace_root, code_root)
    dataset = _dataset(config)
    graph_path = Path(graph_path).resolve()
    training = _resolved_training(config, dataset)
    ablation_graph = config["ablation"]["graph"]
    stage_config = {
        "dataset": dataset,
        "seed": config["experiment"]["seed"],
        "training": training,
        "gine_aggregation": ablation_graph["gine_aggregation"],
        "node_transformation": ablation_graph["node_transformation"],
    }
    store = ArtifactStore(workspace, dataset, code)

    def build(temp_dir: Path) -> dict[str, Path]:
        metrics, checkpoint = _train_graph_bundle(
            graph_path,
            training=training,
            seed=int(config["experiment"]["seed"]),
            gine_aggregation=str(ablation_graph["gine_aggregation"]),
            node_transformation=str(ablation_graph["node_transformation"]),
        )
        metrics_path = temp_dir / "metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2))
        import torch

        checkpoint_path = temp_dir / "attribute_gae.pt"
        torch.save(checkpoint, checkpoint_path)
        return {"metrics": metrics_path, "checkpoint": checkpoint_path}

    outputs, _, reused = store.stage(
        stage="stage6_train",
        stage_config=stage_config,
        inputs=[graph_path],
        build=build,
    )
    _announce("stage6_train", reused)
    metrics = json.loads(outputs["metrics"].read_text())
    metrics["model_path"] = str(outputs["checkpoint"])
    return metrics


def run_experiment(
    config: dict[str, Any],
    *,
    mode: str,
    workspace_root: str | Path | None = None,
    code_root: str | Path | None = None,
    graph_dataset: str | Path | None = None,
    input_run_id: str | None = None,
    checkpoint_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run one configuration and persist a small run manifest."""
    workspace, code = _roots(config, workspace_root, code_root)
    run_tag = get_run_tag(config)
    dataset = _dataset(config)
    started = time.monotonic()

    if mode in {"full", "smoke"}:
        stage1_parse(config, run_tag, workspace_root=workspace, code_root=code)
        _checkpoint_workspace(workspace, checkpoint_root)
        templates = stage2_enrich(
            config, run_tag, workspace_root=workspace, code_root=code
        )
        _checkpoint_workspace(workspace, checkpoint_root)
        sequences = stage3_sequence(
            config, run_tag, workspace_root=workspace, code_root=code
        )
        _checkpoint_workspace(workspace, checkpoint_root)
        graph_path = stage45_build_dataset(
            config,
            run_tag,
            templates,
            sequences,
            workspace_root=workspace,
            code_root=code,
        )
        _checkpoint_workspace(workspace, checkpoint_root)
    elif mode == "train-only":
        graph_path = _resolve_graph_dataset(
            workspace, graph_dataset=graph_dataset, input_run_id=input_run_id
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    metrics = stage6_train(
        config,
        run_tag,
        graph_path,
        workspace_root=workspace,
        code_root=code,
    )
    _checkpoint_workspace(workspace, checkpoint_root)
    output_dir = workspace / config["paths"]["outputs_dir"] / dataset / run_tag
    output_dir.mkdir(parents=True, exist_ok=True)
    metric_output = output_dir / "metrics.json"
    metric_output.write_text(json.dumps(metrics, indent=2))
    model_output = output_dir / "attribute_gae.pt"
    shutil.copy2(metrics["model_path"], model_output)

    record = {
        "run_id": run_tag,
        "dataset": dataset,
        "mode": mode,
        "created_at": datetime.now(UTC).isoformat(),
        "elapsed_minutes": round((time.monotonic() - started) / 60, 2),
        "config": _serialisable_config(config),
        "artifacts": {
            "graph_dataset": _workspace_relative(graph_path, workspace),
            "metrics": _workspace_relative(metric_output, workspace),
            "checkpoint": _workspace_relative(model_output, workspace),
        },
        "metrics": {key: value for key, value in metrics.items() if key != "history"},
        "history": metrics["history"],
    }
    run_manifest = workspace / "artifacts" / "runs" / f"{run_tag}.json"
    run_manifest.parent.mkdir(parents=True, exist_ok=True)
    run_manifest.write_text(json.dumps(record, indent=2))
    _checkpoint_workspace(workspace, checkpoint_root)
    return record


def _stage1_artifacts(
    config: dict[str, Any],
    *,
    workspace_root: str | Path | None = None,
    code_root: str | Path | None = None,
) -> dict[str, Path]:
    workspace, code = _roots(config, workspace_root, code_root)
    dataset = _dataset(config)
    parser_settings = config["parser"][dataset]
    raw_path = workspace / config["paths"]["raw_dir"] / parser_settings["raw_file"]
    parser_config = code / parser_settings["config"]
    store = ArtifactStore(workspace, dataset, code)
    stage_config = {
        "dataset": dataset,
        "parser_config": parser_settings["config"],
        "raw_file": parser_settings["raw_file"],
    }

    def build(temp_dir: Path) -> dict[str, Path]:
        parser_cls = BGLParser if dataset == "bgl" else DrainParser
        state_path = temp_dir / "drain_parser.bin"
        parser = parser_cls(
            config_path=str(parser_config),
            persistence_path=str(state_path),
        )
        parser.fit_file(str(raw_path))
        frame = parser.annotate_file(str(raw_path))
        templates_path = temp_dir / "templates.json"
        parser.export_templates(str(templates_path))
        parser.save()
        annotated_path = temp_dir / "annotated.parquet"
        _write_parquet(frame, annotated_path)
        return {
            "annotated": annotated_path,
            "templates": templates_path,
            "parser_state": state_path,
        }

    outputs, _, reused = store.stage(
        stage="stage1_parse",
        stage_config=stage_config,
        inputs=[raw_path, parser_config],
        build=build,
    )
    _announce("stage1_parse", reused)
    return outputs


def _train_graph_bundle(
    graph_path: Path,
    *,
    training: dict[str, Any],
    seed: int,
    gine_aggregation: str,
    node_transformation: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import torch
    from sklearn.metrics import (
        average_precision_score,
        confusion_matrix,
        f1_score,
        precision_recall_curve,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from torch.optim import Adam
    from torch_geometric.loader import DataLoader

    from src.modules.models.gae import (
        AttributeAwareGAE,
        compute_anomaly_scores,
        train_epoch,
    )

    seed_everything(seed)
    device = get_device()
    bundle = torch.load(graph_path, weights_only=False, map_location="cpu")
    all_data = bundle["data_list"]
    train_graphs = [all_data[int(index)] for index in bundle["idx_train"]]
    val_graphs = [all_data[int(index)] for index in bundle["idx_val"]]
    test_graphs = [all_data[int(index)] for index in bundle["idx_test"]]
    if training["train_mode"] == "clean":
        train_graphs = [graph for graph in train_graphs if graph.y.item() == 0]
    if not train_graphs:
        raise ValueError("No training graphs remain after applying train_mode.")

    if training["test_run"]:
        sample_count = int(training["test_samples"])
        train_graphs = train_graphs[:sample_count]
        val_graphs = val_graphs[:sample_count]
        test_graphs = test_graphs[:sample_count]

    edge_mean, edge_std = _normalise_edge_attributes(
        train_graphs,
        val_graphs,
        test_graphs,
        enabled=bool(training["pre_normalize_edges"]),
        minimum_std=float(training["minimum_edge_std"]),
    )
    batch_size = int(training["batch_size"])
    train_loader = DataLoader(train_graphs, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_graphs, batch_size=batch_size)
    test_loader = DataLoader(test_graphs, batch_size=batch_size)

    model = AttributeAwareGAE(
        node_dim=int(bundle["node_dim"]),
        edge_dim=int(bundle["edge_dim"]),
        hidden_dim=int(training["hidden_dim"]),
        latent_dim=int(training["latent_dim"]),
        gine_aggregation=gine_aggregation,
        node_transformation=node_transformation,
    ).to(device)
    optimizer = Adam(model.parameters(), lr=float(training["learning_rate"]))
    loss_args = {
        "alpha": float(training["alpha"]),
        "beta": float(training["beta"]),
        "gamma": float(training["gamma"]),
    }
    history: list[dict[str, float | int]] = []
    best_state: dict[str, Any] | None = None
    best_val_f1 = -1.0
    best_threshold = 0.5

    for epoch in range(1, int(training["epochs"]) + 1):
        total, structure, node, edge = train_epoch(
            model, train_loader, optimizer, device, **loss_args
        )
        val_scores, val_labels = compute_anomaly_scores(model, val_loader, device, **loss_args)
        threshold, val_metrics = _threshold_and_metrics(val_labels, val_scores)
        history.append(
            {
                "epoch": epoch,
                "train_total_loss": total,
                "train_structure_loss": structure,
                "train_node_loss": node,
                "train_edge_loss": edge,
                "val_f1": val_metrics["f1"],
                "val_pr_auc": val_metrics["pr_auc"],
                "val_roc_auc": val_metrics["roc_auc"],
            }
        )
        if val_metrics["f1"] >= best_val_f1:
            best_val_f1 = val_metrics["f1"]
            best_threshold = threshold
            best_state = copy.deepcopy(model.state_dict())

    if best_state is None:
        raise RuntimeError("Training did not produce a validation checkpoint.")
    model.load_state_dict(best_state)
    val_scores, val_labels = compute_anomaly_scores(model, val_loader, device, **loss_args)
    _, val_metrics = _threshold_and_metrics(val_labels, val_scores, threshold=best_threshold)
    test_scores, test_labels = compute_anomaly_scores(model, test_loader, device, **loss_args)
    test_metrics = _score_metrics(test_labels, test_scores, best_threshold)
    test_predictions = (test_scores > best_threshold).astype(int)
    matrix = confusion_matrix(test_labels, test_predictions, labels=[0, 1]).tolist()
    test_metrics.update(
        {
            "precision": _rounded(precision_score(test_labels, test_predictions, zero_division=0)),
            "recall": _rounded(recall_score(test_labels, test_predictions, zero_division=0)),
            "confusion_matrix": matrix,
        }
    )
    metrics: dict[str, Any] = {
        "best_threshold": _rounded(best_threshold),
        "val_f1": val_metrics["f1"],
        "val_pr_auc": val_metrics["pr_auc"],
        "val_roc_auc": val_metrics["roc_auc"],
        "test_f1": test_metrics["f1"],
        "test_pr_auc": test_metrics["pr_auc"],
        "test_roc_auc": test_metrics["roc_auc"],
        "test_precision": test_metrics["precision"],
        "test_recall": test_metrics["recall"],
        "test_confusion_matrix": test_metrics["confusion_matrix"],
        "device": str(device),
        "n_train": len(train_graphs),
        "n_val": len(val_graphs),
        "n_test": len(test_graphs),
        "history": history,
    }
    checkpoint = {
        "model_state_dict": best_state,
        "node_dim": int(bundle["node_dim"]),
        "edge_dim": int(bundle["edge_dim"]),
        "hidden_dim": int(training["hidden_dim"]),
        "latent_dim": int(training["latent_dim"]),
        "best_threshold": best_threshold,
        "training": training,
        "history": _loss_history(history),
        "edge_mean": edge_mean,
        "edge_std": edge_std,
        "gine_aggregation": gine_aggregation,
        "node_transformation": node_transformation,
    }
    metrics["history"] = _loss_history(history)
    return metrics, checkpoint


def _normalise_edge_attributes(
    train_graphs: list,
    val_graphs: list,
    test_graphs: list,
    *,
    enabled: bool,
    minimum_std: float,
) -> tuple[list[float] | None, list[float] | None]:
    """Fit edge scaling on training graphs only, then apply to every split."""
    if not enabled:
        return None, None
    import torch

    training_edges = [
        graph.edge_attr.float()
        for graph in train_graphs
        if getattr(graph, "edge_attr", None) is not None and graph.edge_attr.numel() > 0
    ]
    if not training_edges:
        return None, None
    stacked = torch.cat(training_edges, dim=0)
    mean = stacked.mean(dim=0)
    std = stacked.std(dim=0).clamp_min(minimum_std)
    for graph in [*train_graphs, *val_graphs, *test_graphs]:
        edge_attr = getattr(graph, "edge_attr", None)
        if edge_attr is not None and edge_attr.numel() > 0:
            graph.edge_attr = (edge_attr.float() - mean) / std
    return mean.tolist(), std.tolist()


def _loss_history(history: list[dict[str, float | int]]) -> dict[str, list[float]]:
    """Convert per-epoch records to the compact plot/checkpoint contract."""
    return {
        "total": [float(entry["train_total_loss"]) for entry in history],
        "structure": [float(entry["train_structure_loss"]) for entry in history],
        "node": [float(entry["train_node_loss"]) for entry in history],
        "edge": [float(entry["train_edge_loss"]) for entry in history],
    }


def _threshold_and_metrics(
    labels: np.ndarray, scores: np.ndarray, *, threshold: float | None = None
) -> tuple[float, dict[str, float]]:
    from sklearn.metrics import precision_recall_curve

    if threshold is None:
        precision, recall, thresholds = precision_recall_curve(labels, scores)
        if len(thresholds) == 0:
            threshold = float(np.median(scores))
        else:
            f1_values = (2 * precision[:-1] * recall[:-1]) / (
                precision[:-1] + recall[:-1] + 1e-12
            )
            threshold = float(thresholds[int(np.nanargmax(f1_values))])
    return threshold, _score_metrics(labels, scores, threshold)


def _score_metrics(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

    predictions = (scores > threshold).astype(int)
    has_both_classes = len(np.unique(labels)) == 2
    return {
        "f1": _rounded(f1_score(labels, predictions, zero_division=0)),
        "pr_auc": _rounded(average_precision_score(labels, scores)) if has_both_classes else 0.0,
        "roc_auc": _rounded(roc_auc_score(labels, scores)) if has_both_classes else 0.0,
    }


def _sequence_labels(
    *,
    dataset: str,
    sequences: dict,
    labels_path: Path | None,
) -> dict[Any, int]:
    if dataset == "bgl":
        return {
            sequence_id: int(group["is_anomaly"].fillna(False).astype(bool).any())
            for sequence_id, group in sequences.items()
        }
    if labels_path is None or not labels_path.exists():
        raise FileNotFoundError(
            "HDFS requires data/raw/anomaly_label.csv for reproducible labels."
        )
    labels_frame = pd.read_csv(labels_path)
    columns = {column.lower(): column for column in labels_frame.columns}
    id_column = next(
        (columns[name] for name in ("blockid", "block_id") if name in columns), None
    )
    label_column = next(
        (columns[name] for name in ("label", "anomaly", "is_anomaly") if name in columns), None
    )
    if id_column is None or label_column is None:
        raise ValueError(
            f"Expected BlockId and Label columns in {labels_path}; found {list(labels_frame.columns)}"
        )
    mapping = {
        str(row[id_column]): _to_binary_label(row[label_column])
        for _, row in labels_frame.iterrows()
    }
    return {sequence_id: mapping.get(str(sequence_id), 0) for sequence_id in sequences}


def _to_binary_label(value: Any) -> int:
    if isinstance(value, str):
        return int(value.strip().lower() in {"1", "true", "anomaly", "anomalous"})
    return int(bool(value))


def _read_parquet(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path, engine=_parquet_engine())
    if "parameters" in frame.columns:
        frame["parameters"] = frame["parameters"].apply(
            lambda value: json.loads(value) if isinstance(value, str) else (value or [])
        )
    return frame


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    result = frame.copy()
    if "parameters" in result.columns:
        result["parameters"] = result["parameters"].apply(json.dumps)
    for column in result.select_dtypes(include=["object", "string"]).columns:
        result[column] = result[column].astype(object)
    result.to_parquet(path, index=False, engine=_parquet_engine())


def _parquet_engine() -> str:
    """Prefer legacy fastparquet artifacts while allowing a clean PyArrow setup."""
    return "fastparquet" if find_spec("fastparquet") else "pyarrow"


def _roots(
    config: dict[str, Any],
    workspace_root: str | Path | None,
    code_root: str | Path | None,
) -> tuple[Path, Path]:
    meta = config.get("__pipeline__", {})
    workspace_value = workspace_root or meta.get("workspace_root") or os.environ.get(
        "PIPELINE_WORKSPACE_ROOT"
    )
    code_value = code_root or meta.get("code_root")
    if not code_value:
        raise ValueError("Unable to infer code root; use --code-root.")
    code = Path(code_value).resolve()
    workspace = Path(workspace_value).resolve() if workspace_value else code
    return workspace, code


def _dataset(config: dict[str, Any]) -> str:
    dataset = str(config["experiment"]["dataset"]).lower()
    if dataset not in {"bgl", "hdfs"}:
        raise ValueError(f"Unsupported dataset {dataset!r}; choose bgl or hdfs.")
    return dataset


def _resolved_training(config: dict[str, Any], dataset: str) -> dict[str, Any]:
    training = copy.deepcopy(config["training"])
    learning_rate = training.get("learning_rate")
    if isinstance(learning_rate, dict):
        training["learning_rate"] = learning_rate[dataset]
    return training


def _resolve_graph_dataset(
    workspace: Path,
    *,
    graph_dataset: str | Path | None,
    input_run_id: str | None,
) -> Path:
    if graph_dataset:
        path = Path(graph_dataset).expanduser().resolve()
    elif input_run_id:
        manifest = workspace / "artifacts" / "runs" / f"{_safe_name(input_run_id)}.json"
        if not manifest.exists():
            raise FileNotFoundError(f"No prior run manifest: {manifest}")
        path = workspace / json.loads(manifest.read_text())["artifacts"]["graph_dataset"]
    else:
        raise ValueError("train-only mode requires --graph-dataset or --input-run-id.")
    if not path.exists():
        raise FileNotFoundError(f"Graph dataset does not exist: {path}")
    return path


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    if not cleaned:
        raise ValueError("Run names must contain at least one letter or number.")
    return cleaned.strip(".-")


def _serialisable_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if key != "__pipeline__"}


def _workspace_relative(path: Path, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace))
    except ValueError:
        return str(path.resolve())


def _checkpoint_workspace(workspace: Path, checkpoint_root: str | Path | None) -> None:
    """Copy completed, ignored artifacts to a mounted durable workspace.

    Cache success manifests are copied only after their payloads.  If a Colab
    runtime disconnects during a large graph transfer, the next session sees no
    valid ``_SUCCESS.json`` and will safely resume the local copy.
    """
    if checkpoint_root is None:
        return
    destination_root = Path(checkpoint_root).resolve()
    if destination_root == workspace.resolve():
        return
    for name in ("artifacts", "models", "outputs", "runs"):
        source = workspace / name
        if not source.exists():
            continue
        destination = destination_root / name
        destination.mkdir(parents=True, exist_ok=True)
        if shutil.which("rsync"):
            subprocess.run(
                [
                    "rsync",
                    "-a",
                    "--partial",
                    "--exclude",
                    "_SUCCESS.json",
                    f"{source}/",
                    f"{destination}/",
                ],
                check=True,
            )
            subprocess.run(
                [
                    "rsync",
                    "-a",
                    "--include",
                    "*/",
                    "--include",
                    "_SUCCESS.json",
                    "--exclude",
                    "*",
                    f"{source}/",
                    f"{destination}/",
                ],
                check=True,
            )
        else:
            # Local fallback for systems without rsync.  It preserves the same
            # ordering guarantee, albeit without partial-file support.
            manifests: list[tuple[Path, Path]] = []
            for item in source.rglob("*"):
                relative = item.relative_to(source)
                target = destination / relative
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif item.name == "_SUCCESS.json":
                    manifests.append((item, target))
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
            for source_manifest, destination_manifest in manifests:
                destination_manifest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_manifest, destination_manifest)
    print(f"[CHECKPOINT] {destination_root}")


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _announce(stage: str, reused: bool) -> None:
    print(f"[{'REUSE' if reused else 'DONE'}] {stage}")


def _write_matrix_summary(
    workspace: Path, results: list[dict[str, Any]], *, dataset: str
) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = workspace / "outputs" / dataset / f"{timestamp}_ablation_matrix"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "ablation_results.json"
    json_path.write_text(json.dumps(results, indent=2))
    pd.DataFrame(results).to_csv(output_dir / "ablation_results.csv", index=False)
    return json_path


def _run_matrix(args: argparse.Namespace, base_config: dict[str, Any]) -> int:
    matrix_path = Path(args.matrix).resolve()
    matrix = yaml.safe_load(matrix_path.read_text()) or {}
    experiments = matrix.get("experiments", [])
    if not experiments:
        raise ValueError(f"No experiments found in {matrix_path}")
    results: list[dict[str, Any]] = []
    dataset = _dataset(base_config)
    for experiment in experiments:
        if not experiment.get("enabled", True):
            continue
        config = apply_overrides(
            base_config,
            [f"{key}={json.dumps(value)}" for key, value in experiment["overrides"].items()],
        )
        if args.run_id:
            config["experiment"]["run_id"] = f"{args.run_id}_{experiment['name']}"
        try:
            record = run_experiment(
                config,
                mode=args.mode,
                workspace_root=args.workspace_root,
                code_root=args.code_root,
                graph_dataset=args.graph_dataset,
                input_run_id=args.input_run_id,
                checkpoint_root=args.checkpoint_root,
            )
            results.append(
                {
                    "name": experiment["name"],
                    "status": "OK",
                    **record["metrics"],
                    "history": record["history"],
                }
            )
        except Exception as exc:  # Keep the matrix resumable even after one failed arm.
            results.append(
                {
                    "name": experiment["name"],
                    "status": "FAILED",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
    summary = _write_matrix_summary(Path(args.workspace_root).resolve(), results, dataset=dataset)
    _checkpoint_workspace(Path(args.workspace_root).resolve(), args.checkpoint_root)
    print(f"Matrix results: {summary}")
    return 0 if all(result["status"] == "OK" for result in results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("full", "train-only", "smoke"),
        default="full",
        help="Full raw-log pipeline, training-only, or a one-epoch no-LLM check.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ablation_base.yaml"),
        help="Base experiment YAML.",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        help="Optional matrix YAML to apply on top of the base config.",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path(os.environ.get("PIPELINE_WORKSPACE_ROOT", ".")),
        help="Ignored data/artifact root (separate from the code checkout).",
    )
    parser.add_argument(
        "--code-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Repository checkout that contains configs/ and src/.",
    )
    parser.add_argument("--run-id", help="Optional explicit id for this run.")
    parser.add_argument(
        "--input-run-id", help="Prior full-run id whose graph bundle should be trained."
    )
    parser.add_argument(
        "--graph-dataset",
        type=Path,
        help="Explicit graph_dataset.pt path for train-only mode.",
    )
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        help="Mounted durable workspace copied after every successful stage.",
    )
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="YAML-aware override; may be repeated.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = args.config
    if not config_path.is_absolute():
        config_path = args.code_root / config_path
    config = load_config(config_path)
    config = apply_overrides(config, args.overrides)
    config["__pipeline__"]["workspace_root"] = str(args.workspace_root.resolve())
    config["__pipeline__"]["code_root"] = str(args.code_root.resolve())
    if args.run_id and not args.matrix:
        config["experiment"]["run_id"] = args.run_id
    if args.mode == "smoke":
        config = apply_overrides(
            config,
            [
                "ablation.llm_enrichment_enabled=false",
                "training.test_run=true",
                "training.epochs=1",
            ],
        )
    if args.matrix:
        return _run_matrix(args, config)
    record = run_experiment(
        config,
        mode=args.mode,
        workspace_root=args.workspace_root,
        code_root=args.code_root,
        graph_dataset=args.graph_dataset,
        input_run_id=args.input_run_id,
        checkpoint_root=args.checkpoint_root,
    )
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
