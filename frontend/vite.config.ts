import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiOrigin = (process.env.E2E_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/admin": apiOrigin,
      "/auth": apiOrigin,
      "/projects": apiOrigin,
      "/users": apiOrigin
    }
  }
});
