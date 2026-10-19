// The route table, in React Router's data mode (ADR 0003 point 2). Each page is a
// module under src/routes/, loaded with `lazy` so it is its own chunk (#237 R4); the
// bundle budget fails a route module that is not. Nothing here touches the DOM:
// main.tsx makes the browser router from this table.
import { redirect, type LoaderFunctionArgs, type RouteObject } from "react-router";

import { AppShell } from "@/components/app-shell";

/** `/?session=<id>`, the link on a results card before #237 (#116), is now
 * `/sessions/<id>`. Runs before the list's chunk loads. */
export function legacySessionLink({ request }: LoaderFunctionArgs) {
  const id = new URL(request.url).searchParams.get("session");
  return id ? redirect(`/sessions/${encodeURIComponent(id)}`) : null;
}

export const routes: RouteObject[] = [
  {
    path: "/",
    Component: AppShell,
    children: [
      { index: true, loader: legacySessionLink, lazy: () => import("./routes/sessions") },
      { path: "sessions/:id", lazy: () => import("./routes/session") },
      { path: "*", lazy: () => import("./routes/not-found") },
    ],
  },
];
