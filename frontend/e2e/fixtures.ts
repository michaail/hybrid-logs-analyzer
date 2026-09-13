import { test as base } from "@playwright/test";

import { readAuthToken, type E2ERole } from "./helpers/accounts";

export const test = base.extend<{ role: E2ERole }>({
  role: ["publisher", { option: true }],
  page: async ({ page, role }, use) => {
    const accessToken = readAuthToken(role);
    await page.addInitScript((token: string) => {
      sessionStorage.setItem("logscope.access-token", token);
    }, accessToken);
    await use(page);
  },
});

export { expect } from "@playwright/test";
