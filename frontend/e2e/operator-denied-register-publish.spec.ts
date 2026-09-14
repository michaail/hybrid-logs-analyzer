// operator-denied-register-publish.spec.ts
// Risk: an Operator is offered Publisher model actions (test-plan risk #6).
// Banner-only 403 oracles remain in Vitest for when those actions are shown.
// pytest remains the HTTP no-row / still-eligible check. Same-project
// Operator token — not project-b-user (that actor is 404 on project A).

import { expect, test } from "./fixtures";
import {
  modelArticle,
  openWorkspace,
  operatorPublishSeedPackage,
  registerEligibleViaPublisherApi,
} from "./helpers/publication";

test.describe("operator model-action visibility", () => {
  test.use({ role: "operator" });

  test("operator does not see register or remove model actions", async ({ page }) => {
    await openWorkspace(page);

    await expect(page.getByRole("button", { name: "Register trained model" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Remove" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Publish version" })).toHaveCount(0);
  });

  test("operator does not see publish on an eligible same-project model", async ({
    page,
    request,
  }) => {
    const pkg = operatorPublishSeedPackage();
    await registerEligibleViaPublisherApi(request, pkg.zipPath, pkg.bundleZipPath);
    await openWorkspace(page);

    const article = modelArticle(page, pkg.identifier, pkg.version);
    await expect(article).toBeVisible();
    await expect(article.getByRole("button", { name: "Publish version" })).toHaveCount(0);
    await expect(article.getByRole("button", { name: "Remove" })).toHaveCount(0);
  });
});
