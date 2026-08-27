import { useEffect, useState } from "react";
import { FieldPage } from "../field/FieldPage";
import { InboxPanel } from "../inbox/InboxPanel";
import { useGraphController } from "./GraphController";
import "./AppShell.css";

type Surface = "field" | "inbox";

function useIsNarrow(breakpoint = 900) {
  const [narrow, setNarrow] = useState(
    () =>
      typeof window !== "undefined" ? window.innerWidth < breakpoint : false,
  );
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < breakpoint);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);
  return narrow;
}

export function AppShell() {
  const narrow = useIsNarrow();
  const [surface, setSurface] = useState<Surface>("field");
  const { flyToId } = useGraphController();

  useEffect(() => {
    if (narrow && flyToId) setSurface("field");
  }, [narrow, flyToId]);

  return (
    <div className={narrow ? "app-shell app-shell--narrow" : "app-shell"}>
      <header className="app-shell__top">
        <div className="app-shell__brand">
          <span className="app-shell__mark">Graph</span>
          <span className="app-shell__sub">two-surface core</span>
        </div>
        {narrow && (
          <nav className="app-shell__tabs" aria-label="Surfaces">
            <button
              type="button"
              className={surface === "field" ? "is-active" : ""}
              onClick={() => setSurface("field")}
            >
              Field
            </button>
            <button
              type="button"
              className={surface === "inbox" ? "is-active" : ""}
              onClick={() => setSurface("inbox")}
            >
              Inbox
            </button>
          </nav>
        )}
        <a className="app-shell__explore" href="#/explorations">
          Explorations
        </a>
      </header>

      <div className="app-shell__body">
        <section
          className="app-shell__field"
          hidden={narrow && surface !== "field"}
          aria-label="Field surface"
        >
          <FieldPage />
        </section>
        <section
          className="app-shell__inbox"
          hidden={narrow && surface !== "inbox"}
          aria-label="Escalation inbox"
        >
          <InboxPanel />
        </section>
      </div>
    </div>
  );
}
