// The one place the app talks HTTP (ADR 0003 point 3): the client generated from
// web/openapi.json. Components use the hooks in ./hooks.ts, never this; ESLint
// stops `fetch` and this module being used outside src/api/.
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Session = components["schemas"]["Session"];
export type SessionList = components["schemas"]["SessionList"];
export type EngineStatus = components["schemas"]["EngineStatus"];
export type Health = components["schemas"]["Health"];

// Same origin: the pit wall serves the app and the API (ADR 0003 point 6). Nothing
// runs at import: fetch is looked up per request, so a test can replace it.
export const client = createClient<paths>({ baseUrl: "", fetch: (request) => fetch(request) });

/** A non-2xx answer, with the API's own message (its ApiError body). */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** The body of a call, or an ApiError for its status and message. */
export function unwrap<T>(result: {
  data?: T;
  error?: { error: string };
  response: Response;
}): T {
  if (result.data !== undefined) {
    return result.data;
  }
  const { status, statusText } = result.response;
  throw new ApiError(status, result.error?.error ?? (statusText || `HTTP ${status}`));
}
