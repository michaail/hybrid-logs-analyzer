import { HdfsAnomalyContext, HdfsProvisionalContext } from "../../api";
import { sourceEvidenceLabel } from "./inspection";

export function SourceEvidence({
  context,
  kind,
}: {
  context: HdfsAnomalyContext | HdfsProvisionalContext;
  kind: "scored" | "source";
}): JSX.Element {
  return (
    <details className="results-disclosure">
      <summary>{sourceEvidenceLabel(context, kind)}</summary>
      {context.source_lines.length === 0 ? (
        <p className="muted">No stored source lines are available for this block.</p>
      ) : (
        <ol className="source-line-list">
          {context.source_lines.map((line, index) => (
            <li key={`${line.line_number ?? "unavailable"}-${index}`}>
              <span className="source-line-number">Line {line.line_number ?? "unavailable"}</span>
              <pre className="source-line-raw">{line.raw}</pre>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}
