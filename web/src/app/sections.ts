// The app's sections, in the order the navigation shows them (#296 R4). A section
// goes in when its first page ships, never before: there is never a tab for
// something not built (ADR 0004 point 7). With one section there is no navigation
// at all; the second one brings the tab bar and the side rail. docs/design.md
// (Information architecture) has the ones still to come: Live, Progress, Setup.
import { ListIcon, type LucideIcon } from "lucide-react";

export interface Section {
  /** A stable key. */
  id: string;
  /** Its name in the navigation: one short word. */
  label: string;
  /** Where its tab goes. */
  to: string;
  icon: LucideIcon;
  /** Path prefixes beyond `to` whose pages belong to it, so its tab stays marked there. */
  prefixes: string[];
}

export const SECTIONS: readonly Section[] = [
  { id: "sessions", label: "Sessions", to: "/", icon: ListIcon, prefixes: ["/sessions/"] },
];

/** The section a path belongs to: its `to` exactly, or one of its prefixes. */
export function isActive(section: Section, pathname: string): boolean {
  return pathname === section.to || section.prefixes.some((p) => pathname.startsWith(p));
}
