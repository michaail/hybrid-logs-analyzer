# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend/e2e/publish-eligible-hdfs-model.spec.ts >> publisher can upload an eligible HDFS package and explicitly publish it
- Location: frontend/e2e/publish-eligible-hdfs-model.spec.ts:9:1

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/", waiting until "load"

```

# Test source

```ts
  1  | import type { Page, Response } from "@playwright/test";
  2  | 
  3  | import { expect } from "../fixtures";
  4  | import { uniquePackageIdentity, writePackageZip } from "./packages";
  5  | 
  6  | export function eligiblePackage(): ReturnType<typeof writePackageZip> {
  7  |   return writePackageZip("eligible", uniquePackageIdentity("e2e.pub"));
  8  | }
  9  | 
  10 | export function ineligiblePackage(): ReturnType<typeof writePackageZip> {
  11 |   return writePackageZip("ineligible", uniquePackageIdentity("e2e.reject"));
  12 | }
  13 | 
  14 | export function modelArticle(page: Page, identifier: string, version: string) {
  15 |   return page.getByRole("article", { name: `${identifier} version ${version}` });
  16 | }
  17 | 
  18 | export async function openPublisherWorkspace(page: Page, projectName = "e2e-project-a"): Promise<void> {
> 19 |   await page.goto("/");
     |              ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  20 |   await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  21 |   await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  22 |   await page.getByRole("button", { name: /^Models/ }).click();
  23 |   await expect(page.getByRole("button", { name: "Register trained model" })).toBeVisible();
  24 | }
  25 | 
  26 | export async function registerPackage(
  27 |   page: Page,
  28 |   zipPath: string,
  29 | ): Promise<Response> {
  30 |   await page.getByRole("button", { name: "Register trained model" }).click();
  31 |   const dialog = page.getByRole("dialog", { name: "Register trained model" });
  32 |   await expect(dialog).toBeVisible();
  33 |   await dialog.getByLabel("HDFS model package ZIP").setInputFiles(zipPath);
  34 |   const pending = page.waitForResponse((response) => {
  35 |     if (response.request().method() !== "POST") {
  36 |       return false;
  37 |     }
  38 |     return /\/projects\/[^/]+\/models$/.test(new URL(response.url()).pathname);
  39 |   });
  40 |   await dialog.getByRole("button", { name: "Register model" }).click();
  41 |   return pending;
  42 | }
  43 | 
```