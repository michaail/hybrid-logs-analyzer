#!/usr/bin/env python3
"""Verify a labelled HDFS baseline release against frozen inference metrics.

The command accepts explicit baseline-release paths only. It checks corpus and
artefact SHA-256 values, recomputes test F1 / PR-AUC / ROC-AUC, and exits
nonzero when a checksum mismatches, the decision threshold changes, or a core
metric moves by more than 0.01. The comparison report is written beside the
release evidence and never replaces the immutable expected record.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.modules.hdfs_parity import (
    load_parity_expected,
    load_test_block_ids,
    verify_hdfs_release,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-package",
        type=Path,
        required=True,
        help="Path to the exported v2 model ZIP",
    )
    parser.add_argument(
        "--preprocessing-bundle",
        type=Path,
        required=True,
        help="Path to the exported preprocessing-bundle ZIP",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        required=True,
        help="Path to the labelled baseline HDFS log",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        required=True,
        help="Path to anomaly_label.csv",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        required=True,
        help="Immutable expected checksums and metrics JSON",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Comparison report path (default: <expected-dir>/parity-report.json)",
    )
    parser.add_argument(
        "--test-block-ids",
        type=Path,
        default=None,
        help="Optional ordered test-split block IDs, one per line",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    expected = load_parity_expected(args.expected)
    report_path = args.report or (args.expected.parent / "parity-report.json")
    test_block_ids = load_test_block_ids(args.test_block_ids) if args.test_block_ids else None
    report = verify_hdfs_release(
        model_package=args.model_package,
        preprocessing_bundle=args.preprocessing_bundle,
        corpus=args.corpus,
        labels=args.labels,
        expected=expected,
        report_path=report_path,
        test_block_ids=test_block_ids,
    )
    status = "passed" if report["passed"] else "failed"
    print(f"HDFS parity {status}. Report: {report_path}")
    if report["failures"]:
        print("Failures: " + ", ".join(report["failures"]))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
