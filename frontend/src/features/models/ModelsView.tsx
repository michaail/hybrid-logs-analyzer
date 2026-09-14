import { useState } from "react";

import { ModelVersion } from "../../api";
import { Dialog } from "../../components/Dialog";
import { EmptyState } from "../../components/EmptyState";
import { MetricList } from "../../components/MetricList";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDate } from "../../lib/format";

export function ModelsView({
  models,
  selectedModelId,
  canManageModels,
  onPublish,
  onRegister,
  onRemove,
  onSelectModel,
}: {
  models: ModelVersion[];
  selectedModelId: string | null;
  canManageModels: boolean;
  onPublish: (model: ModelVersion) => Promise<void>;
  onRegister: () => void;
  onRemove: (model: ModelVersion) => Promise<void>;
  onSelectModel: (id: string) => void;
}): JSX.Element {
  const [pendingRemoval, setPendingRemoval] = useState<ModelVersion | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  async function confirmRemoval(): Promise<void> {
    if (!pendingRemoval) {
      return;
    }
    setIsRemoving(true);
    try {
      await onRemove(pendingRemoval);
      setPendingRemoval(null);
    } finally {
      setIsRemoving(false);
    }
  }

  return (
    <section className="content-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Model registry</p>
          <h2>Choose a model for analysis</h2>
          <p className="muted">
            Only published HDFS model versions can be selected. Inference-ready releases are bound
            to an immutable preprocessing bundle.
          </p>
        </div>
        {canManageModels && (
          <button className="primary-button" type="button" onClick={onRegister}>
            Register trained model
          </button>
        )}
      </div>

      {models.length === 0 ? (
        <EmptyState
          title="No model versions yet"
          description="A Publisher can upload a complete HDFS model package ZIP for this project."
        />
      ) : (
        <div className="model-grid">
          {models.map((model) => {
            const isSelected = selectedModelId === model.id;
            const isPublished = model.status === "published";
            return (
              <article
                aria-label={`${model.model_identifier} version ${model.version}`}
                className={`model-card ${isSelected ? "selected" : ""}`}
                key={model.id}
              >
                <div className="card-title-row">
                  <div>
                    <p className="model-name">{model.model_identifier}</p>
                    <p className="muted">Version {model.version}</p>
                    {model.status === "published" && (
                      <p className="muted">
                        {model.inference_ready ? "Ready for analysis" : "Not inference-ready"}
                      </p>
                    )}
                  </div>
                  <StatusBadge status={model.status} />
                </div>

                <dl className="metadata-list">
                  <div>
                    <dt>Source</dt>
                    <dd>HDFS</dd>
                  </div>
                  <div>
                    <dt>Pipeline run</dt>
                    <dd className="truncate">{model.pipeline_run_id}</dd>
                  </div>
                  <div>
                    <dt>Registered</dt>
                    <dd>{formatDate(model.created_at)}</dd>
                  </div>
                </dl>

                <MetricList metrics={model.metrics} />

                <div className="card-actions">
                  <button
                    className={isSelected ? "secondary-button selected-button" : "secondary-button"}
                    disabled={!isPublished}
                    type="button"
                    onClick={() => onSelectModel(model.id)}
                  >
                    {isSelected ? "Selected for analysis" : "Select model"}
                  </button>
                  {canManageModels && (
                    <div className="card-action-group">
                      {model.status === "eligible" && (
                        <button className="text-button" type="button" onClick={() => void onPublish(model)}>
                          Publish version
                        </button>
                      )}
                      <button
                        className="danger-button"
                        type="button"
                        onClick={() => setPendingRemoval(model)}
                      >
                        Remove
                      </button>
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {canManageModels && (
        <div className="info-strip">
          <strong>Trusted artifact boundary</strong>
          <span>
            This client uploads a complete HDFS model package ZIP. The API never deserializes
            artifacts in this process.
          </span>
        </div>
      )}

      {pendingRemoval && (
        <Dialog
          title="Remove model version"
          onClose={() => {
            if (!isRemoving) {
              setPendingRemoval(null);
            }
          }}
        >
          <div className="dialog-form">
            <p>
              Remove {pendingRemoval.model_identifier} version {pendingRemoval.version}? Analysis
              runs that referenced this version are kept.
            </p>
            <div className="dialog-actions">
              <button
                className="secondary-button"
                disabled={isRemoving}
                type="button"
                onClick={() => setPendingRemoval(null)}
              >
                Cancel
              </button>
              <button
                className="danger-button"
                disabled={isRemoving}
                type="button"
                onClick={() => void confirmRemoval()}
              >
                {isRemoving ? "Removing…" : "Remove model"}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </section>
  );
}
