// One session: a stub until #238 ports the laps and the compare.
import { useParams } from "react-router";

import { useSession } from "@/api/hooks";
import { BackLink } from "@/app/back-link";
import { usePageTitle } from "@/app/title";
import { Button } from "@/components/ui/button";

export function Component() {
  const { id = "" } = useParams();
  const session = useSession(id);
  const title = session.data?.title ?? (session.isError ? "Session not found" : id);
  usePageTitle(title);

  return (
    <article className="space-y-2">
      <h2 className="text-lg font-semibold break-words">{title}</h2>
      <p className="text-sm">Session {id}. The laps come with #238.</p>
      <Button asChild variant="outline">
        <BackLink to="/">All sessions</BackLink>
      </Button>
    </article>
  );
}
