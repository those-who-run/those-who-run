// The session list: the proof that the build, the client, the router and the
// tests fit (#237). Plain on purpose: the designed list is #297.
import { Link } from "react-router";

import { useSessions } from "@/api/hooks";
import { usePageTitle } from "@/app/title";

export function Component() {
  usePageTitle("Sessions");
  const sessions = useSessions();

  if (sessions.isPending) {
    return <p>Loading sessions…</p>;
  }
  if (sessions.isError) {
    return <p role="alert">Could not load the sessions: {sessions.error.message}</p>;
  }
  if (sessions.data.sessions.length === 0) {
    return <p>No sessions yet.</p>;
  }
  return (
    <ul className="space-y-2" aria-label="Sessions">
      {sessions.data.sessions.map((s) => (
        <li key={s.session_id}>
          {/* `back`: the session's "All sessions" is then the browser's Back (#296 R7). */}
          <Link
            className="underline break-words"
            to={`/sessions/${encodeURIComponent(s.session_id)}`}
            state={{ back: true }}
          >
            {s.title}
          </Link>
        </li>
      ))}
    </ul>
  );
}
