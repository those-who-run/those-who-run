import { Link } from "react-router";

export function Component() {
  return (
    <div className="space-y-2">
      <h2 className="text-lg font-semibold">Nothing here</h2>
      <Link className="underline" to="/">
        All sessions
      </Link>
    </div>
  );
}
