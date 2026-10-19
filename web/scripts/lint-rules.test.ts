// @vitest-environment node
//
// ADR 0003 point 3, checked: outside src/api/, nothing calls fetch or the client
// itself (#237 AC5). The real ESLint config, on code it would see in a component.
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const eslint = new ESLint({ cwd: fileURLToPath(new URL("..", import.meta.url)) });

async function errors(code: string, filePath: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath });
  return (result?.messages ?? []).filter((m) => m.severity === 2).map((m) => m.ruleId ?? m.message);
}

const COMPONENT = "src/components/laps.tsx";

describe("data goes through src/api/ only", () => {
  it.each([
    ["fetch", 'export const load = () => fetch("/api/v1/sessions");', "no-restricted-globals"],
    ["window.fetch", 'export const load = () => window.fetch("/api/v1/sessions");', "no-restricted-properties"],
    ["globalThis.fetch", 'export const load = () => globalThis.fetch("/x");', "no-restricted-properties"],
    ["XMLHttpRequest", "export const x = () => new XMLHttpRequest();", "no-restricted-globals"],
    ["the client", 'import { client } from "@/api/client";\nexport const c = client;', "no-restricted-imports"],
    ["the client, relatively", 'import { client } from "../api/client";\nexport const c = client;', "no-restricted-imports"],
    ["openapi-fetch", 'import createClient from "openapi-fetch";\nexport const c = createClient;', "no-restricted-imports"],
  ])("a component that uses %s fails lint", async (_, code, rule) => {
    expect(await errors(code, COMPONENT)).toContain(rule);
  });

  it("a component that uses a hook passes", async () => {
    const code = 'import { useSessions } from "@/api/hooks";\nexport const use = () => useSessions();';
    expect(await errors(code, COMPONENT)).toEqual([]);
  });

  it("src/api/ may fetch", async () => {
    const code = 'export const load = () => fetch("/api/v1/sessions");';
    expect(await errors(code, "src/api/extra.ts")).toEqual([]);
  });
});
