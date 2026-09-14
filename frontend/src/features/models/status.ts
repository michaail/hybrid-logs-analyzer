import { ModelVersion } from "../../api";

export function publishedStatusMessage(
  model: Pick<ModelVersion, "model_identifier" | "version">,
): string {
  return `${model.model_identifier} ${model.version} is now published.`;
}

export function registeredStatusMessage(
  model: Pick<ModelVersion, "model_identifier" | "version">,
): string {
  return `${model.model_identifier} ${model.version} was registered as eligible.`;
}

export function deletedStatusMessage(
  model: Pick<ModelVersion, "model_identifier" | "version">,
): string {
  return `${model.model_identifier} ${model.version} was removed.`;
}

export async function publishModelWithStatus(
  publish: () => Promise<unknown>,
  model: Pick<ModelVersion, "model_identifier" | "version">,
): Promise<string> {
  await publish();
  return publishedStatusMessage(model);
}
