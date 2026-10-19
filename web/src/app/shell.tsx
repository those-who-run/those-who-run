// The frame every page sits in (#296): the header with the live engineer chip, the
// sections' navigation once there are two (ADR 0004 point 7), and the page. The
// page's scroll comes back on Back (R7), and the page names itself through
// usePageTitle (R5).
import { useState } from "react";
import { Outlet, ScrollRestoration } from "react-router";

import { Header } from "./header";
import { Nav, NAV_MIN_SECTIONS } from "./nav";
import { SECTIONS } from "./sections";
import { PageTitleContext } from "./title";

export function Shell() {
  const [title, setTitle] = useState<string | null>(null);
  const nav = SECTIONS.length >= NAV_MIN_SECTIONS;
  return (
    <PageTitleContext value={setTitle}>
      <Header title={title} />
      <Nav />
      <div className={nav ? "lg:pl-24" : undefined}>
        <main className={`mx-auto max-w-content px-gutter pt-4 ${nav ? "pb-tab-bar lg:pb-page" : "pb-page"}`}>
          <Outlet />
        </main>
      </div>
      <ScrollRestoration />
    </PageTitleContext>
  );
}
