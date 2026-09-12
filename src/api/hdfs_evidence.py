"""Reconstruct HDFS block source sequences from an admitted dataset log."""

from __future__ import annotations

import re
from datetime import datetime

from src.api.schemas import HdfsSourceLine

_HDFS_BLOCK_ID_RE = re.compile(r"blk_-?\d+")
_RAW_CHAR_CAP = 500
_TIMESTAMP_FORMAT = "%d%m%y %H%M%S"


def collect_hdfs_block_source_lines(
    text: str,
    block_ids: set[str],
) -> dict[str, list[HdfsSourceLine]]:
    """Return scoring-order source lines for the requested HDFS block IDs.

    Sequence identity matches the frozen parser: the first ``blk_`` token on a
    line owns that line. Lines are ordered by parsed HDFS timestamp, then by
    original line number. Missing timestamps sort after dated lines.
    """

    if not block_ids:
        return {}
    buckets: dict[str, list[tuple[datetime | None, int, str]]] = {
        block_id: [] for block_id in block_ids
    }
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip("\r")
        if not line:
            continue
        match = _HDFS_BLOCK_ID_RE.search(line)
        if match is None:
            continue
        block_id = match.group(0)
        collected = buckets.get(block_id)
        if collected is None:
            continue
        collected.append((_hdfs_timestamp(line), line_number, line[:_RAW_CHAR_CAP]))
    return {
        block_id: [
            HdfsSourceLine(line_number=line_number, raw=raw)
            for _timestamp, line_number, raw in sorted(
                rows,
                key=lambda item: (item[0] is None, item[0] or datetime.min, item[1]),
            )
        ]
        for block_id, rows in buckets.items()
    }


def _hdfs_timestamp(line: str) -> datetime | None:
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(f"{parts[0]} {parts[1]}", _TIMESTAMP_FORMAT)
    except ValueError:
        return None
