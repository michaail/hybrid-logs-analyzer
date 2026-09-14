import { FormEvent, useState } from "react";

import { ApiError, Dataset } from "../../api";
import { Banner } from "../../components/Banner";
import { messageFor } from "../../lib/errors";
import { shortId } from "../../lib/format";

export function DatasetPanel({
  datasets,
  onUpload,
  onUnauthorized,
}: {
  datasets: Dataset[];
  onUpload: (logFile: File) => Promise<void>;
  onUnauthorized: (error: unknown) => void;
}): JSX.Element {
  const [logFile, setLogFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!logFile) {
      setError("Choose a UTF-8 HDFS log file.");
      return;
    }
    setError(null);
    setIsUploading(true);
    try {
      await onUpload(logFile);
      setLogFile(null);
      setFileInputKey((current) => current + 1);
    } catch (uploadError) {
      if (uploadError instanceof ApiError && uploadError.status === 401) {
        onUnauthorized(uploadError);
        return;
      }
      setError(messageFor(uploadError));
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="dataset-panel">
      <h3 className="dataset-heading">Project datasets</h3>
      <p className="muted">
        Upload a UTF-8 HDFS log (at most 32 MiB). Invalid files return a validation report and
        never appear in this list.
      </p>
      <form className="dataset-upload" onSubmit={(event) => void submit(event)}>
        {error && <Banner tone="error" message={error} onDismiss={() => setError(null)} />}
        <label className="file-field">
          HDFS log file
          <input
            key={fileInputKey}
            onChange={(event) => setLogFile(event.target.files?.[0] ?? null)}
            required
            type="file"
          />
          <span className="file-field-name">{logFile ? logFile.name : "No log file selected"}</span>
        </label>
        <button className="secondary-button" disabled={isUploading || !logFile} type="submit">
          {isUploading ? "Uploading…" : "Upload dataset"}
        </button>
      </form>
      {datasets.length === 0 ? (
        <p className="muted">No reusable datasets are registered yet.</p>
      ) : (
        <div className="dataset-list">
          {datasets.map((dataset) => (
            <article className="dataset-card" key={dataset.id}>
              <div>
                <span className="summary-label">Dataset {shortId(dataset.id)}</span>
                <strong>{dataset.object_reference}</strong>
              </div>
              <dl className="metadata-list compact-metadata">
                <div>
                  <dt>Storage</dt>
                  <dd>{dataset.storage_kind}</dd>
                </div>
                <div>
                  <dt>Checksum</dt>
                  <dd className="truncate">{dataset.checksum ?? "none"}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
