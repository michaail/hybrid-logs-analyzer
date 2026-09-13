import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
export const authDir = path.join(repoRoot, "playwright", ".auth");

export interface E2EAccounts {
  apiOrigin: string;
  projectAName: string;
  projectBName: string;
  admin: { username: string; password: string };
  publisherA: { username: string; password: string };
  projectBUser: { username: string; password: string };
}

export type E2ERole = "publisher" | "project-b-user";

export function readAccounts(): E2EAccounts {
  const accountsPath = path.join(authDir, "accounts.json");
  if (!fs.existsSync(accountsPath)) {
    throw new Error(
      `Missing ${accountsPath}. Start the suite with npm --prefix frontend run test:e2e so scripts/e2e_serve.py can seed accounts.`,
    );
  }
  return JSON.parse(fs.readFileSync(accountsPath, "utf8")) as E2EAccounts;
}

export function writeAuthToken(role: E2ERole, accessToken: string): void {
  fs.mkdirSync(authDir, { recursive: true });
  fs.writeFileSync(
    path.join(authDir, `${role}.json`),
    JSON.stringify({ accessToken }, null, 2) + "\n",
    { encoding: "utf8" },
  );
}

export function readAuthToken(role: E2ERole): string {
  const authPath = path.join(authDir, `${role}.json`);
  if (!fs.existsSync(authPath)) {
    throw new Error(`Missing ${authPath}. The Playwright setup project must run first.`);
  }
  const payload = JSON.parse(fs.readFileSync(authPath, "utf8")) as { accessToken: string };
  if (!payload.accessToken) {
    throw new Error(`Auth file ${authPath} does not contain an access token.`);
  }
  return payload.accessToken;
}
