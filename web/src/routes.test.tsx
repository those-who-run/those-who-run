import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, isRouteErrorResponse, type LoaderFunctionArgs } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { legacySessionLink, routes } from "./routes";

function args(url: string): LoaderFunctionArgs {
  return { request: new Request(url), params: {}, context: undefined } as unknown as LoaderFunctionArgs;
}

describe("the results card's old link (#116)", () => {
  it("redirects /?session=<id> to /sessions/<id>", () => {
    const res = legacySessionLink(args("http://pitwall/?session=20261017-162118"));
    expect(res).toBeInstanceOf(Response);
    expect(res?.status).toBe(302);
    expect(res?.headers.get("Location")).toBe("/sessions/20261017-162118");
  });

  it("escapes the id", () => {
    const res = legacySessionLink(args("http://pitwall/?session=a%2Fb"));
    expect(res?.headers.get("Location")).toBe("/sessions/a%2Fb");
  });

  it("leaves / alone", () => {
    expect(legacySessionLink(args("http://pitwall/"))).toBeNull();
    expect(legacySessionLink(args("http://pitwall/?session="))).toBeNull();
  });
});

const SESSIONS = {
  sessions: [
    { session_id: "20261017-162118", title: "Circuit Gilles Villeneuve · 12-lap race" },
    { session_id: "20261015-180019", title: "Suzuka Circuit East Course · 6-lap race" },
  ],
  filters: { track: [], car: [], kind: [] },
};

function renderAt(url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

// Node's Request, which jsdom keeps, wants an absolute URL; a browser resolves the
// client's same-origin paths against the page, and so does this.
class PageRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === "string" ? new URL(input, window.location.href) : input, init);
  }
}

function answer(status: number, body: unknown) {
  vi.stubGlobal("Request", PageRequest);
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify(body), { status }));
}

describe("the session list, through the generated client", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("lists every title, each linking to its session", async () => {
    const fetch = answer(200, SESSIONS);
    renderAt("/");
    const link = await screen.findByRole("link", { name: SESSIONS.sessions[0]!.title });
    expect(link.getAttribute("href")).toBe("/sessions/20261017-162118");
    expect(screen.getByRole("link", { name: SESSIONS.sessions[1]!.title })).toBeTruthy();
    const request = fetch.mock.calls[0]![0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/v1/sessions");
  });

  it("says when there are none", async () => {
    answer(200, { ...SESSIONS, sessions: [] });
    renderAt("/");
    expect(await screen.findByText("No sessions yet.")).toBeTruthy();
  });

  it("shows the API's error", async () => {
    answer(503, { error: "the index is busy, try again" });
    renderAt("/");
    expect((await screen.findByRole("alert")).textContent).toContain("the index is busy");
  });

  it("follows /?session=<id> to the session", async () => {
    answer(200, SESSIONS.sessions[0]);
    const router = renderAt("/?session=20261017-162118");
    expect(await screen.findByRole("heading", { name: SESSIONS.sessions[0]!.title })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/sessions/20261017-162118");
  });

  it("has a page for anything else", async () => {
    const router = renderAt("/nope");
    expect(await screen.findByText("Nothing here")).toBeTruthy();
    expect(isRouteErrorResponse(router.state.errors)).toBe(false);
  });
});
