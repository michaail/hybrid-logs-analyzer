export function Banner({
  message,
  onDismiss,
  tone,
}: {
  message: string;
  onDismiss?: () => void;
  tone: "error" | "success";
}): JSX.Element {
  return (
    <div className={`banner ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span>{message}</span>
      {onDismiss && (
        <button aria-label="Dismiss message" className="icon-button" type="button" onClick={onDismiss}>
          ×
        </button>
      )}
    </div>
  );
}
