import { FormEvent, useState } from "react";

import { Banner } from "../../components/Banner";
import { Dialog } from "../../components/Dialog";
import { messageFor } from "../../lib/errors";

export function ModelRegistrationDialog({
  projectName,
  onClose,
  onRegister,
}: {
  projectName: string;
  onClose: () => void;
  onRegister: (packageFile: File, preprocessingBundleFile: File) => Promise<void>;
}): JSX.Element {
  const [packageFile, setPackageFile] = useState<File | null>(null);
  const [preprocessingBundleFile, setPreprocessingBundleFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!packageFile) {
      setError("Choose a complete HDFS model package ZIP.");
      return;
    }
    if (!preprocessingBundleFile) {
      setError("Choose the companion preprocessing-bundle ZIP.");
      return;
    }
    setError(null);
    setIsSubmitting(true);
    try {
      await onRegister(packageFile, preprocessingBundleFile);
      onClose();
    } catch (submissionError) {
      setError(messageFor(submissionError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog title="Register trained model" onClose={onClose}>
      <form className="dialog-form" onSubmit={(event) => void submit(event)}>
        <p className="muted">
          Upload an <strong>attribute-aware-gae-v2</strong> package ZIP and its bound
          preprocessing-bundle ZIP for <strong>{projectName}</strong>. Identity, metrics, and
          evidence come from the package manifest at the ZIP root.
        </p>
        <div className="warning-strip">
          The API never deserializes uploaded artifacts in this process. Invalid packages are
          rejected with structured issues and are not registered.
        </div>
        {error && <Banner tone="error" message={error} />}
        <label className="file-field">
          HDFS model package ZIP
          <input
            accept=".zip,application/zip,application/x-zip-compressed"
            onChange={(event) => setPackageFile(event.target.files?.[0] ?? null)}
            required
            type="file"
          />
          <span className="file-field-name">
            {packageFile ? packageFile.name : "No ZIP selected"}
          </span>
        </label>
        <label className="file-field">
          Preprocessing-bundle ZIP
          <input
            accept=".zip,application/zip,application/x-zip-compressed"
            onChange={(event) => setPreprocessingBundleFile(event.target.files?.[0] ?? null)}
            required
            type="file"
          />
          <span className="file-field-name">
            {preprocessingBundleFile ? preprocessingBundleFile.name : "No bundle ZIP selected"}
          </span>
        </label>
        <div className="dialog-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="primary-button"
            disabled={isSubmitting || !packageFile || !preprocessingBundleFile}
            type="submit"
          >
            {isSubmitting ? "Registering…" : "Register model"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
