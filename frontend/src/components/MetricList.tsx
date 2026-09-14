import { formatMetric, humanize } from "../lib/format";

export function MetricList({ metrics }: { metrics: Record<string, unknown> }): JSX.Element | null {
  const entries = Object.entries(metrics).slice(0, 3);
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="metric-list">
      {entries.map(([name, value]) => (
        <span key={name}>
          <small>{humanize(name)}</small>
          <strong>{formatMetric(value)}</strong>
        </span>
      ))}
    </div>
  );
}
