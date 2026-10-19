// The shell (#296): page titles (R5), the route error states inside a working
// shell (R6), the navigation's rule of two (R4), and the back link (R7).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GaugeIcon } from "lucide-react";
import { createMemoryRouter, Link, type RouteObject } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BackLink } from "./back-link";
import { isChunkLoadError } from "./errors";
import { Nav } from "./nav";
import { RouteError } from "./route-error";
import { SECTIONS, type Section } from "./sections";
import { Shell } from "./shell";
import { usePageTitle } from "./title";

vi.hoisted(() => {
  class PageRequest extends Request {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, window.location.href) : input, init);
    }
  }
  globalThis.Request = PageRequest;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** The engineer is down; the pit wall is 0.7.1. */
function api() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL((input as Request).url).pathname;
    return path === "/healthz"
      ? Response.json({ ok: true, version: "0.7.1", index: true, engineer: false })
      : Response.json({ error: "the engineer is not answering" }, { status: 502 });
  });
}

function Page({ title }: { title: string }) {
  usePageTitle(title);
  return <h2>{title}</h2>;
}

function Throws(): never {
  throw new Error("the lap table fell over");
}

/** The real shell and error boundary around `pages`. */
function renderShell(pages: RouteObject[], url = "/") {
  api();
  const router = createMemoryRouter(
    [
      {
        path: "/",
        Component: Shell,
        ErrorBoundary: RouteError,
        children: [{ ErrorBoundary: RouteError, children: pages }],
      },
    ],
    { initialEntries: [url] },
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("the shell", () => {
  it("names the page in the tab and the header (R1, R5)", async () => {
    renderShell([{ index: true, element: <Page title="Suzuka Circuit East Course · 6-lap race" /> }]);
    expect(await screen.findByRole("heading", { level: 2 })).toBeTruthy();
    expect(document.title).toBe("Suzuka Circuit East Course · 6-lap race · Pit wall");
    const header = screen.getByRole("banner");
    expect(header.querySelector("[data-slot=header-title]")?.textContent).toBe(
      "Suzuka Circuit East Course · 6-lap race",
    );
    // The wordmark links home.
    const home = within(header).getByRole("link", { name: "Those Who Run" });
    expect(home.getAttribute("href")).toBe("/");
    // The chip is in the header, and an engineer that is down is "Engineer offline".
    expect(await within(header).findByRole("button", { name: "Engineer offline" })).toBeTruthy();
  });

  it("shows a page that throws as its error state, with the header still working (R6)", async () => {
    const router = renderShell([
      { index: true, element: <Page title="Sessions" /> },
      { path: "broken", Component: Throws },
    ]);
    await screen.findByRole("heading", { name: "Sessions" });
    vi.spyOn(console, "error").mockImplementation(() => {});
    await router.navigate("/broken");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("This page failed to show.");
    expect(alert.textContent).toContain("the lap table fell over");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(document.title).toBe("Page failed · Pit wall");

    // The header is still there, and its link still goes home.
    await userEvent.click(within(screen.getByRole("banner")).getByRole("link", { name: "Those Who Run" }));
    expect(await screen.findByRole("heading", { name: "Sessions" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("offers a reload when a page's chunk is gone after a deploy (R6)", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderShell([
      {
        index: true,
        lazy: () =>
          Promise.reject(new TypeError("Failed to fetch dynamically imported module: /assets/session-old.js")),
      },
    ]);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The pit wall has been updated since this tab opened.");
    expect(within(alert).getByRole("button", { name: "Reload to get the new version" })).toBeTruthy();
    expect(screen.getByRole("banner")).toBeTruthy();
  });

  it("tells a chunk that failed to load from any other error", () => {
    expect(isChunkLoadError(new TypeError("Failed to fetch dynamically imported module: x.js"))).toBe(true);
    expect(isChunkLoadError(new TypeError("error loading dynamically imported module: x.js"))).toBe(true);
    expect(isChunkLoadError(new TypeError("Importing a module script failed."))).toBe(true);
    expect(isChunkLoadError(Object.assign(new Error("x"), { name: "ChunkLoadError" }))).toBe(true);
    expect(isChunkLoadError(new Error("the lap table fell over"))).toBe(false);
    expect(isChunkLoadError("Failed to fetch dynamically imported module")).toBe(false);
  });
});

const TWO: Section[] = [
  SECTIONS[0]!,
  { id: "live", label: "Live", to: "/dash", icon: GaugeIcon, prefixes: ["/dash/"] },
];

function renderNav(sections: readonly Section[], url: string) {
  const router = createMemoryRouter([{ path: "*", element: <Nav sections={sections} /> }], { initialEntries: [url] });
  render(<RouterProvider router={router} />);
}

describe("the navigation (R4)", () => {
  it("is not there with one section, as in 0.7", () => {
    expect(SECTIONS.map((s) => s.label)).toEqual(["Sessions"]);
    renderNav(SECTIONS, "/");
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("shows every section with two, the current one marked by the red bar", () => {
    renderNav(TWO, "/sessions/20261017-162118");
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["Sessions", "/"],
      ["Live", "/dash"],
    ]);
    expect(links[0]!.getAttribute("aria-current")).toBe("page");
    expect(links[0]!.querySelector("[data-slot=nav-bar]")?.getAttribute("class")).toContain("bg-accent");
    expect(links[1]!.getAttribute("aria-current")).toBeNull();
    expect(links[1]!.querySelector("[data-slot=nav-bar]")).toBeNull();
    // A tab bar fixed to the bottom, with the home indicator's room, that is a rail from 1024 px.
    expect(nav.className).toContain("fixed");
    expect(nav.className).toContain("bottom-0");
    expect(nav.className).toContain("pb-safe");
    expect(nav.className).toContain("lg:left-0");
    expect(links[0]!.className).toContain("h-15.75");
  });

  it("marks the other section on its own pages", () => {
    renderNav(TWO, "/dash/race");
    const links = within(screen.getByRole("navigation")).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("aria-current"))).toEqual([null, "page"]);
  });
});

describe("the back link (R7)", () => {
  function renderBack() {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: (
            <Link to="/sessions/a" state={{ back: true }}>
              Open
            </Link>
          ),
        },
        { path: "/sessions/:id", element: <BackLink to="/">All sessions</BackLink> },
      ],
      { initialEntries: ["/?track=Suzuka"] },
    );
    render(<RouterProvider router={router} />);
    return router;
  }

  it("is the browser's Back when the page was opened from the list, filters and all", async () => {
    const router = renderBack();
    await userEvent.click(screen.getByRole("link", { name: "Open" }));
    await userEvent.click(await screen.findByRole("link", { name: "All sessions" }));
    expect(router.state.historyAction).toBe("POP");
    expect(router.state.location.pathname + router.state.location.search).toBe("/?track=Suzuka");
  });

  it("is a plain link when the page was opened another way", async () => {
    const router = renderBack();
    await router.navigate("/sessions/a");
    await userEvent.click(await screen.findByRole("link", { name: "All sessions" }));
    expect(router.state.historyAction).toBe("PUSH");
    expect(router.state.location.search).toBe("");
  });
});
