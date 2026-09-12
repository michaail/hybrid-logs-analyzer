#!/usr/bin/env python3
"""Build a checksum-bound HDFS evaluation dataset from complete selected-block histories.

The command requires explicit corpus, labels, and ordered selected-ID paths. It never
selects a newest source file, split, or release. Output is an atomically published
workspace artifact containing bounded source-order shards and a provenance manifest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="Path to the approved HDFS source log",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        required=True,
        help="Path to the HDFS block-label CSV",
    )
    parser.add_argument(
        "--selected-block-ids",
        type=Path,
        required=True,
        help="Ordered selected block IDs, one identifier per line",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path.cwd(),
        help="Workspace root for the published artifact cache",
    )
    parser.add_argument(
        "--code-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Checked-out source root recorded in the artifact fingerprint",
    )
    parser.add_argument(
        "--max-source-lines",
        type=int,
        default=None,
        help="Optional per-shard non-empty source-line cap",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=None,
        help="Optional per-shard selected-block cap",
    )
    return parser.parse_args(argv)


def _require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} must be an existing file: {path}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    from src.modules.hdfs_evaluation_data import (
        DEFAULT_MAX_BLOCKS,
        DEFAULT_MAX_SOURCE_LINES,
        EvaluationDataError,
        publish_hdfs_evaluation_dataset,
    )

    args = _parse_args(argv)
    try:
        corpus = _require_file(args.corpus, "Corpus")
        labels = _require_file(args.labels, "Labels")
        selected_block_ids = _require_file(args.selected_block_ids, "Selected block-id file")
        published = publish_hdfs_evaluation_dataset(
            corpus=corpus,
            labels=labels,
            selected_block_ids=selected_block_ids,
            workspace_root=args.workspace_root,
            code_root=args.code_root,
            max_source_lines=args.max_source_lines or DEFAULT_MAX_SOURCE_LINES,
            max_blocks=args.max_blocks or DEFAULT_MAX_BLOCKS,
        )
    except (EvaluationDataError, FileNotFoundError, OSError) as error:
        print(f"HDFS evaluation dataset failed: {error}", file=sys.stderr)
        return 1
    status = "reused" if published.reused else "published"
    print(
        f"HDFS evaluation dataset {status}. Manifest: {published.manifest_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
