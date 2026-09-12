"""Unit tests for HDFS block evidence reconstruction."""

from __future__ import annotations

from src.api.hdfs_evidence import collect_hdfs_block_source_lines


def test_collect_hdfs_block_source_lines_uses_first_block_id_and_timestamp_order() -> None:
    text = "\n".join(
        [
            "081109 203620 150 INFO dfs.DataNode$DataXceiver: Receiving block blk_10 src: /10.0.0.1",
            "081109 203615 148 INFO dfs.DataNode$DataXceiver: copy blk_10 linked to blk_20",
            "081109 203616 149 INFO dfs.DataNode$DataXceiver: Receiving block blk_20 src: /10.0.0.2",
            "",
            "not a log line",
        ]
    )
    collected = collect_hdfs_block_source_lines(text, {"blk_10", "blk_missing"})
    keep = collected["blk_10"]
    assert [line.line_number for line in keep] == [2, 1]
    assert keep[0].raw.startswith("081109 203615")
    assert keep[1].raw.startswith("081109 203620")
    assert collected["blk_missing"] == []
    assert "blk_20" not in collected
