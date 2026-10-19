import "./styles/index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";

import { routes } from "./routes";

const queryClient = new QueryClient({
  defaultOptions: {
    // The pit wall answers 304 while nothing changed (ETags), so refetching is cheap.
    queries: { staleTime: 10_000, retry: 1 },
  },
});

const router = createBrowserRouter(routes);

const root = document.getElementById("root");
if (!root) {
  throw new Error("index.html has no #root");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
