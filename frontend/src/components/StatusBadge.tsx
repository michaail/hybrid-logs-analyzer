export function StatusBadge({ status }: { status: string }): JSX.Element {
  return (
    <span className={`status-badge status-${status.split("_").join("-")}`}>
      {status.split("_").join(" ")}
    </span>
  );
}
