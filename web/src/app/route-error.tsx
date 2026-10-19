// A route that failed (#296 R6): the kit's ErrorState where the page would be,
// inside the shell, so the header, the chip and the navigation keep working. A
// chunk that no longer exists (a tab left open over a deploy) offers a reload to
// get the new version; anything else says the page failed, with the error behind
// Details.
//
// ErrorState is a chunk of its own, fetched as the app starts (main.tsx), so it is
// in memory before a deploy can take its file away; the first paint doesn't need
// it (the bundle budget, #237 R6).
import { lazy, Suspense } from "react";
import { isRouteErrorResponse, useRouteError } from "react-router";

import { isChunkLoadError, loadErrorState } from "./errors";
import { usePageTitle } from "./title";

const ErrorState = lazy(() => loadErrorState().then((m) => ({ default: m.ErrorState })));

function reload() {
  window.location.reload();
}

function message(error: unknown): string | null {
  if (isRouteErrorResponse(error)) {
    return `${error.status} ${error.statusText}`.trim();
  }
  if (error instanceof Error) {
    return error.message;
  }
  return error == null ? null : String(error);
}

export function RouteError() {
  const error = useRouteError();
  const stale = isChunkLoadError(error);
  usePageTitle(stale ? "New version" : "Page failed");
  return (
    <Suspense fallback={null}>
      {stale ? (
        <ErrorState
          title="The pit wall has been updated since this tab opened."
          hint="This page is part of the new version."
          actionLabel="Reload to get the new version"
          onRetry={reload}
        />
      ) : (
        <ErrorState
          title="This page failed to show."
          hint="Retry. If it fails again, it is a bug in the pit wall, and the details say where."
          detail={message(error)}
          onRetry={reload}
        />
      )}
    </Suspense>
  );
}
