import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { searchForWorkspaceRoot } from "vite";
import { defineConfig } from "vitest/config";

// `make web-dev` runs `those-who-run pitwall` on this port and Vite in front of it.
const pitwall = process.env.PITWALL_URL ?? "http://127.0.0.1:9852";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    // dist/.vite/manifest.json: what scripts/bundle-budget.ts measures.
    manifest: true,
  },
  server: {
    // Outside web/, what the tests read: the format cases shared with pytest
    // and the design guide whose contrast table the tokens are checked against.
    fs: {
      allow: [
        searchForWorkspaceRoot(process.cwd()),
        fileURLToPath(new URL("../tests/fixtures", import.meta.url)),
        fileURLToPath(new URL("../docs", import.meta.url)),
      ],
    },
    proxy: { "/api": { target: pitwall, ws: true }, "/healthz": pitwall },
  },
  test: {
    // Component tests run in jsdom; the route import test asks for node itself.
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.ts"],
    restoreMocks: true,
  },
});
