/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Local dev: forward API calls to the FastAPI backend.
    proxy: { "/v1": "http://localhost:8000" },
  },
  build: { sourcemap: true, target: "es2022" },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
