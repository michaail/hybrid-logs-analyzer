import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, ModelVersion } from "./api";
import {
  ModelRegistrationDialog,
  PublishModelHarness,
  publishedStatusMessage,
  registeredStatusMessage,
} from "./App";

const ROLE_DENIED = "Insufficient project role.";

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

function roleDeniedError(): ApiError {
  return new ApiError(ROLE_DENIED, 403);
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
    fireEvent.change(screen.getByLabelText(/HDFS model package ZIP/i), {
      target: { files: [packageFile] },
    });
    const registerButton = screen.getByRole("button", { name: "Register model" });
    expect((registerButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.submit(registerButton.closest("form") as HTMLFormElement);

    expect(registerModel).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole("alert")).textContent).toContain(ROLE_DENIED);
    expect(screen.queryByRole("status")).toBeNull();
    expect(
      screen.queryByText(
        registeredStatusMessage({ model_identifier: "hdfs-detector", version: "1.0.0" }),
      ),
    ).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
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
