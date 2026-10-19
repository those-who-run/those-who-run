// Any path the app doesn't have (#296 R6): said plainly, with the way home.
import { Link } from "react-router";

import { usePageTitle } from "@/app/title";

export function Component() {
  usePageTitle("Nothing here");
  return (
    <div className="space-y-2">
      <h2 className="text-lg font-semibold">Nothing here</h2>
      <p className="text-muted">The pit wall has no page at this address.</p>
      <Link className="inline-flex min-h-11 items-center text-accent-text underline underline-offset-4" to="/">
        All sessions
      </Link>
    </div>
  );
}
