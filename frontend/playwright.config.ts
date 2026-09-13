import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(frontendRoot, "..");
const apiPort = Number(process.env.E2E_API_PORT ?? 18000);
const uiPort = Number(process.env.E2E_UI_PORT ?? 15173);
const apiOrigin = process.env.E2E_API_ORIGIN ?? `http://127.0.0.1:${apiPort}`;
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${uiPort}`;
const venvPython = path.join(repoRoot, ".venv", "bin", "python");
const python =
  process.env.E2E_PYTHON ?? (fs.existsSync(venvPython) ? venvPython : "python3");

export default defineConfig({
  testDir: path.join(frontendRoot, "e2e"),
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `"${python}" scripts/e2e_serve.py --port ${apiPort}`,
      cwd: repoRoot,
      url: `${apiOrigin}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${uiPort} --strictPort`,
      cwd: frontendRoot,
      url: baseURL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        E2E_API_ORIGIN: apiOrigin,
      },
    },
  ],
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      dependencies: ["setup"],
      testIgnore: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
