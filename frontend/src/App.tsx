import { lazy, Suspense, useEffect, useState, type CSSProperties } from "react";
import { LAB_ENABLED } from "./flags";
import {
  chromeCssVariables,
  GRAPH_DNA_CHROME,
  type ThemeMode,
} from "./styles/graphDna";
// Type-only: erased at compile time, so it does not pull the labs into the
// bundle. It is what keeps this file's route union and the lab dispatch from
// drifting apart.
import type { LabRoute } from "./LabRoutes";

const ProductHost = lazy(() =>
  import("./product/ProductHost").then((module) => ({
    default: module.ProductHost,
  })),
);
/**
 * The labs, if this build has them.
 *
 * `LAB_ENABLED` is `import.meta.env.DEV`, which Vite substitutes as a literal,
 * so in a production build this is `false ? … : null` — a statically dead
 * branch, and Rollup drops `LabRoutes` and everything it reaches. Thirteen
 * `lazy()` declarations here would each have emitted a chunk regardless of
 * whether anything routed to them: lazy is not absent.
 */
const LabHost = LAB_ENABLED
  ? lazy(() =>
      import("./LabRoutes").then((module) => ({ default: module.LabHost })),
    )
  : null;

/**
 * Three product surfaces plus whatever the labs define. Stated as a union with
 * `LabRoute` rather than re-spelling fourteen names, so a lab page added over
 * there cannot become a route this file silently fails to dispatch.
 */
type Route = "product-graph" | "product-review" | LabRoute;

function normalizeHash() {
  const raw = window.location.hash;
  if (!raw || raw === "#" || raw === "#/") {
    window.history.replaceState(null, "", "#/graph?api=live");
  }
}

function routeFromHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "").split("?")[0];

  if (h === "graph" || h === "ask") return "product-graph";
  if (h === "review" || h === "log") return "product-review";
  // Constructions live in the Graphs drawer, not as a third surface.
  if (h === "construct" || h.startsWith("construct/")) return "product-graph";

  if (h.startsWith("explorations/ledger-feed") || h === "ledger-feed")
    return "ledger-feed";
  if (h.startsWith("explorations/graph-map") || h === "graph-map")
    return "graph-map";
  if (
    h.startsWith("explorations/canvas-linkage") ||
    h === "canvas-linkage"
  )
    return "canvas-linkage";
  if (
    h.startsWith("explorations/ambient-canvas") ||
    h === "ambient-canvas"
  )
    return "ambient-canvas";
  if (
    h.startsWith("explorations/graph-animations") ||
    h === "graph-animations"
  )
    return "graph-animations";
  if (
    h.startsWith("explorations/graph-dna-motion") ||
    h === "graph-dna-motion"
  )
    return "graph-dna-motion";
  if (h.startsWith("explorations/graph-dna") || h === "graph-dna")
    return "graph-dna";
  if (h.startsWith("explorations/ledger-dna") || h === "ledger-dna")
    return "ledger-dna";
  if (h.startsWith("explorations/arrangement") || h === "arrangement")
    return "arrangement";
  if (h.startsWith("explorations/notices") || h === "notices")
    return "notices";
  if (h.startsWith("explorations/events") || h === "events")
    return "events";
  if (h === "explorations" || h.startsWith("explorations/")) {
    return "explorations";
  }
  return "product-graph";
}

function storedTheme(): ThemeMode {
  try {
    return localStorage.getItem("graphauthor.productTheme") === "dark"
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

function RouteLoading() {
  return (
    <div
      className="route-loading"
      role="status"
      style={
        chromeCssVariables(GRAPH_DNA_CHROME[storedTheme()]) as CSSProperties
      }
    >
      Opening…
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => {
    normalizeHash();
    return routeFromHash();
  });

  useEffect(() => {
    const sync = () => {
      normalizeHash();
      setRoute(routeFromHash());
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  let page;
  if (route === "product-graph") page = <ProductHost surface="graph" />;
  else if (route === "product-review") page = <ProductHost surface="log" />;
  else if (LabHost) page = <LabHost route={route as LabRoute} />;
  // A build without labs still has to answer a bookmark to one. Falling back
  // to Graph rather than rendering nothing: the route is gone, not broken.
  else page = <ProductHost surface="graph" />;

  return <Suspense fallback={<RouteLoading />}>{page}</Suspense>;
}
