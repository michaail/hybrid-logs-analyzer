import { FormEvent, useEffect, useRef, useState } from "react";

import { AnalysisResults, ApiError, ProvisionalResults, ResultSort } from "../../api";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { StatusBadge } from "../../components/StatusBadge";
import { SummaryMetric } from "../../components/SummaryMetric";
import { messageFor } from "../../lib/errors";
import { fileNameFromReference, formatDateTime } from "../../lib/format";
import { api } from "../../session";
import {
  RESULTS_PAGE_SIZE,
  formatInspectedNumber,
  parseFiniteScore,
  resultInspectionMessage,
} from "./inspection";
import { ProvisionalHistoryCard } from "./ProvisionalHistoryCard";
import { ResultPagination } from "./ResultPagination";
import { SourceEvidence } from "./SourceEvidence";

export function ResultsDialog({
  projectId,
  runId,
  onClose,
  onUnauthorized,
}: {
  projectId: string;
  runId: string;
  onClose: () => void;
  onUnauthorized: (error: unknown) => void;
}): JSX.Element {
  const [sort, setSort] = useState<ResultSort>("score_desc");
  const [draftPrefix, setDraftPrefix] = useState("");
  const [draftMinScore, setDraftMinScore] = useState("");
  const [appliedPrefix, setAppliedPrefix] = useState<string | null>(null);
  const [appliedMinScore, setAppliedMinScore] = useState<number | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [previousCursors, setPreviousCursors] = useState<Array<string | null>>([]);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [panel, setPanel] = useState<"anomalies" | "provisional">("anomalies");
  const [provisionalDraftPrefix, setProvisionalDraftPrefix] = useState("");
  const [provisionalAppliedPrefix, setProvisionalAppliedPrefix] = useState<string | null>(null);
  const [provisionalCursor, setProvisionalCursor] = useState<string | null>(null);
  const [provisionalPreviousCursors, setProvisionalPreviousCursors] = useState<Array<string | null>>(
    [],
  );
  const [provisionalResults, setProvisionalResults] = useState<ProvisionalResults | null>(null);
  const [provisionalError, setProvisionalError] = useState<string | null>(null);
  const [provisionalFilterError, setProvisionalFilterError] = useState<string | null>(null);
  const [isProvisionalLoading, setIsProvisionalLoading] = useState(false);
  const onUnauthorizedRef = useRef(onUnauthorized);
  onUnauthorizedRef.current = onUnauthorized;

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    void api
      .getAnalysisResults(projectId, runId, {
        limit: RESULTS_PAGE_SIZE,
        sort,
        block_id_prefix: appliedPrefix,
        min_score: appliedMinScore,
        cursor,
      })
      .then((page) => {
        if (!cancelled) {
          setResults(page);
        }
      })
      .catch((requestError: unknown) => {
        if (cancelled) {
          return;
        }
        if (requestError instanceof ApiError && requestError.status === 401) {
          onUnauthorizedRef.current(requestError);
          return;
        }
        setError(messageFor(requestError));
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [appliedMinScore, appliedPrefix, cursor, projectId, runId, sort]);

  useEffect(() => {
    if (panel !== "provisional") {
      return;
    }
    let cancelled = false;
    setIsProvisionalLoading(true);
    setProvisionalError(null);

    void api
      .getProvisionalResults(projectId, runId, {
        limit: RESULTS_PAGE_SIZE,
        block_id_prefix: provisionalAppliedPrefix,
        cursor: provisionalCursor,
      })
      .then((page) => {
        if (!cancelled) {
          setProvisionalResults(page);
        }
      })
      .catch((requestError: unknown) => {
        if (cancelled) {
          return;
        }
        if (requestError instanceof ApiError && requestError.status === 401) {
          onUnauthorizedRef.current(requestError);
          return;
        }
        setProvisionalError(messageFor(requestError));
      })
      .finally(() => {
        if (!cancelled) {
          setIsProvisionalLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [panel, projectId, provisionalAppliedPrefix, provisionalCursor, runId]);

  function resetPaging(): void {
    setCursor(null);
    setPreviousCursors([]);
  }

  function changeSort(nextSort: ResultSort): void {
    setSort(nextSort);
    resetPaging();
  }

  function applyFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const parsedScore = parseFiniteScore(draftMinScore);
    if (!parsedScore.ok) {
      setFilterError(parsedScore.error);
      return;
    }
    const prefix = draftPrefix.trim();
    setFilterError(null);
    setAppliedPrefix(prefix.length > 0 ? prefix : null);
    setAppliedMinScore(parsedScore.value);
    resetPaging();
  }

  function resetFilters(): void {
    setDraftPrefix("");
    setDraftMinScore("");
    setFilterError(null);
    setSort("score_desc");
    setAppliedPrefix(null);
    setAppliedMinScore(null);
    resetPaging();
  }

  function goPrevious(): void {
    if (isLoading || previousCursors.length === 0) {
      return;
    }
    const previous = previousCursors[previousCursors.length - 1] ?? null;
    setIsLoading(true);
    setPreviousCursors((history) => history.slice(0, -1));
    setCursor(previous);
  }

  function goNext(): void {
    if (isLoading || !results?.next_cursor) {
      return;
    }
    setIsLoading(true);
    setPreviousCursors((history) => [...history, cursor]);
    setCursor(results.next_cursor);
  }

  function resetProvisionalPaging(): void {
    setProvisionalCursor(null);
    setProvisionalPreviousCursors([]);
  }

  function applyProvisionalFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const prefix = provisionalDraftPrefix.trim();
    setProvisionalFilterError(null);
    setProvisionalAppliedPrefix(prefix.length > 0 ? prefix : null);
    resetProvisionalPaging();
  }

  function resetProvisionalFilters(): void {
    setProvisionalDraftPrefix("");
    setProvisionalFilterError(null);
    setProvisionalAppliedPrefix(null);
    resetProvisionalPaging();
  }

  function goProvisionalPrevious(): void {
    if (isProvisionalLoading || provisionalPreviousCursors.length === 0) {
      return;
    }
    const previous = provisionalPreviousCursors[provisionalPreviousCursors.length - 1] ?? null;
    setIsProvisionalLoading(true);
    setProvisionalPreviousCursors((history) => history.slice(0, -1));
    setProvisionalCursor(previous);
  }

  function goProvisionalNext(): void {
    if (isProvisionalLoading || !provisionalResults?.next_cursor) {
      return;
    }
    setIsProvisionalLoading(true);
    setProvisionalPreviousCursors((history) => [...history, provisionalCursor]);
    setProvisionalCursor(provisionalResults.next_cursor);
  }

  const run = results?.run;
  const summary = results?.summary;
  const trace = results?.trace;
  const filtersActive = appliedPrefix !== null || appliedMinScore !== null;
  const showInspectionControls =
    run?.status === "completed" && summary !== undefined && summary.anomaly_count > 0;
  const inspectionMessage = results
    ? resultInspectionMessage(results.run, results.summary, results.anomalies.length, filtersActive)
    : null;
  const validationExamples = run?.validation_report?.examples ?? [];
  const busy = isLoading || (panel === "provisional" && isProvisionalLoading);

  return (
    <Dialog className="dialog-wide" title="Analysis outcome" onClose={onClose}>
      <div aria-busy={busy} className="results-dialog">
        {error && <Banner tone="error" message={error} onDismiss={() => setError(null)} />}
        {provisionalError && (
          <Banner tone="error" message={provisionalError} onDismiss={() => setProvisionalError(null)} />
        )}
        {isLoading && !results && <p className="muted">Loading analysis results…</p>}
        {isLoading && results && (
          <p aria-live="polite" className="muted">
            Updating this page of results…
          </p>
        )}
        {panel === "provisional" && isProvisionalLoading && (
          <p aria-live="polite" className="muted">
            {provisionalResults ? "Updating provisional histories…" : "Loading provisional histories…"}
          </p>
        )}

        {run && trace && summary && (
          <>
            <div className="results-header">
              <div>
                <span className="summary-label">HDFS analysis run</span>
                <h3>
                  {fileNameFromReference(run.log_reference)} · {formatDateTime(run.created_at)}
                </h3>
              </div>
              <StatusBadge status={run.status} />
            </div>

            <dl className="results-identity">
              <div>
                <dt>Model</dt>
                <dd>{trace.model_identifier}</dd>
              </div>
              <div>
                <dt>Model version</dt>
                <dd>{trace.version}</dd>
              </div>
            </dl>

            <details className="results-disclosure">
              <summary>More provenance</summary>
              <dl className="results-provenance">
                <div>
                  <dt>Analysis run ID</dt>
                  <dd className="technical-id">{run.id}</dd>
                </div>
                <div>
                  <dt>Model version ID</dt>
                  <dd className="technical-id">{trace.model_version_id}</dd>
                </div>
                <div>
                  <dt>Pipeline run</dt>
                  <dd className="technical-id">{trace.pipeline_run_id}</dd>
                </div>
                <div>
                  <dt>Dataset checksum</dt>
                  <dd className="technical-id">{trace.dataset_checksum ?? "unavailable"}</dd>
                </div>
                <div>
                  <dt>Model artifact checksum</dt>
                  <dd className="technical-id">{trace.artifact_checksum ?? "unavailable"}</dd>
                </div>
                {trace.preprocessing_bundle ? (
                  <>
                    <div>
                      <dt>Bundle identifier</dt>
                      <dd className="technical-id">{trace.preprocessing_bundle.identifier}</dd>
                    </div>
                    <div>
                      <dt>Bundle version</dt>
                      <dd>{trace.preprocessing_bundle.version}</dd>
                    </div>
                    <div>
                      <dt>Bundle digest</dt>
                      <dd className="technical-id">{trace.preprocessing_bundle.digest}</dd>
                    </div>
                  </>
                ) : (
                  <div>
                    <dt>Preprocessing bundle</dt>
                    <dd>Not attached</dd>
                  </div>
                )}
                {trace.classification_policy && (
                  <div>
                    <dt>Classification policy</dt>
                    <dd className="technical-id">{trace.classification_policy}</dd>
                  </div>
                )}
                {trace.classification_catalog_sha256 && (
                  <div>
                    <dt>Reference catalog digest</dt>
                    <dd className="technical-id">{trace.classification_catalog_sha256}</dd>
                  </div>
                )}
              </dl>
            </details>

            {inspectionMessage && (
              <p className={`results-state results-state-${inspectionMessage.tone}`}>
                {inspectionMessage.text}
              </p>
            )}
            {run.validation_report?.execution && (
              <div className="warning-strip">{run.validation_report.execution}</div>
            )}
            {run.error_code && <p className="error-code">Error code: {run.error_code}</p>}

            <div className="outcome-summary">
              <SummaryMetric label="Heuristically final anomalies" value={summary.anomaly_count} />
              <SummaryMetric label="Heuristically final normal" value={summary.normal_count} />
              <SummaryMetric label="Provisional histories" value={summary.provisional_count} />
              <SummaryMetric label="Unassigned context lines" value={summary.unassigned_context_line_count} />
              <SummaryMetric label="Rejected records" value={summary.rejected_records} />
              <SummaryMetric label="Invalid records" value={summary.invalid_records} />
            </div>
            <p className="results-summary-note">
              These totals cover the entire run, not the current page or filters. Rejected and
              invalid counts stay at zero for admitted HDFS runs; invalid uploads are rejected at
              dataset admission and never become analysis results.
            </p>
            <div className="info-strip">
              <strong>Heuristic outcomes</strong>
              <span>
                Heuristically final outcomes are based on membership in the pinned reference
                catalog. Catalog membership is not proof that the source HDFS lifecycle ended.
              </span>
            </div>

            {validationExamples.length > 0 && (
              <div className="validation-examples">
                <h4>Validation details</h4>
                <ul>
                  {validationExamples.map((example, index) => (
                    <li key={`${example.line_number ?? 0}-${index}`}>
                      Line {example.line_number ?? "unavailable"}: {example.reason ?? "Invalid record"}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {summary.provisional_count > 0 && (
              <div className="results-panel-switch">
                <button
                  className={panel === "anomalies" ? "selected-button" : "secondary-button"}
                  onClick={() => setPanel("anomalies")}
                  type="button"
                >
                  Heuristically final anomalies
                </button>
                <button
                  className={panel === "provisional" ? "selected-button" : "secondary-button"}
                  onClick={() => setPanel("provisional")}
                  type="button"
                >
                  Review {summary.provisional_count} provisional histories
                </button>
              </div>
            )}

            {panel === "anomalies" && showInspectionControls && results && (
              <form className="results-filters" onSubmit={(event) => applyFilters(event)}>
                {filterError && <Banner tone="error" message={filterError} />}
                <label htmlFor="results-sort">
                  Order
                  <select
                    disabled={isLoading}
                    id="results-sort"
                    onChange={(event) => changeSort(event.target.value as ResultSort)}
                    value={sort}
                  >
                    <option value="score_desc">Score (highest first)</option>
                    <option value="block_id_asc">Block ID (A–Z)</option>
                  </select>
                </label>
                <label htmlFor="results-block-prefix">
                  Block ID prefix
                  <input
                    disabled={isLoading}
                    id="results-block-prefix"
                    onChange={(event) => setDraftPrefix(event.target.value)}
                    placeholder="e.g. blk_"
                    value={draftPrefix}
                  />
                </label>
                <label htmlFor="results-min-score">
                  Minimum score
                  <input
                    disabled={isLoading}
                    id="results-min-score"
                    inputMode="decimal"
                    onChange={(event) => setDraftMinScore(event.target.value)}
                    placeholder="Leave blank for no minimum"
                    value={draftMinScore}
                  />
                </label>
                <div className="results-filter-actions">
                  <button className="secondary-button" disabled={isLoading} type="submit">
                    Apply filters
                  </button>
                  <button className="text-button" disabled={isLoading} onClick={resetFilters} type="button">
                    Reset
                  </button>
                </div>
              </form>
            )}

            {panel === "anomalies" && showInspectionControls && results && (
              <ResultPagination
                hasNext={results.next_cursor !== null}
                hasPrevious={previousCursors.length > 0}
                isLoading={isLoading}
                itemCount={results.anomalies.length}
                itemLabel="HDFS blocks"
                onNext={goNext}
                onPrevious={goPrevious}
                page={previousCursors.length + 1}
              />
            )}

            {panel === "anomalies" && results.anomalies.length > 0 && (
              <div className="anomaly-list">
                <h4>Heuristically final anomalies</h4>
                {results.anomalies.map((anomaly) => (
                  <article className="anomaly-card" key={anomaly.block_id}>
                    <div className="anomaly-heading">
                      <span className="summary-label">HDFS block</span>
                      <strong className="technical-id">{anomaly.block_id}</strong>
                    </div>
                    <p>
                      Score {formatInspectedNumber(anomaly.anomaly_score)} · threshold{" "}
                      {formatInspectedNumber(anomaly.decision_threshold)}
                      {anomaly.anomaly_level ? ` · ${anomaly.anomaly_level}` : ""}
                    </p>
                    <SourceEvidence context={anomaly.context} kind="scored" />
                  </article>
                ))}
              </div>
            )}

            {panel === "anomalies" && showInspectionControls && results && (
              <ResultPagination
                hasNext={results.next_cursor !== null}
                hasPrevious={previousCursors.length > 0}
                isLoading={isLoading}
                itemCount={results.anomalies.length}
                itemLabel="HDFS blocks"
                onNext={goNext}
                onPrevious={goPrevious}
                page={previousCursors.length + 1}
              />
            )}

            {panel === "provisional" && (
              <>
                <form className="results-filters results-filters-provisional" onSubmit={applyProvisionalFilters}>
                  {provisionalFilterError && <Banner tone="error" message={provisionalFilterError} />}
                  <label htmlFor="provisional-block-prefix">
                    Block ID prefix
                    <input
                      disabled={isProvisionalLoading}
                      id="provisional-block-prefix"
                      onChange={(event) => setProvisionalDraftPrefix(event.target.value)}
                      placeholder="e.g. blk_"
                      value={provisionalDraftPrefix}
                    />
                  </label>
                  <div className="results-filter-actions">
                    <button className="secondary-button" disabled={isProvisionalLoading} type="submit">
                      Apply filter
                    </button>
                    <button
                      className="text-button"
                      disabled={isProvisionalLoading}
                      onClick={resetProvisionalFilters}
                      type="button"
                    >
                      Reset
                    </button>
                  </div>
                </form>
                {provisionalResults && (
                  <ResultPagination
                    hasNext={provisionalResults.next_cursor !== null}
                    hasPrevious={provisionalPreviousCursors.length > 0}
                    isLoading={isProvisionalLoading}
                    itemCount={provisionalResults.items.length}
                    itemLabel="provisional histories"
                    onNext={goProvisionalNext}
                    onPrevious={goProvisionalPrevious}
                    page={provisionalPreviousCursors.length + 1}
                  />
                )}
                {provisionalResults && provisionalResults.items.length > 0 && (
                  <div className="anomaly-list">
                    <h4>Provisional histories</h4>
                    {provisionalResults.items.map((item) => (
                      <ProvisionalHistoryCard key={item.block_id} item={item} />
                    ))}
                  </div>
                )}
                {provisionalResults && (
                  <ResultPagination
                    hasNext={provisionalResults.next_cursor !== null}
                    hasPrevious={provisionalPreviousCursors.length > 0}
                    isLoading={isProvisionalLoading}
                    itemCount={provisionalResults.items.length}
                    itemLabel="provisional histories"
                    onNext={goProvisionalNext}
                    onPrevious={goProvisionalPrevious}
                    page={provisionalPreviousCursors.length + 1}
                  />
                )}
              </>
            )}
          </>
        )}

        <div className="dialog-actions">
          <button className="primary-button" type="button" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </Dialog>
  );
}
