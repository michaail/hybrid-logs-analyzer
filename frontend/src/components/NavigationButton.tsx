export function NavigationButton({
  active,
  detail,
  label,
  onClick,
}: {
  active: boolean;
  detail?: string;
  label: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <button className={`navigation-button ${active ? "active" : ""}`} type="button" onClick={onClick}>
      <span>{label}</span>
      {detail && <small>{detail}</small>}
    </button>
  );
}
