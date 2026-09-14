import { FormEvent, useState } from "react";

import { Dataset, ModelVersion } from "../../api";
import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { messageFor } from "../../lib/errors";
import { datasetOptionLabel } from "../../lib/format";

export function AnalysisDialog({
  projectName,
  selectedModel,
  datasets,
  onClose,
  onStart,
}: {
  projectName: string;
  selectedModel: ModelVersion | null;
  datasets: Dataset[];
  onClose: () => void;
  onStart: (datasetId: string) => Promise<void>;
}): JSX.Element {
  const newestDataset = datasets[datasets.length - 1];
  const [datasetId, setDatasetId] = useState(newestDataset?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const canStart = Boolean(selectedModel) && datasets.length > 0 && datasetId.length > 0;

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!canStart) {
      setError("Upload an accepted HDFS dataset before starting analysis.");
      return;
    }
    setError(null);
    setIsSubmitting(true);
    try {
      await onStart(datasetId);
      onClose();
    } catch (submissionError) {
      setError(messageFor(submissionError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog title="Start HDFS analysis" onClose={onClose}>
      <form className="dialog-form" onSubmit={(event) => void submit(event)}>
        <div className="analysis-model-summary">
          <span>Project</span>
          <strong>{projectName}</strong>
          <span>Model</span>
          <strong>
            {selectedModel?.model_identifier} {selectedModel && `· ${selectedModel.version}`}
          </strong>
        </div>
        <p className="muted">
          A valid request is accepted as <code>queued</code>. In-progress runs refresh every five
          seconds until they complete or fail. Failed runs show a safe execution report and error
          code. Invalid HDFS datasets are rejected at upload and never appear in this list.
        </p>
        {error && <Banner tone="error" message={error} />}
        <label htmlFor="analysis-dataset">
          Accepted HDFS dataset
          <select
            disabled={datasets.length === 0}
            id="analysis-dataset"
            onChange={(event) => setDatasetId(event.target.value)}
            required={datasets.length > 0}
            value={datasetId}
          >
            {datasets.length === 0 ? (
              <option value="">No accepted datasets yet</option>
            ) : (
              datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {datasetOptionLabel(dataset)}
                </option>
              ))
            )}
          </select>
        </label>
        <div className="dialog-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-button" disabled={isSubmitting || !canStart} type="submit">
            {isSubmitting ? "Submitting…" : "Start analysis"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
