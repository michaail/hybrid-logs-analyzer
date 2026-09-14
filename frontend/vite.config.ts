import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const apiOrigin = (process.env.E2E_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["src/test-setup.ts"],
  },
  server: {
    proxy: {
      "/admin": apiOrigin,
      "/auth": apiOrigin,
      "/projects": apiOrigin,
      "/users": apiOrigin
    }
  }
});
