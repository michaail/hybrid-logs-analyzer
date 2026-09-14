import { expect, test as setup } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { readAccounts, writeAuthToken } from "./helpers/accounts";

setup("provision isolated projects and store role auth tokens", async ({ page, request }) => {
  const accounts = readAccounts();
  const adminHeaders = await adminAuthHeaders(request, accounts.apiOrigin, accounts.admin);

  await ensureProject(request, accounts.apiOrigin, adminHeaders, accounts.projectAName);
  await ensureProject(request, accounts.apiOrigin, adminHeaders, accounts.projectBName);
  const projects = await listProjects(request, accounts.apiOrigin, adminHeaders);
  const projectA = requireProject(projects, accounts.projectAName);
  const projectB = requireProject(projects, accounts.projectBName);

  await ensureProjectAccount(
    request,
    accounts.apiOrigin,
    adminHeaders,
    accounts.publisherA.username,
    accounts.publisherA.password,
    projectA.id,
    "publisher",
  );
  await ensureProjectAccount(
    request,
    accounts.apiOrigin,
    adminHeaders,
    accounts.operatorA.username,
    accounts.operatorA.password,
    projectA.id,
    "operator",
  );
  await ensureProjectAccount(
    request,
    accounts.apiOrigin,
    adminHeaders,
    accounts.projectBUser.username,
    accounts.projectBUser.password,
    projectB.id,
    "operator",
  );

  const publisherToken = await signInAndReadToken(
    page,
    accounts.publisherA.username,
    accounts.publisherA.password,
    accounts.projectAName,
  );
  writeAuthToken("publisher", publisherToken);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

  const operatorToken = await signInAndReadToken(
    page,
    accounts.operatorA.username,
    accounts.operatorA.password,
    accounts.projectAName,
  );
  writeAuthToken("operator", operatorToken);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

  const projectBToken = await signInAndReadToken(
    page,
    accounts.projectBUser.username,
    accounts.projectBUser.password,
    accounts.projectBName,
  );
  writeAuthToken("project-b-user", projectBToken);
});

async function adminAuthHeaders(
  request: APIRequestContext,
  apiOrigin: string,
  admin: { username: string; password: string },
): Promise<{ Authorization: string }> {
  const response = await request.post(`${apiOrigin}/auth/token`, {
    data: { username: admin.username, password: admin.password },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = (await response.json()) as { access_token: string };
  return { Authorization: `Bearer ${body.access_token}` };
}

async function ensureProject(
  request: APIRequestContext,
  apiOrigin: string,
  headers: { Authorization: string },
  name: string,
): Promise<void> {
  const created = await request.post(`${apiOrigin}/projects`, {
    headers,
    data: { name },
  });
  if (created.status() === 201 || created.status() === 409) {
    return;
  }
  throw new Error(`Creating ${name} failed: ${created.status()} ${await created.text()}`);
}

async function listProjects(
  request: APIRequestContext,
  apiOrigin: string,
  headers: { Authorization: string },
): Promise<Array<{ id: string; name: string }>> {
  const listed = await request.get(`${apiOrigin}/projects`, { headers });
  expect(listed.ok(), await listed.text()).toBeTruthy();
  return (await listed.json()) as Array<{ id: string; name: string }>;
}

function requireProject(
  projects: Array<{ id: string; name: string }>,
  name: string,
): { id: string; name: string } {
  const match = projects.find((project) => project.name === name);
  if (!match) {
    throw new Error(`Project ${name} was not listed after provisioning.`);
  }
  return match;
}

async function ensureProjectAccount(
  request: APIRequestContext,
  apiOrigin: string,
  headers: { Authorization: string },
  username: string,
  password: string,
  projectId: string,
  role: "publisher" | "operator",
): Promise<void> {
  const created = await request.post(`${apiOrigin}/admin/project-accounts`, {
    headers,
    data: {
      username,
      password,
      project_id: projectId,
      role,
    },
  });
  if (created.status() === 201 || created.status() === 409) {
    return;
  }
  throw new Error(`Provisioning ${username} failed: ${created.status()} ${await created.text()}`);
}

async function signInAndReadToken(
  page: Page,
  username: string,
  password: string,
  projectName: string,
): Promise<string> {
  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
  const token = await page.evaluate(() => sessionStorage.getItem("logscope.access-token"));
  if (!token) {
    throw new Error(`No access token was stored for ${username}.`);
  }
  return token;
}
