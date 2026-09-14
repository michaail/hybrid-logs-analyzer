import { ReactNode } from "react";

export function Dialog({
  children,
  className,
  onClose,
  title,
}: {
  children: ReactNode;
  className?: string;
  onClose: () => void;
  title: string;
}): JSX.Element {
  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        aria-labelledby="dialog-title"
        aria-modal="true"
        className={className ? `dialog ${className}` : "dialog"}
        role="dialog"
      >
        <div className="dialog-heading">
          <h2 id="dialog-title">{title}</h2>
          <button aria-label="Close dialog" className="icon-button" type="button" onClick={onClose}>
            ×
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
