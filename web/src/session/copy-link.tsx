// The session page's overflow menu (#298 R9): "Copy link" copies the session's
// address. The clipboard needs HTTPS (or localhost); without it the menu shows the
// address to copy by hand.
import { CheckIcon, EllipsisIcon, LinkIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

type Copied = "idle" | "copied" | "manual";

/** The session's address, without the page's picks. */
function sessionUrl(id: string): string {
  return `${window.location.origin}/sessions/${encodeURIComponent(id)}`;
}

export function SessionMenu({ sessionId }: { sessionId: string }) {
  const [copied, setCopied] = useState<Copied>("idle");
  const url = typeof window === "undefined" ? "" : sessionUrl(sessionId);

  const copy = async () => {
    try {
      if (!navigator.clipboard) {
        throw new Error("no clipboard");
      }
      await navigator.clipboard.writeText(url);
      setCopied("copied");
    } catch {
      setCopied("manual");
    }
  };

  return (
    <Popover onOpenChange={(open) => !open && setCopied("idle")}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="More" className="-mr-2">
          <EllipsisIcon aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" aria-label="Session" className="w-64 space-y-2 p-2">
        <Button variant="ghost" className="w-full justify-start" onClick={() => void copy()}>
          {copied === "copied" ? <CheckIcon aria-hidden="true" /> : <LinkIcon aria-hidden="true" />}
          Copy link
        </Button>
        <p role="status" className="px-2 text-meta text-muted empty:hidden">
          {copied === "copied" ? "Link copied." : copied === "manual" ? "Couldn't copy here: select the link." : ""}
        </p>
        {copied === "manual" && (
          <input
            readOnly
            aria-label="The session's link"
            value={url}
            onFocus={(e) => e.currentTarget.select()}
            className="min-h-11 w-full rounded-md border border-input bg-bg px-2 text-sm"
          />
        )}
      </PopoverContent>
    </Popover>
  );
}
