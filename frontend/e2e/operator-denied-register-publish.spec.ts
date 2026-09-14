// operator-denied-register-publish.spec.ts
// Risk: the UI shows Register/Publish as successful when the API denies an
// Operator (test-plan risk #6). Banner-only oracle; pytest remains the no-row
// / still-eligible check. Seeded from seed.spec.ts locators. Same-project
// Operator token — not project-b-user (that actor is 404 on project A).

import { expect, test } from "./fixtures";
import {
  modelArticle,
  openPublisherWorkspace,
  operatorPublishSeedPackage,
  operatorRegisterPackage,
  registerEligibleViaPublisherApi,
  registerPackage,
} from "./helpers/publication";

const ROLE_DENIED = "Insufficient project role.";

test.describe("operator role-deny banners", () => {
  test.use({ role: "operator" });

  test("operator register 403 shows dialog alert and no success status", async ({ page }) => {
    const pkg = operatorRegisterPackage();
    await openPublisherWorkspace(page);

    const response = await registerPackage(page, pkg.zipPath);
    expect(response.status()).toBe(403);

    const dialog = page.getByRole("dialog", { name: "Register trained model" });
    await expect(dialog.getByRole("alert")).toContainText(ROLE_DENIED);
    await expect(dialog.getByRole("button", { name: "Register model" })).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: "was registered as eligible" }),
    ).toHaveCount(0);
  });

  test("operator publish 403 shows page alert and no success status", async ({ page, request }) => {
    const pkg = operatorPublishSeedPackage();
    await registerEligibleViaPublisherApi(request, pkg.zipPath);
    await openPublisherWorkspace(page);

    const article = modelArticle(page, pkg.identifier, pkg.version);
    await expect(article.getByRole("button", { name: "Publish version" })).toBeVisible();

    const pendingPublish = page.waitForResponse((response) => {
      return (
        response.request().method() === "POST" &&
        /\/projects\/[^/]+\/models\/[^/]+\/publish$/.test(new URL(response.url()).pathname)
      );
    });
    await article.getByRole("button", { name: "Publish version" }).click();
    expect((await pendingPublish).status()).toBe(403);

    await expect(page.getByRole("alert")).toContainText(ROLE_DENIED);
    await expect(
      page.getByRole("status").filter({ hasText: `${pkg.identifier} ${pkg.version} is now published.` }),
    ).toHaveCount(0);
  });
});
