export function SummaryMetric({ label, value }: { label: string; value: number }): JSX.Element {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
