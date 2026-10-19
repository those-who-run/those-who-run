// @vitest-environment node
//
// ADR 0003 point 3, checked: outside src/api/, nothing calls fetch or the client
// itself (#237 AC5). The real ESLint config, on code it would see in a component.
import { readdirSync } from "node:fs";
import { join, sep } from "node:path";
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

// ADR 0004 point 1, checked: outside src/styles/, style comes only from the tokens
// (#294 R2, AC2).
const STYLE = "twr-style/no-style-literals";

describe("style only through the tokens", () => {
  it.each([
    ["an arbitrary colour class", 'export const A = () => <p className="text-[#ff0000]">x</p>;'],
    ["a hex colour in a style prop", "export const A = () => <p style={{ color: \"#f00\" }}>x</p>;"],
    ["an arbitrary pixel spacing", 'export const A = () => <p className="p-[13px]">x</p>;'],
    ["rgb()", 'export const c = "rgb(255 0 0)";'],
    ["hsl()", 'export const c = "hsl(0 100% 50%)";'],
    ["oklch()", 'export const c = "oklch(62% 0.25 29)";'],
    ["a hex colour in a class list", 'export const c = ["border", "#D21F1B"];'],
    ["a hex colour in a template", "export const c = (w: number) => `${w}px solid #333`;"],
    ["an arbitrary property", 'export const A = () => <p className="[mask-type:luminance]">x</p>;'],
    ["a number in a style prop", "export const A = () => <p style={{ padding: 13 }}>x</p>;"],
    ["an arbitrary value with a variant", 'export const c = "hover:bg-[#111] p-2";'],
  ])("%s fails lint, naming the file", async (_, code) => {
    const [result] = await eslint.lintText(code, { filePath: "src/components/lap-time.tsx" });
    expect(result?.filePath).toMatch(/src\/components\/lap-time\.tsx$/);
    expect(result?.messages.filter((m) => m.severity === 2).map((m) => m.ruleId)).toContain(STYLE);
  });

  it.each([
    ["token classes", 'export const A = () => <p className="bg-surface text-muted num p-4 rounded-md">x</p>;'],
    ["a variant with brackets", 'export const c = "data-[state=open]:bg-surface-raised aria-[sort=ascending]:text-fg";'],
    ["a CSS variable value", 'export const c = "p-(--gutter)";'],
    ["a computed style", "export const A = ({ w }: { w: number }) => <p style={{ width: `${w}%` }}>x</p>;"],
    ["an id link", 'export const href = "#main";'],
  ])("%s pass", async (_, code) => {
    expect(await errors(code, "src/components/lap-time.tsx")).not.toContain(STYLE);
  });

  it("src/styles/ may hold literals", async () => {
    expect(await errors('export const c = "#D21F1B";', "src/styles/contrast.ts")).toEqual([]);
  });

  it("stylesheets live in src/styles/ only", () => {
    const src = fileURLToPath(new URL("../src", import.meta.url));
    const sheets = readdirSync(src, { recursive: true, encoding: "utf8" }).filter((f) => f.endsWith(".css"));
    expect(sheets.filter((f) => !f.startsWith(`styles${sep}`))).toEqual([]);
    expect(sheets).toContain(join("styles", "tokens.css"));
  });
});
