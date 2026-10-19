import { Link, Outlet } from "react-router";

/** Every page's frame: the name and the page. The real header is #295's. */
export function AppShell() {
  return (
    <div className="mx-auto max-w-3xl p-4">
      <header className="mb-4">
        <h1 className="text-xl font-bold">
          <Link to="/">Those Who Run · pit wall</Link>
        </h1>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
