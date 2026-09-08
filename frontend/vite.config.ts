import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/admin": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
      "/projects": "http://127.0.0.1:8000",
      "/users": "http://127.0.0.1:8000"
    }
  }
});
