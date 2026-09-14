export function ResultPagination({
  hasNext,
  hasPrevious,
  isLoading,
  itemCount,
  itemLabel,
  onNext,
  onPrevious,
  page,
}: {
  hasNext: boolean;
  hasPrevious: boolean;
  isLoading: boolean;
  itemCount: number;
  itemLabel: string;
  onNext: () => void;
  onPrevious: () => void;
  page: number;
}): JSX.Element {
  return (
    <div className="results-pagination">
      <button className="secondary-button" disabled={isLoading || !hasPrevious} onClick={onPrevious} type="button">
        Previous page
      </button>
      <p>
        Page {page}
        {hasNext ? "" : ", last page"}
        {` · ${itemCount} ${itemLabel} on this page`}
      </p>
      <button className="secondary-button" disabled={isLoading || !hasNext} onClick={onNext} type="button">
        Next page
      </button>
    </div>
  );
}
