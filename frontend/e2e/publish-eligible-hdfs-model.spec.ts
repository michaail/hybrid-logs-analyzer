// publish-eligible-hdfs-model.spec.ts
// Risk: an eligible package can be registered without an explicit publish
// transition, or the UI can claim publication without the version becoming
// published (PRD US-01 / FR-004).

import { expect, test } from "./fixtures";
import { eligiblePackage, modelArticle, openPublisherWorkspace, registerPackage } from "./helpers/publication";

test("publisher can upload an eligible HDFS package and explicitly publish it", async ({ page }) => {
  const pkg = eligiblePackage();
  await openPublisherWorkspace(page);

  const registration = await registerPackage(page, pkg.zipPath);
  expect(registration.status()).toBe(201);
  await expect(
    page.getByRole("status").filter({
      hasText: `${pkg.identifier} ${pkg.version} was registered as eligible.`,
    }),
  ).toBeVisible();

  const article = modelArticle(page, pkg.identifier, pkg.version);
  await expect(article.getByText("eligible", { exact: true })).toBeVisible();

  const pendingPublish = page.waitForResponse((response) => {
    return (
      response.request().method() === "POST" &&
      /\/projects\/[^/]+\/models\/[^/]+\/publish$/.test(new URL(response.url()).pathname)
    );
  });
  await article.getByRole("button", { name: "Publish version" }).click();
  expect((await pendingPublish).status()).toBe(200);

  await expect(
    page.getByRole("status").filter({
      hasText: `${pkg.identifier} ${pkg.version} is now published.`,
    }),
  ).toBeVisible();
  await expect(article.getByText("published", { exact: true })).toBeVisible();
  await expect(article.getByRole("button", { name: "Publish version" })).toHaveCount(0);
  await expect(article.getByRole("button", { name: /Select model|Selected for analysis/ })).toBeEnabled();
});
