// #294 R3, ADR 0004 point 3: every text-on-surface pair docs/design.md allows meets
// its floor (4.5:1 text, 3:1 large text and UI parts, 7:1 dashboard values), read
// from the real tokens. pairs.json holds the pairs and floors; the guide's table
// must agree with it and with the ratios the tokens give.
//
// The files are read from disk: Vitest empties a stylesheet it imports.
/// <reference types="node" />
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { contrast, failures, guideRatios, readTokens, resolve, type Pair } from "./contrast";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const guide = read("../../../docs/design.md");
const brandCss = read("./brand.css");
const tokensCss = read("./tokens.css");
const { pairs, notAllowed } = JSON.parse(read("./pairs.json")) as { pairs: Pair[]; notAllowed: Pair[] };
const tokens = readTokens(brandCss, tokensCss);
const key = (p: { fg: string; bg: string }) => `${p.fg} on ${p.bg}`;

describe("the allowed pairs meet their floors", () => {
  it("every pair", () => {
    expect(failures(tokens, pairs)).toEqual([]);
  });

  it("names a failing pair and its ratio (AC3)", () => {
    const greyer = readTokens(brandCss, tokensCss, ":root { --text-muted: #555555; }");
    const failed = failures(greyer, pairs);
    expect(failed).toContain(
      "--text-muted on --bg is 2.53:1, under the 7:1 its use needs (anything; dashboard values)",
    );
    expect(failed.every((f) => f.startsWith("--text-muted on "))).toBe(true);
  });

  it("the ruled-out pairs are under 3:1, or the guide could allow them", () => {
    for (const p of notAllowed) {
      expect(contrast(resolve(tokens, p.fg), resolve(tokens, p.bg)), key(p)).toBeLessThan(3);
    }
  });
});

describe("pairs.json and docs/design.md agree", () => {
  const stated = guideRatios(guide);

  it("reads the guide's table", () => {
    expect(stated.size).toBeGreaterThanOrEqual(pairs.length);
  });

  it("the guide states each pair's ratio, as the tokens measure it", () => {
    for (const p of [...pairs, ...notAllowed]) {
      const ratio = contrast(resolve(tokens, p.fg), resolve(tokens, p.bg));
      expect(stated.get(key(p)), `${key(p)} in docs/design.md`).toBe(Number(ratio.toFixed(1)));
    }
  });

  it("every ratio the guide states is an allowed or a ruled-out pair", () => {
    const listed = new Set([...pairs, ...notAllowed].map(key));
    expect([...stated.keys()].filter((k) => !listed.has(k))).toEqual([]);
  });
});

describe("the tokens", () => {
  it("take the brand's colours from brand.css", () => {
    expect(tokens.get("--bg")).toBe("var(--brand-deep-black)");
    expect(tokens.get("--accent")).toBe("var(--brand-advan-red)");
    expect(resolve(tokens, "--accent")).toBe("#d21f1b");
  });

  it("follow var() to a colour, and say which token is missing", () => {
    expect(resolve(tokens, "--lap-a")).toBe(resolve(tokens, "--accent"));
    expect(() => resolve(new Map([["--a", "var(--b)"]]), "--a")).toThrow("--b is not defined (from --a)");
  });
});
