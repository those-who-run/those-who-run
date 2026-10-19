// A link back to where the page was opened from, such as "All sessions" (#296 R7).
// When the page was opened from that place in the app, it is the browser's Back,
// so the list comes back with its scroll and filters; opened any other way (a
// results card's link, a bookmark, a reload), it is a plain link to `to`.
//
// The link that opens the page says where it came from: `state={{ back: true }}`.
import type { ComponentProps, MouseEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";

export function BackLink({ onClick, ...props }: ComponentProps<typeof Link>) {
  const location = useLocation();
  const navigate = useNavigate();
  const cameFromApp = (location.state as { back?: boolean } | null)?.back === true;
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    const plain = e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
    if (cameFromApp && plain && !e.defaultPrevented) {
      e.preventDefault();
      navigate(-1);
    }
  };
  return <Link {...props} onClick={click} />;
}
