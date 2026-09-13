// reject-ineligible-hdfs-model.spec.ts
// Risk: an ineligible package becomes listed or publishable from the browser
// workflow (PRD US-01 rejection / test-plan risk #3).

import { expect, test } from "./fixtures";
import { ineligiblePackage, modelArticle, openPublisherWorkspace, registerPackage } from "./helpers/publication";

test("ineligible HDFS package is rejected and cannot be published", async ({ page }) => {
  const pkg = ineligiblePackage();
  await openPublisherWorkspace(page);

  const response = await registerPackage(page, pkg.zipPath);
  expect(response.status()).toBe(422);

  const dialog = page.getByRole("dialog", { name: "Register trained model" });
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(dialog.getByRole("alert")).toContainText(/evidence/i);
  await expect(dialog.getByRole("button", { name: "Register model" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Publish version" })).toHaveCount(0);

  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);

  await expect(modelArticle(page, pkg.identifier, pkg.version)).toHaveCount(0);
  await expect(page.getByText(pkg.identifier, { exact: true })).toHaveCount(0);
});
