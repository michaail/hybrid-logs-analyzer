export function EmptyState({ description, title }: { description: string; title: string }): JSX.Element {
  return (
    <div className="empty-state">
      <span className="empty-state-icon">⌁</span>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}
