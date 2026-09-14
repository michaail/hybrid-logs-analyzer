import { AuditEvent } from "../../api";
import { formatDate } from "../../lib/format";

export function AuditPanel({
  title,
  description,
  emptyMessage,
  events,
}: {
  title: string;
  description: string;
  emptyMessage: string;
  events: AuditEvent[];
}): JSX.Element {
  return (
    <div className="audit-card">
      <div className="audit-heading">
        <div>
          <p className="eyebrow">Immutable history</p>
          <h3>{title}</h3>
          <p className="muted">{description}</p>
        </div>
        <span className="event-count">{events.length} events</span>
      </div>
      {events.length === 0 ? (
        <p className="muted">{emptyMessage}</p>
      ) : (
        <ol className="audit-list">
          {events.map((event) => (
            <li key={event.id}>
              <span className="audit-marker" />
              <div>
                <strong>{event.action}</strong>
                <p>
                  {event.resource_type}
                  {event.project_id ? " · project-scoped" : " · system"} · {formatDate(event.created_at)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
