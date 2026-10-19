// Page titles (#296 R5): every route names itself with usePageTitle, which sets
// `document.title` to "<page> · Pit wall" and gives the header the page's name to
// show on wider screens (R1).
import { createContext, useContext, useEffect } from "react";

export const APP_TITLE = "Pit wall";

/** The shell's setter for the header's title; null outside a shell (a test). */
export const PageTitleContext = createContext<((title: string) => void) | null>(null);

/** "Suzuka Circuit East Course · 6-lap race · Pit wall". */
export function documentTitle(page: string): string {
  return `${page} · ${APP_TITLE}`;
}

/** Names the page: the tab's title and the header's. */
export function usePageTitle(page: string): void {
  const setHeaderTitle = useContext(PageTitleContext);
  useEffect(() => {
    document.title = documentTitle(page);
    setHeaderTitle?.(page);
  }, [page, setHeaderTitle]);
}
