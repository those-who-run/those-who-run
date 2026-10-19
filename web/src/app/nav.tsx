// The sections' navigation (#296 R4, ADR 0004 point 7): a bottom tab bar on a
// phone and a tablet, a side rail from 1024 px. One <nav>, laid out by the shell's
// breakpoint, so there is one landmark at any width. It shows only when there are
// two sections or more; with one (0.7: Sessions), it renders nothing.
//
// The active item has the 3 px `--accent` bar (docs/design.md, the livery rule): on
// its top edge in the tab bar, its left edge in the rail. It is marked by the bar
// and white text, never by the raised fill, which red may not sit on.
import { Link, useLocation } from "react-router";

import { isActive, SECTIONS, type Section } from "./sections";

/** The navigation needs this many sections before it shows. */
export const NAV_MIN_SECTIONS = 2;

export function Nav({
  sections = SECTIONS,
  contained = false,
  label = "Sections",
}: {
  sections?: readonly Section[];
  /** In the page's flow instead of fixed to the screen: the kit's preview. */
  contained?: boolean;
  label?: string;
}) {
  const { pathname } = useLocation();
  if (sections.length < NAV_MIN_SECTIONS) {
    return null;
  }
  const place = contained
    ? "relative lg:w-24 lg:border-r"
    : "fixed inset-x-0 bottom-0 z-40 pb-safe lg:inset-x-auto lg:top-14 lg:left-0 lg:w-24 lg:border-r lg:pb-0 lg:pl-safe";
  return (
    <nav aria-label={label} data-slot="nav" className={`${place} border-t bg-surface lg:border-t-0`}>
      <ul className="flex lg:flex-col lg:py-2">
        {sections.map((s) => {
          const active = isActive(s, pathname);
          return (
            <li key={s.id} className="min-w-0 flex-1 lg:flex-none">
              <Link
                to={s.to}
                aria-current={active ? "page" : undefined}
                className={`relative flex h-15.75 flex-col items-center justify-center gap-1 text-meta font-medium transition-colors duration-fast lg:h-18 ${
                  active ? "text-fg" : "text-muted hover:text-fg"
                }`}
              >
                <s.icon aria-hidden="true" className="size-6" />
                <span className="max-w-full truncate px-1">{s.label}</span>
                {active && (
                  <span
                    aria-hidden="true"
                    data-slot="nav-bar"
                    className="absolute inset-x-4 top-0 h-0.75 bg-accent lg:inset-x-auto lg:inset-y-3 lg:left-0 lg:h-auto lg:w-0.75"
                  />
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
