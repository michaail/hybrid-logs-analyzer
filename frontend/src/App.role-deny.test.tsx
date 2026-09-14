import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ApiError, Dataset, ModelVersion } from "./api";
import { Banner } from "./components/Banner";
import { ModelRegistrationDialog } from "./features/models/ModelRegistrationDialog";
import { ModelsView } from "./features/models/ModelsView";
import {
  deletedStatusMessage,
  publishedStatusMessage,
  publishModelWithStatus,
  registeredStatusMessage,
} from "./features/models/status";
import { DatasetPanel } from "./features/runs/DatasetPanel";
import { messageFor } from "./lib/errors";
import { shortId } from "./lib/format";

const ROLE_DENIED = "Insufficient project role.";
const MODEL_REFERENCED = "This model version is referenced by analysis runs.";
const DATASET_REFERENCED = "This dataset is referenced by analysis runs.";

function eligibleModel(): ModelVersion {
  return {
    id: "model-1",
    project_id: "project-a",
    model_identifier: "hdfs-detector",
    version: "1.0.0",
    source_compatibility: "hdfs",
    status: "eligible",
    pipeline_run_id: "run-1",
    artifact_reference: "models/hdfs-detector/1.0.0/artifact",
    package_reference: "models/hdfs-detector/1.0.0/package.zip",
    artifact_sha256: "abc",
    metrics: {},
    metadata: {},
    external_evaluation_evidence: "notebook",
    created_at: "2026-09-14T00:00:00Z",
    published_at: null,
    published_by_user_id: null,
    storage_kind: "object",
    checksum: null,
    inference_ready: false,
    preprocessing_bundle: null,
  };
}

function sampleDataset(): Dataset {
  return {
    id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    project_id: "project-a",
    storage_kind: "object",
    object_reference: "datasets/project-a/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/log",
    checksum: "abc",
    source_compatibility: "hdfs",
    created_at: "2026-09-14T00:00:00Z",
  };
}

function roleDeniedError(): ApiError {
  return new ApiError(ROLE_DENIED, 403);
}

function conflictError(detail: string): ApiError {
  return new ApiError(detail, 409);
}

function PublishModelHarness({
  model,
  publishModel,
}: {
  model: ModelVersion;
  publishModel: (model: ModelVersion) => Promise<void>;
}): JSX.Element {
  const [notice, setNotice] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  async function onPublish(target: ModelVersion): Promise<void> {
    setPageError(null);
    try {
      const status = await publishModelWithStatus(() => publishModel(target), target);
      setNotice(status);
    } catch (error) {
      setPageError(messageFor(error));
    }
  }

  return (
    <div>
      {notice ? <Banner tone="success" message={notice} onDismiss={() => setNotice(null)} /> : null}
      {pageError ? (
        <Banner tone="error" message={pageError} onDismiss={() => setPageError(null)} />
      ) : null}
      <ModelsView
        models={[model]}
        selectedModelId={null}
        canManageModels
        onPublish={onPublish}
        onRegister={() => undefined}
        onRemove={async () => undefined}
        onSelectModel={() => undefined}
      />
    </div>
  );
}

function RemoveModelHarness({
  model,
  deleteModel,
}: {
  model: ModelVersion;
  deleteModel: (model: ModelVersion) => Promise<void>;
}): JSX.Element {
  const [notice, setNotice] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  async function onRemove(target: ModelVersion): Promise<void> {
    setPageError(null);
    try {
      await deleteModel(target);
      setNotice(deletedStatusMessage(target));
    } catch (error) {
      setPageError(messageFor(error));
    }
  }

  return (
    <div>
      {notice ? <Banner tone="success" message={notice} onDismiss={() => setNotice(null)} /> : null}
      {pageError ? (
        <Banner tone="error" message={pageError} onDismiss={() => setPageError(null)} />
      ) : null}
      <ModelsView
        models={[model]}
        selectedModelId={null}
        canManageModels
        onPublish={async () => undefined}
        onRegister={() => undefined}
        onRemove={onRemove}
        onSelectModel={() => undefined}
      />
    </div>
  );
}

function RemoveDatasetHarness({
  dataset,
  deleteDataset,
}: {
  dataset: Dataset;
  deleteDataset: (dataset: Dataset) => Promise<void>;
}): JSX.Element {
  const [notice, setNotice] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  async function onRemove(target: Dataset): Promise<void> {
    setPageError(null);
    try {
      await deleteDataset(target);
      setNotice(`HDFS dataset ${shortId(target.id)} was removed.`);
    } catch (error) {
      setPageError(messageFor(error));
    }
  }

  return (
    <div>
      {notice ? <Banner tone="success" message={notice} onDismiss={() => setNotice(null)} /> : null}
      {pageError ? (
        <Banner tone="error" message={pageError} onDismiss={() => setPageError(null)} />
      ) : null}
      <DatasetPanel
        datasets={[dataset]}
        onUpload={async () => undefined}
        onRemove={onRemove}
        onUnauthorized={() => undefined}
      />
    </div>
  );
}

describe("Register and Publish role-deny copy", () => {
  it("shows a Register 403 alert and does not render success status", async () => {
    const registerModel = vi.fn().mockRejectedValue(roleDeniedError());
    const onClose = vi.fn();

    render(
      <ModelRegistrationDialog
        projectName="Project A"
        onClose={onClose}
        onRegister={registerModel}
      />,
    );

    const packageFile = new File(["package"], "hdfs-model.zip", { type: "application/zip" });
    const bundleFile = new File(["bundle"], "hdfs-bundle.zip", { type: "application/zip" });
    fireEvent.change(screen.getByLabelText(/HDFS model package ZIP/i), {
      target: { files: [packageFile] },
    });
    fireEvent.change(screen.getByLabelText(/Preprocessing-bundle ZIP/i), {
      target: { files: [bundleFile] },
    });
    const registerButton = screen.getByRole("button", { name: "Register model" });
    expect((registerButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.submit(registerButton.closest("form") as HTMLFormElement);

    expect(registerModel).toHaveBeenCalledTimes(1);
    expect(registerModel).toHaveBeenCalledWith(packageFile, bundleFile);
    expect((await screen.findByRole("alert")).textContent).toContain(ROLE_DENIED);
    expect(screen.queryByRole("status")).toBeNull();
    expect(
      screen.queryByText(
        registeredStatusMessage({ model_identifier: "hdfs-detector", version: "1.0.0" }),
      ),
    ).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("hides register, publish, and remove when the caller cannot manage models", () => {
    render(
      <ModelsView
        models={[eligibleModel()]}
        selectedModelId={null}
        canManageModels={false}
        onPublish={async () => undefined}
        onRegister={() => undefined}
        onRemove={async () => undefined}
        onSelectModel={() => undefined}
      />,
    );

    expect(screen.queryByRole("button", { name: "Register trained model" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Publish version" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.getByRole("button", { name: "Select model" })).toBeTruthy();
  });

  it("shows a Publish 403 alert and does not render success status", async () => {
    const user = userEvent.setup();
    const model = eligibleModel();
    const publishModel = vi.fn().mockRejectedValue(roleDeniedError());

    render(<PublishModelHarness model={model} publishModel={publishModel} />);

    await user.click(screen.getByRole("button", { name: "Publish version" }));

    expect(publishModel).toHaveBeenCalledTimes(1);
    expect(publishModel).toHaveBeenCalledWith(model);
    expect((await screen.findByRole("alert")).textContent).toContain(ROLE_DENIED);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText(publishedStatusMessage(model))).toBeNull();
  });
});

describe("Remove deny copy", () => {
  it("shows a model Remove 403 alert and keeps the action visible", async () => {
    const user = userEvent.setup();
    const model = eligibleModel();
    const deleteModel = vi.fn().mockRejectedValue(roleDeniedError());

    render(<RemoveModelHarness model={model} deleteModel={deleteModel} />);

    expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByRole("dialog").textContent).toContain(
      `${model.model_identifier} version ${model.version}`,
    );
    await user.click(screen.getByRole("button", { name: "Remove model" }));

    expect(deleteModel).toHaveBeenCalledTimes(1);
    expect(deleteModel).toHaveBeenCalledWith(model);
    expect((await screen.findByRole("alert")).textContent).toContain(ROLE_DENIED);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText(deletedStatusMessage(model))).toBeNull();
    expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();
  });

  it("shows a model Remove 409 alert and does not render success status", async () => {
    const user = userEvent.setup();
    const model = eligibleModel();
    const deleteModel = vi.fn().mockRejectedValue(conflictError(MODEL_REFERENCED));

    render(<RemoveModelHarness model={model} deleteModel={deleteModel} />);

    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove model" }));

    expect(deleteModel).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole("alert")).textContent).toContain(MODEL_REFERENCED);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText(deletedStatusMessage(model))).toBeNull();
    expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();
  });

  it("shows a dataset Remove 403 alert and keeps the action visible", async () => {
    const user = userEvent.setup();
    const dataset = sampleDataset();
    const deleteDataset = vi.fn().mockRejectedValue(roleDeniedError());

    render(<RemoveDatasetHarness dataset={dataset} deleteDataset={deleteDataset} />);

    expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByRole("dialog").textContent).toContain(shortId(dataset.id));
    await user.click(screen.getByRole("button", { name: "Remove dataset" }));

    expect(deleteDataset).toHaveBeenCalledTimes(1);
    expect(deleteDataset).toHaveBeenCalledWith(dataset);
    expect((await screen.findByRole("alert")).textContent).toContain(ROLE_DENIED);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText(`HDFS dataset ${shortId(dataset.id)} was removed.`)).toBeNull();
    expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();
  });

  it("shows a dataset Remove 409 alert and does not render success status", async () => {
    const user = userEvent.setup();
    const dataset = sampleDataset();
    const deleteDataset = vi.fn().mockRejectedValue(conflictError(DATASET_REFERENCED));

    render(<RemoveDatasetHarness dataset={dataset} deleteDataset={deleteDataset} />);

    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove dataset" }));

    expect(deleteDataset).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole("alert")).textContent).toContain(DATASET_REFERENCED);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText(`HDFS dataset ${shortId(dataset.id)} was removed.`)).toBeNull();
    expect(screen.getByRole("button", { name: "Remove" })).toBeTruthy();
  });
});
