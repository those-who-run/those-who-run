// The header (#296 R1): the 走り屋 wordmark linking home, the page's title from
// 640 px, and the live engineer chip on the right. Sticky, on `--surface`, with the
// 2 px `--accent` line under it (docs/design.md, the livery rule), and 56 px tall
// with that line, below the notch in standalone mode (R11).
//
// The chip is a chunk of its own, loaded as the page starts: it brings Radix's
// Popover, which the first paint doesn't need (the bundle budget, #237 R6). Until
// it is in, its place holds the same placeholder as "checking".
import wordmark from "@/assets/wordmark.svg";
import { Component, lazy, Suspense, type ReactNode } from "react";
import { Link } from "react-router";

const LiveChip = lazy(() => import("./live-chip").then((m) => ({ default: m.LiveChip })));

function ChipPlaceholder() {
  return (
    <span
      role="status"
      aria-label="Checking the engineer"
      className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-3"
    >
      <span className="h-4 w-16 rounded-sm bg-surface-raised motion-safe:animate-pulse" />
    </span>
  );
}

/** A chip whose chunk failed to load is left out; the page carries on. */
class ChipBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export function Header({ title }: { title: string | null }) {
  return (
    <header data-slot="header" className="sticky top-0 z-40 border-b-2 border-accent bg-surface pt-safe">
      <div className="mx-auto flex h-13.5 max-w-content items-center gap-3 px-gutter">
        <h1 className="shrink-0">
          <Link to="/" className="flex min-h-11 items-center">
            <img src={wordmark} alt="Those Who Run" width={465} height={68} className="h-5 w-auto sm:h-6" />
          </Link>
        </h1>
        {/* The page's own heading says it to a screen reader; this is for the eye. */}
        <p aria-hidden="true" data-slot="header-title" className="hidden min-w-0 truncate text-muted sm:block">
          {title}
        </p>
        <div className="ml-auto flex min-w-0 justify-end">
          <ChipBoundary>
            <Suspense fallback={<ChipPlaceholder />}>
              <LiveChip />
            </Suspense>
          </ChipBoundary>
        </div>
      </div>
    </header>
  );
}
