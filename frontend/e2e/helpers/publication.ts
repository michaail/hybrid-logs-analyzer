import type { Page, Response } from "@playwright/test";

import { expect } from "../fixtures";
import { uniquePackageIdentity, writePackageZip } from "./packages";

export function eligiblePackage(): ReturnType<typeof writePackageZip> {
  return writePackageZip("eligible", uniquePackageIdentity("e2e.pub"));
}

export function ineligiblePackage(): ReturnType<typeof writePackageZip> {
  return writePackageZip("ineligible", uniquePackageIdentity("e2e.reject"));
}

export function modelArticle(page: Page, identifier: string, version: string) {
  return page.getByRole("article", { name: `${identifier} version ${version}` });
}

export async function openPublisherWorkspace(page: Page, projectName = "e2e-project-a"): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  await page.getByRole("button", { name: /^Models/ }).click();
  await expect(page.getByRole("button", { name: "Register trained model" })).toBeVisible();
}

export async function registerPackage(
  page: Page,
  zipPath: string,
  bundleZipPath: string,
): Promise<Response> {
  await page.getByRole("button", { name: "Register trained model" }).click();
  const dialog = page.getByRole("dialog", { name: "Register trained model" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("HDFS model package ZIP").setInputFiles(zipPath);
  await dialog.getByLabel("Preprocessing-bundle ZIP").setInputFiles(bundleZipPath);
  const pending = page.waitForResponse((response) => {
    if (response.request().method() !== "POST") {
      return false;
    }
    return /\/projects\/[^/]+\/models$/.test(new URL(response.url()).pathname);
  });
  await dialog.getByRole("button", { name: "Register model" }).click();
  return pending;
}
