export function LoadingScreen(): JSX.Element {
  return (
    <div className="loading-screen" aria-live="polite">
      <div className="brand">
        <span className="brand-mark">L</span>
        <span>logscope</span>
      </div>
      <span className="loading-dot" />
      Restoring your session…
    </div>
  );
}
