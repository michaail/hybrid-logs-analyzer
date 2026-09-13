// seed.spec.ts
// Risk: an eligible HDFS package can be uploaded in the browser and not appear as
// a project-owned eligible version (FR-003 / test-plan risk #3 admission half).
// Seed exemplar for later E2E tests: role locators, unique data, state waits,
// independent setup → action → assertion, suite-level isolated DB cleanup.

import { expect, test } from "./fixtures";
import { eligiblePackage, modelArticle, openPublisherWorkspace, registerPackage } from "./helpers/publication";

test("eligible HDFS package registration is listed under its unique identifier", async ({ page }) => {
  const pkg = eligiblePackage();
  await openPublisherWorkspace(page);

  const response = await registerPackage(page, pkg.zipPath);
  expect(response.status()).toBe(201);

  await expect(
    page.getByRole("status").filter({
      hasText: `${pkg.identifier} ${pkg.version} was registered as eligible.`,
    }),
  ).toBeVisible();

  const article = modelArticle(page, pkg.identifier, pkg.version);
  await expect(article).toBeVisible();
  await expect(article.getByText("eligible", { exact: true })).toBeVisible();
  await expect(article.getByRole("button", { name: "Publish version" })).toBeVisible();
});
