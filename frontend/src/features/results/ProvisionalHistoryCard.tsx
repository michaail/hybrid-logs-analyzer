import { HdfsProvisionalResult } from "../../api";
import { SourceEvidence } from "./SourceEvidence";

export function ProvisionalHistoryCard({ item }: { item: HdfsProvisionalResult }): JSX.Element {
  return (
    <article className="anomaly-card">
      <div className="anomaly-heading">
        <span className="summary-label">Provisional HDFS block</span>
        <strong className="technical-id">{item.block_id}</strong>
      </div>
      <p>
        {item.reason} <span className="technical-id">({item.reason_code})</span>
      </p>
      <SourceEvidence context={item.context} kind="source" />
    </article>
  );
}
