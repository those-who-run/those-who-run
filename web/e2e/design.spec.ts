// The design tokens and fonts in the built app (#294 AC5, AC6, R4, R8, R9), at each
// of the three viewports.
import { expect, test } from "./pitwall";

test("asks nothing of another origin, and sets body text in Barlow", async ({ page, baseURL }) => {
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));
  await page.goto("/");
  await expect(page.getByRole("list", { name: "Sessions" })).toBeVisible();
  await page.getByRole("list", { name: "Sessions" }).getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 2 })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);

  const origin = new URL(baseURL!).origin;
  const foreign = requests.filter((u) => !u.startsWith("data:") && new URL(u).origin !== origin);
  expect(foreign, "requests to another origin").toEqual([]);
  expect(requests.some((u) => /\/assets\/barlow-latin-400-normal-[\w-]+\.woff2$/.test(u))).toBe(true);

  const body = await page.evaluate(() => ({
    family: getComputedStyle(document.body).fontFamily,
    loaded: document.fonts.check('16px "Barlow"'),
  }));
  expect(body.family).toMatch(/^"?Barlow"?,/);
  expect(body.loaded).toBe(true);
});

test("is dark, with the brand's black", async ({ page }) => {
  await page.goto("/");
  const look = await page.evaluate(() => ({
    scheme: getComputedStyle(document.documentElement).colorScheme,
    background: getComputedStyle(document.documentElement).backgroundColor,
    text: getComputedStyle(document.body).color,
    themeColour: document.querySelector('meta[name="theme-color"]')?.getAttribute("content"),
    preload: document.querySelector('link[rel="preload"][as="font"]')?.getAttribute("href"),
  }));
  expect(look).toEqual({
    scheme: "dark",
    background: "rgb(17, 17, 17)",
    text: "rgb(255, 255, 255)",
    themeColour: "#111111",
    preload: expect.stringMatching(/^\/assets\/barlow-latin-400-normal-[\w-]+\.woff2$/),
  });
});

test("tabular figures: two lap times set with .num are the same width (AC6)", async ({ page }) => {
  await page.goto("/");
  const widths = await page.evaluate(async () => {
    // Every family and weight the guide lists for numbers.
    const faces = [
      ["400", "num"],
      ["500", "num"],
      ["600", "num"],
      ["600", "num-lg"],
      ["700", "num-xl"],
    ];
    const out: Record<string, number[]> = {};
    for (const [weight, cls] of faces) {
      const spans = ["1:11.111", "1:00.000"].map((text) => {
        const span = document.createElement("span");
        span.className = cls!;
        if (cls === "num") {
          span.style.fontWeight = weight!;
        }
        span.textContent = text;
        document.body.append(span);
        return span;
      });
      await document.fonts.ready;
      out[`${cls} ${weight}`] = spans.map((s) => s.getBoundingClientRect().width);
      spans.forEach((s) => s.remove());
    }
    return out;
  });
  for (const [face, [a, b]] of Object.entries(widths)) {
    expect(a, `${face}: 1:11.111 against 1:00.000`).toBeCloseTo(b!, 2);
  }
  // And without .num, Barlow's figures are proportional: the check can fail.
  const proportional = await page.evaluate(async () => {
    const spans = ["1:11.111", "1:00.000"].map((text) => {
      const span = document.createElement("span");
      span.textContent = text;
      document.body.append(span);
      return span;
    });
    await document.fonts.ready;
    return spans.map((s) => s.getBoundingClientRect().width);
  });
  expect(proportional[0]).not.toBeCloseTo(proportional[1]!, 2);
});

test.describe("under reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("the motion tokens are 0", async ({ page }) => {
    await page.goto("/");
    const motion = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      return [root.getPropertyValue("--motion-fast"), root.getPropertyValue("--motion-base")];
    });
    expect(motion.map((v) => parseFloat(v))).toEqual([0, 0]);
  });
});
