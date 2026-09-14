import { AnalysisRun, Dataset, ModelVersion } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDate, shortId } from "../../lib/format";
import { DatasetPanel } from "./DatasetPanel";

export function RunsView({
  models,
  runs,
  datasets,
  selectedModel,
  onOpenAnalysis,
  onShowResults,
  onUploadDataset,
  onUnauthorized,
}: {
  models: ModelVersion[];
  runs: AnalysisRun[];
  datasets: Dataset[];
  selectedModel: ModelVersion | null;
  onOpenAnalysis: () => void;
  onShowResults: (run: AnalysisRun) => void;
  onUploadDataset: (logFile: File) => Promise<void>;
  onUnauthorized: (error: unknown) => void;
}): JSX.Element {
  return (
    <section className="content-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Analysis workspace</p>
          <h2>Validate an HDFS log dataset</h2>
          <p className="muted">
            {selectedModel
              ? `Using ${selectedModel.model_identifier} ${selectedModel.version}${
                  selectedModel.inference_ready ? "." : ". This published model is not inference-ready."
                }`
              : "Select a published model in the Models view before starting an analysis."}
          </p>
        </div>
        <button className="primary-button" disabled={!selectedModel} type="button" onClick={onOpenAnalysis}>
          Start analysis
        </button>
      </div>

      {selectedModel && (
        <div className="selection-summary">
          <div>
            <span className="summary-label">Selected model</span>
            <strong>
              {selectedModel.model_identifier} <span>·</span> {selectedModel.version}
            </strong>
          </div>
          <StatusBadge status={selectedModel.status} />
        </div>
      )}

      <DatasetPanel
        datasets={datasets}
        onUpload={onUploadDataset}
        onUnauthorized={onUnauthorized}
      />

      {runs.length === 0 ? (
        <EmptyState
          title="No analysis runs yet"
          description="Start with a published model and an accepted HDFS dataset from this project."
        />
      ) : (
        <div className="runs-list">
          {runs.map((run) => {
            const model = models.find((candidate) => candidate.id === run.model_version_id);
            return (
              <article className="run-card" key={run.id}>
                <div className="run-primary">
                  <div className="run-status-line">
                    <StatusBadge status={run.status} />
                    <span className="run-id">Run {shortId(run.id)}</span>
                  </div>
                  <strong>{run.log_reference}</strong>
                  {run.dataset_id && (
                    <span className="muted">Dataset {shortId(run.dataset_id)}</span>
                  )}
                  <span className="muted">
                    {model ? `${model.model_identifier} ${model.version}` : "Model version unavailable"} ·{" "}
                    {formatDate(run.created_at)}
                  </span>
                </div>
                <div className="run-outcome">
                  {run.error_code && <code>{run.error_code}</code>}
                  <button className="secondary-button" type="button" onClick={() => onShowResults(run)}>
                    View outcome
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {(runs.some((run) => run.status === "queued") || runs.some((run) => run.status === "running")) && (
        <p className="auto-refresh-note">In-progress runs refresh automatically every five seconds.</p>
      )}
    </section>
  );
}
