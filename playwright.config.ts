/**
 * Loaded when Playwright is started from the repository root.
 * `npx --prefix frontend playwright test` does not change cwd, so without this
 * file the frontend config (baseURL, webServer, auth setup) is skipped.
 */
export { default } from "./frontend/playwright.config.ts";
