/**
 * Live graph → the ambient canvas's own data shape.
 *
 * The canvas is driven entirely by one `GraphData`, so pointing it at a real
 * committed graph is a data-source swap, not a second canvas. Everything the
 * fixture unlocked — mass/LOD coarsening, CONTAINS hulls, the cursor lens, the
 * hover bond, seam modes — applies unchanged, because the shape it consumes is
 * the shape produced here.
 *
 * Source of truth: `/graph/map` (see `graph_read.py`). Coordinates come from
 * the server and are used as-is; nothing is laid out in the browser.
 */

import type { EdgeData, GraphData, NodeData } from "@antv/g6";
import { useEffect, useMemo, useState } from "react";
import { lensVisualKindOf } from "../g6/lensEdgeOptions";
import type { AmbientLodNodeData } from "./ambientLodData";
import { ApiError } from "../../api/client";
import { fetchMap, isLiveMode, type GraphMap } from "../../api/graph";

/**
 * Share of nodes treated as landmarks. The fixture hand-picked region roots and
 * hubs; on a real graph the equivalent is "the most structurally central few",
 * so take a fixed share rather than a magic importance threshold that would
 * mean different things on different graphs.
 */
const LANDMARK_SHARE = 0.12;
const MAX_LANDMARKS = 14;

function normalise(values: Map<string, number>): Map<string, number> {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values.values()) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const span = Math.max(1e-9, max - min);
  const out = new Map<string, number>();
  for (const [k, v] of values) out.set(k, (v - min) / span);
  return out;
}

export function liveMapToAmbientGraph(map: GraphMap): GraphData {
  const contains = map.edges.filter((e) => e.type === "CONTAINS");
  const parentOf = new Map<string, string>();
  for (const e of contains) parentOf.set(e.target, e.source);

  // Importance drives mass and therefore LOD survival. Betweenness is the real
  // signal — but it is `null` when the server skipped Brandes on a large cold
  // graph, and normalising nulls to zero would make every node equally
  // unimportant and collapse the LOD. Degree is the honest stand-in there:
  // cruder, but it is measured.
  const measured = map.structural_mode === "full";
  const raw = new Map<string, number>();
  if (measured) {
    for (const n of map.nodes) raw.set(n.id, n.betweenness ?? 0);
  } else {
    for (const n of map.nodes) raw.set(n.id, 0);
    for (const e of map.edges) {
      raw.set(e.source, (raw.get(e.source) ?? 0) + 1);
      raw.set(e.target, (raw.get(e.target) ?? 0) + 1);
    }
  }
  const importance = normalise(raw);

  const ranked = [...map.nodes]
    .sort((a, b) => (importance.get(b.id) ?? 0) - (importance.get(a.id) ?? 0))
    .map((n) => n.id);
  const landmarkCount = Math.min(
    MAX_LANDMARKS,
    Math.max(1, Math.round(map.nodes.length * LANDMARK_SHARE)),
  );
  const landmarks = new Set(ranked.slice(0, landmarkCount));

  const nodes: NodeData[] = map.nodes.map((n) => ({
    id: n.id,
    data: {
      label: n.label || n.id,
      // Descriptive only — the canvas never branches on it.
      kind: n.is_metanode ? "metanode" : "concept",
      importance: importance.get(n.id) ?? 0,
      is_landmark: landmarks.has(n.id),
      region_id: parentOf.get(n.id),
    } satisfies AmbientLodNodeData,
    style: { x: n.x, y: n.y },
  }));

  const edges: EdgeData[] = map.edges.map((e, i) => {
    const label = e.type;
    return {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      // `kind` resolved through the shared helper so the live graph and the
      // fixture speak the same edge vocabulary.
      data: {
        label,
        kind: lensVisualKindOf({ source: e.source, target: e.target, data: { label } }),
      },
    };
  });

  return { nodes, edges };
}

export type LiveGraphState = {
  /** `null` until a real graph is loaded — the canvas falls back to its fixture. */
  data: GraphData | null;
  map: GraphMap | null;
  loading: boolean;
  error: string | null;
  /** `false` when the page was not opened in live mode; nothing was attempted. */
  enabled: boolean;
};

/** `?graph=<id>` picks which graph; omitted means the server's current one. */
function graphIdFromUrl(): string | undefined {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const merged = [
    window.location.search.replace(/^\?/, ""),
    q >= 0 ? hash.slice(q + 1) : "",
  ]
    .filter(Boolean)
    .join("&");
  return new URLSearchParams(merged).get("graph") ?? undefined;
}

/**
 * Load the committed graph for the ambient canvas. Returns `data: null` in
 * fixture mode so the lab keeps working with no server, which is the whole
 * reason the fixture exists.
 */
export function useAmbientLiveGraph(): LiveGraphState {
  const enabled = useMemo(() => isLiveMode(), []);
  const graphId = useMemo(() => graphIdFromUrl(), []);
  const [map, setMap] = useState<GraphMap | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    setLoading(true);
    fetchMap(graphId, abort.signal)
      .then((m) => {
        if (!abort.signal.aborted) setMap(m);
      })
      .catch((e: unknown) => {
        if (!abort.signal.aborted) {
          setError(e instanceof ApiError ? e.message : "Could not read the graph.");
        }
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [enabled, graphId]);

  const data = useMemo(() => (map ? liveMapToAmbientGraph(map) : null), [map]);
  return { data, map, loading, error, enabled };
}
