/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The built UI is packaged into the Python wheel and served by the same process as MCP.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/okf_notebooks/webui_dist", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "jsdom", globals: false },
});
