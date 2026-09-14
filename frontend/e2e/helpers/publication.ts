import fs from "node:fs";
import path from "node:path";

import type { APIRequestContext, Page, Response } from "@playwright/test";

import { expect } from "../fixtures";
import { readAccounts, readAuthToken } from "./accounts";
import { uniquePackageIdentity, writePackageZip } from "./packages";

export function eligiblePackage(): ReturnType<typeof writePackageZip> {
  return writePackageZip("eligible", uniquePackageIdentity("e2e.pub"));
}

export function ineligiblePackage(): ReturnType<typeof writePackageZip> {
  return writePackageZip("ineligible", uniquePackageIdentity("e2e.reject"));
}

export function operatorPublishSeedPackage(): ReturnType<typeof writePackageZip> {
  return writePackageZip("eligible", uniquePackageIdentity("e2e.op.pub"));
}

export function modelArticle(page: Page, identifier: string, version: string) {
  return page.getByRole("article", { name: `${identifier} version ${version}` });
}

export async function openWorkspace(page: Page, projectName = "e2e-project-a"): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  await page.getByRole("button", { name: /^Models/ }).click();
}

export async function openPublisherWorkspace(page: Page, projectName = "e2e-project-a"): Promise<void> {
  await openWorkspace(page, projectName);
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

export async function registerEligibleViaPublisherApi(
  request: APIRequestContext,
  zipPath: string,
  bundleZipPath: string,
): Promise<void> {
  const accounts = readAccounts();
  const headers = { Authorization: `Bearer ${readAuthToken("publisher")}` };
  const listed = await request.get(`${accounts.apiOrigin}/projects`, { headers });
  expect(listed.ok(), await listed.text()).toBeTruthy();
  const projects = (await listed.json()) as Array<{ id: string; name: string }>;
  const projectA = projects.find((project) => project.name === accounts.projectAName);
  if (!projectA) {
    throw new Error(`Project ${accounts.projectAName} was not listed for the publisher.`);
  }
  const created = await request.post(`${accounts.apiOrigin}/projects/${projectA.id}/models`, {
    headers,
    multipart: {
      package: {
        name: path.basename(zipPath),
        mimeType: "application/zip",
        buffer: fs.readFileSync(zipPath),
      },
      preprocessing_bundle: {
        name: path.basename(bundleZipPath),
        mimeType: "application/zip",
        buffer: fs.readFileSync(bundleZipPath),
      },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
}
