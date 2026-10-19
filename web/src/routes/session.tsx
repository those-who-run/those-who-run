// One session: a stub until #238 ports the laps and the compare.
import { Link, useParams } from "react-router";

import { useSession } from "@/api/hooks";
import { Button } from "@/components/ui/button";

export function Component() {
  const { id = "" } = useParams();
  const session = useSession(id);

  return (
    <article className="space-y-2">
      <h2 className="text-lg font-semibold break-words">
        {session.data?.title ?? (session.isError ? "Session not found" : id)}
      </h2>
      <p className="text-sm">Session {id}. The laps come with #238.</p>
      <Button asChild variant="outline">
        <Link to="/">All sessions</Link>
      </Button>
    </article>
  );
}
