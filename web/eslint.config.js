import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

const DATA_RULE =
  "All data goes through the generated client and its hooks (ADR 0003 point 3): use a hook from @/api/hooks, or add one there.";

export default defineConfig([
  globalIgnores(["dist", "test-results", "playwright-report", "src/api/schema.d.ts"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [reactHooks.configs.flat.recommended, reactRefresh.configs.vite],
  },
  {
    // The rule ADR 0003 point 3 checks: no component calls fetch or the client.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/api/**"],
    rules: {
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: DATA_RULE },
        { name: "XMLHttpRequest", message: DATA_RULE },
        { name: "WebSocket", message: DATA_RULE },
      ],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "fetch", message: DATA_RULE },
        { object: "globalThis", property: "fetch", message: DATA_RULE },
        { object: "self", property: "fetch", message: DATA_RULE },
      ],
      "no-restricted-imports": [
        "error",
        {
          paths: [{ name: "openapi-fetch", message: DATA_RULE }],
          patterns: [{ regex: "(^@/api/client$|/api/client$)", message: DATA_RULE }],
        },
      ],
    },
  },
  {
    files: ["scripts/**/*.ts", "e2e/**/*.ts", "*.config.{ts,js}"],
    languageOptions: { globals: globals.node },
  },
  {
    // Playwright fixtures take their dependencies as `{}` when they have none.
    files: ["e2e/**/*.ts"],
    rules: { "no-empty-pattern": "off" },
  },
]);
