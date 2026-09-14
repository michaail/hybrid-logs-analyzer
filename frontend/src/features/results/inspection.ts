import { AnalysisResults, AnalysisRun, HdfsAnomalyContext, HdfsProvisionalContext } from "../../api";
import { formatMetric } from "../../lib/format";

export const RESULTS_PAGE_SIZE = 20;

export function parseFiniteScore(
  value: string,
): { ok: true; value: number | null } | { ok: false; error: string } {
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    return { ok: true, value: null };
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) {
    return { ok: false, error: "Minimum score must be a finite number." };
  }
  return { ok: true, value: parsed };
}

export function formatInspectedNumber(value: number | null): string {
  if (value === null) {
    return "unavailable";
  }
  return formatMetric(value);
}

export function sourceEvidenceLabel(
  context: HdfsAnomalyContext | HdfsProvisionalContext,
  kind: "scored" | "source" = "scored",
): string {
  const shown = context.source_lines.length;
  const matched = context.matched_line_count;
  const lineKind = kind === "scored" ? "scored log lines" : "source log lines";
  if (shown === 0 && matched === 0) {
    return "Source evidence — no stored source lines";
  }
  if (shown >= matched && matched > 0) {
    return `Source evidence — ${shown} ${lineKind}`;
  }
  return `Source evidence — showing ${shown} of ${matched} ${lineKind}`;
}

export function resultInspectionMessage(
  run: AnalysisRun,
  summary: AnalysisResults["summary"],
  pageSize: number,
  filtered: boolean,
): { tone: "progress" | "failed" | "empty"; text: string } | null {
  if (run.status === "queued" || run.status === "running") {
    return {
      tone: "progress",
      text: "This run is still in progress. Block-level anomalies and final counts appear when analysis completes.",
    };
  }
  if (run.status === "failed") {
    return {
      tone: "failed",
      text: "This analysis failed. The stored execution report is shown below; it is not a list of scored HDFS blocks.",
    };
  }
  if (run.status === "rejected" || run.status === "not_supported") {
    return {
      tone: "failed",
      text: `This run ended as ${run.status.split("_").join(" ")} and has no scored HDFS block anomalies.`,
    };
  }
  if (run.status === "completed" && summary.anomaly_count === 0) {
    if (summary.provisional_count > 0 || summary.unassigned_context_line_count > 0) {
      return {
        tone: "empty",
        text:
          "Analysis completed. Heuristically final anomaly and normal counts are zero. Review provisional histories and unassigned context below; this run is not a failure.",
      };
    }
    return {
      tone: "empty",
      text: "Analysis completed with no detected HDFS block anomalies. The totals below still cover the whole run.",
    };
  }
  if (run.status === "completed" && pageSize === 0) {
    return {
      tone: "empty",
      text: filtered
        ? "No HDFS blocks on this page match the current filters. Run totals stay the same."
        : "No HDFS block anomalies are on this page.",
    };
  }
  return null;
}
