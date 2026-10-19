// What contrast.test.ts uses (#294 R3): the colour tokens read out of the CSS, and
// the WCAG 2 contrast ratio. Only the tests import this.

export interface Pair {
  fg: string;
  bg: string;
  min: number;
  use?: string;
}

/** Every `--name: value;` in the stylesheets, later ones winning. */
export function readTokens(...css: string[]): Map<string, string> {
  const tokens = new Map<string, string>();
  for (const sheet of css) {
    for (const [, name, value] of sheet.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      tokens.set(name!, value!.trim());
    }
  }
  return tokens;
}

/** A token's colour as #rrggbb, following var() to the value. */
export function resolve(tokens: Map<string, string>, name: string, seen: string[] = []): string {
  const value = tokens.get(name);
  if (value === undefined) {
    throw new Error(`${name} is not defined${seen.length ? ` (from ${seen.join(" -> ")})` : ""}`);
  }
  const ref = /^var\(\s*(--[\w-]+)\s*\)$/.exec(value);
  if (ref) {
    if (seen.includes(name)) {
      throw new Error(`${[...seen, name].join(" -> ")} is a loop`);
    }
    return resolve(tokens, ref[1]!, [...seen, name]);
  }
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
  if (!hex) {
    throw new Error(`${name} is ${value}: the contrast test reads #rgb or #rrggbb colours only`);
  }
  const h = hex[1]!;
  return `#${(h.length === 3 ? [...h].map((c) => c + c).join("") : h).toLowerCase()}`;
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

/** The WCAG 2 contrast ratio of two colours, 1 to 21. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

/** Each pair under its floor, named with its ratio: empty when all pass. */
export function failures(tokens: Map<string, string>, pairs: Pair[]): string[] {
  return pairs.flatMap((p) => {
    const ratio = contrast(resolve(tokens, p.fg), resolve(tokens, p.bg));
    return ratio < p.min
      ? [`${p.fg} on ${p.bg} is ${ratio.toFixed(2)}:1, under the ${p.min}:1 its use needs (${p.use ?? "?"})`]
      : [];
  });
}

/** The guide's allowed-pairs table: the ratio it states for each foreground on each
 * background. A `--a` on `--b` row states one ratio, at the start of its last cell. */
export function guideRatios(markdown: string): Map<string, number> {
  const section = /### Allowed pairs\n([\s\S]*?)\n(?:#|\n[^|])/.exec(markdown)?.[1] ?? "";
  const rows = section.split("\n").filter((l) => l.startsWith("| `"));
  const header = section.split("\n").find((l) => l.startsWith("| Foreground"));
  const columns = (header ?? "").split("|").slice(2, -2).map((c) => /`(--[\w-]+)`/.exec(c)?.[1]);
  const ratios = new Map<string, number>();
  for (const row of rows) {
    const cells = row.split("|").slice(1, -1).map((c) => c.trim());
    const [fg, on] = [...cells[0]!.matchAll(/`(--[\w-]+)`/g)].map((m) => m[1]!);
    if (on) {
      ratios.set(`${fg} on ${on}`, parseFloat(cells.at(-1)!));
      continue;
    }
    columns.forEach((bg, i) => {
      const n = parseFloat(cells[i + 1] ?? "");
      if (bg && !Number.isNaN(n)) {
        ratios.set(`${fg} on ${bg}`, n);
      }
    });
  }
  return ratios;
}
