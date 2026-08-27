import { useEffect, useState } from "react";
import { usePresence } from "../styles/usePresence";
import { GraphWorkspace } from "./GraphWorkspace";
import { LogsWorkspace } from "./LogsWorkspace";
import {
  ProductShell,
  SurfaceLayer,
  type ProductSurface,
} from "./ProductShell";

/**
 * One shell for Graph and Logs. Identity used to remount with the route,
 * so the same two words rebuilt themselves on every trip. The map stays
 * mounted once visited; Logs absorbs out.
 */
export function ProductHost({ surface }: { surface: ProductSurface }) {
  const [graphKept, setGraphKept] = useState(surface === "graph");
  useEffect(() => {
    if (surface === "graph") setGraphKept(true);
  }, [surface]);
  const graph = usePresence(surface === "graph", { stayMounted: graphKept });
  const log = usePresence(surface === "log");

  return (
    <ProductShell active={surface}>
      <div className="product-shell__scenes">
        {graph.mounted ? (
          <SurfaceLayer surface="graph">
            <div
              className={`product-shell__scene motion-layer motion-layer--fade${graph.shown ? " is-in" : ""}`}
              aria-hidden={!graph.shown}
              inert={!graph.shown}
            >
              <GraphWorkspace productMode />
            </div>
          </SurfaceLayer>
        ) : null}
        {log.mounted ? (
          <SurfaceLayer surface="log">
            <div
              className={`product-shell__scene motion-layer motion-layer--fade${log.shown ? " is-in" : ""}`}
              aria-hidden={!log.shown}
              inert={!log.shown}
            >
              <LogsWorkspace />
            </div>
          </SurfaceLayer>
        ) : null}
      </div>
    </ProductShell>
  );
}
