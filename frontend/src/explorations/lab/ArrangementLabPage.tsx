/**
 * Arrangement lab — read the server's layout, in the graph's design language.
 *
 * The point of this page is to make a *backend* decision visible. Layout is
 * server-side and persisted (decided 2026-07-27): the browser asks for an
 * arrangement and renders the coordinates it gets. Nothing here computes a
 * position, and there is deliberately no force simulation to reach for — if the
 * picture is wrong, the fix is in `graph_layout/`, not in this file.
 *
 * Styling comes from `styles/graphDna.ts`, which is the workbench's language
 * rather than a copy of it. Solid discs of the darkest ink with their label set
 * inside, thin filaments, a near-white field.
 *
 * What the toggles are for: each exposes a fact the arrangement is built on, so
 * a bad layout can be read back to its cause.
 *
 * Backend: `graph_read.py`, `graph_layout/`, `design [new]/graph-arrangement.md`.
 */

import {
  Graph,
  type EdgeData,
  type GraphData,
  type IElementEvent,
  type NodeData,
} from "@antv/g6";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchMap,
  listGraphs,
  type GraphMap,
  type GraphSummary,
  type MapNode,
} from "../../api/graph";
import { FONT_SANS_FAMILY } from "../../styles/typography";
import {
  GRAPH_DNA_GEOMETRY,
  mixHex,
  resolveGraphDna,
} from "../../styles/graphDna";
import { MOTION_DURATION_MS, MOTION_SPINE } from "../../styles/motion";
import {
  arrowSizeForKind,
  isDirectedKind,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import {
  AMBIENT_LINKAGE_EDGE,
  ensureAmbientLinkageEdgeRegistered,
} from "./ambientLinkageEdge";
import "./ArrangementLabPage.css";

const EDGE_TYPES = ["CONTAINS", "LEADSTO", "EXPRESSES", "NEARTO"] as const;
type EdgeType = (typeof EDGE_TYPES)[number];

const LENS_LABELS: Record<string, string> = {
  canonical: "Structure",
  causal: "Cause",
  membership: "Belonging",
};

const LENS_HINTS: Record<string, string> = {
  canonical: "What is in this graph?",
  causal: "Where does this lead?",
  membership: "Who belongs to what?",
};

/** Which edge types the spine is allowed to follow (see `spine.py`). */
const SPINE_TYPES = new Set<EdgeType>(["CONTAINS", "LEADSTO"]);

const DNA = resolveGraphDna("light");
const GEO = GRAPH_DNA_GEOMETRY;

/**
 * Accent for structurally isolated nodes — nothing in the graph connects to
 * them. That is a fact about the graph's shape. It is **not** a governance
 * verdict: GOVERNED / UNGOVERNED is a property of a *query* the traversal
 * either can or cannot answer, never a property of a node.
 */
const ISOLATED = "#b1471f";

/**
 * Region tints. Nodes stay solid discs in the graph's language; the read-out
 * only pulls the fill part-way toward a hue, so structure becomes legible
 * without the field turning into a categorical chart.
 */
const REGION_HUES = [
  "#2f4858", "#5b5f97", "#7a5c61", "#3f6c51", "#6b5344",
  "#4a5d6b", "#7c6a8a", "#556b3f", "#8a6d3b", "#41666b",
];
const REGION_MIX = 0.55;

/** Tier scales the DNA diameter; it never introduces a second node language. */
const TIER_SCALE: Record<string, number> = {
  landmark: 1,
  hub: 0.72,
  leaf: 0.55,
};
/** Unmeasured renders neutral — never smallest, which would claim peripheral. */
const TIER_SCALE_UNKNOWN = 0.64;

type Toggles = {
  regions: boolean;
  depth: boolean;
  isolated: boolean;
  tier: boolean;
  labels: boolean;
  spineOnly: boolean;
};

const DEFAULT_TOGGLES: Toggles = {
  regions: false,
  depth: false,
  isolated: true,
  tier: true,
  labels: true,
  spineOnly: false,
};

function regionHue(regionId: string): string {
  let h = 0;
  for (let i = 0; i < regionId.length; i += 1) {
    h = (h * 31 + regionId.charCodeAt(i)) >>> 0;
  }
  return REGION_HUES[h % REGION_HUES.length];
}

export function ArrangementLabPage() {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);

  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [graphId, setGraphId] = useState<string>("");
  const [lens, setLens] = useState<string>("canonical");
  const [map, setMap] = useState<GraphMap | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [toggles, setToggles] = useState<Toggles>(DEFAULT_TOGGLES);
  const [hidden, setHidden] = useState<Set<EdgeType>>(new Set());
  const [selected, setSelected] = useState<MapNode | null>(null);

  const togglesRef = useRef(toggles);
  togglesRef.current = toggles;
  const mapRef = useRef<GraphMap | null>(map);
  mapRef.current = map;

  useEffect(() => {
    const ac = new AbortController();
    listGraphs(ac.signal)
      .then((list) => {
        setGraphs(list);
        const current = list.find((g) => g.is_current) ?? list[0];
        if (current) setGraphId(current.id);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => ac.abort();
  }, []);

  useEffect(() => {
    if (!graphId) return;
    const ac = new AbortController();
    setLoading(true);
    setError("");
    fetchMap(graphId, ac.signal, lens)
      .then((m) => {
        setMap(m);
        setSelected(null);
        if (m.lens && m.lens !== lens) setLens(m.lens);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [graphId, lens]);

  const isolatedSet = useMemo(() => new Set(map?.gutter ?? []), [map]);

  const data: GraphData = useMemo(() => {
    if (!map) return { nodes: [], edges: [] };
    const nodes: NodeData[] = map.nodes.map((n) => ({
      id: n.id,
      // Coordinates come from the server. This page never moves a node.
      style: { x: n.x, y: n.y },
      data: {
        label: n.label,
        anchor: n.semantic_anchor,
        regionId: n.region_id ?? "",
        depth: n.depth ?? 0,
        tier: n.tier ?? null,
        isolated: isolatedSet.has(n.id),
      },
    }));
    const edges: EdgeData[] = map.edges
      .filter((e) => !hidden.has(e.type))
      .map((e, i) => ({
        id: `${e.source}->${e.target}:${e.type}:${i}`,
        source: e.source,
        target: e.target,
        data: { kind: e.type.toLowerCase(), label: e.label, type: e.type },
      }));
    return { nodes, edges };
  }, [map, hidden, isolatedSet]);

  const diameterOf = useCallback((datum: NodeData) => {
    if (!togglesRef.current.tier) return GEO.nodeDiameter * 0.7;
    const tier = datum.data?.tier as string | null;
    const scale = tier
      ? TIER_SCALE[tier] ?? TIER_SCALE_UNKNOWN
      : TIER_SCALE_UNKNOWN;
    return GEO.nodeDiameter * scale;
  }, []);

  const nodeOptions = useMemo(
    () => ({
      type: "circle" as const,
      style: {
        size: diameterOf,
        fill: (datum: NodeData) => {
          const t = togglesRef.current;
          if (t.isolated && datum.data?.isolated) return ISOLATED;
          if (t.regions) {
            const region = String(datum.data?.regionId ?? "");
            return region
              ? mixHex(DNA.node, regionHue(region), REGION_MIX)
              : DNA.node;
          }
          return DNA.node;
        },
        stroke: DNA.node,
        lineWidth: GEO.nodeLine,
        halo: false,
        badge: false,
        // The label sits inside the node — that is the language, not a variant.
        labelText: (datum: NodeData) =>
          togglesRef.current.labels ? String(datum.data?.label ?? "") : "",
        labelFill: DNA.nodeLabel,
        labelFontFamily: FONT_SANS_FAMILY,
        labelFontSize: GEO.labelSize,
        labelFontWeight: 400 as const,
        labelLineHeight: GEO.labelSize * 1.15,
        labelPlacement: "center" as const,
        labelWordWrap: true,
        labelMaxWidth: (datum: NodeData) =>
          diameterOf(datum) * (GEO.labelMaxWidth / 100),
        labelMaxLines: 2,
        labelTextOverflow: "ellipsis" as const,
        cursor: "pointer" as const,
      },
      animation: {
        // Positions are server-owned and stable, so there is nothing to settle.
        enter: false as const,
        update: false as const,
        exit: false as const,
      },
    }),
    [diameterOf],
  );

  const edgeOptions = useMemo(
    () => ({
      type: AMBIENT_LINKAGE_EDGE,
      style: {
        edgeKind: (datum: EdgeData) => linkageEdgeKind(datum),
        pointerEvents: "none" as const,
        stroke: DNA.filament,
        lineWidth: GEO.edgeWidth,
        opacity: (datum: EdgeData) => {
          const type = String(datum.data?.type ?? "") as EdgeType;
          if (togglesRef.current.spineOnly && !SPINE_TYPES.has(type)) {
            return 0.08;
          }
          return GEO.edgeOpacity;
        },
        lineCap: "round" as const,
        lineJoin: "round" as const,
        endArrow: (datum: EdgeData) => isDirectedKind(linkageEdgeKind(datum)),
        endArrowType: "triangle" as const,
        endArrowSize: (datum: EdgeData) =>
          arrowSizeForKind(linkageEdgeKind(datum)),
        endArrowFill: DNA.filament,
        labelText: "",
      },
      animation: {
        enter: false as const,
        update: false as const,
        exit: false as const,
        state: [
          {
            fields: ["opacity", "lineWidth"],
            duration: MOTION_DURATION_MS.hold,
            easing: MOTION_SPINE.settle.css,
          },
        ],
      },
    }),
    [],
  );

  useEffect(() => {
    if (!stageRef.current) return;
    ensureAmbientLinkageEdgeRegistered();
    const graph = new Graph({
      container: stageRef.current,
      autoResize: true,
      // No layout key at all: the server already decided. Handing G6 a layout
      // here would silently take the decision back into the browser.
      behaviors: ["drag-canvas", "zoom-canvas"],
      node: nodeOptions,
      edge: edgeOptions,
      data: { nodes: [], edges: [] },
    });
    graphRef.current = graph;
    graph.on("node:click", (event: IElementEvent) => {
      const id = event.target?.id;
      const found = mapRef.current?.nodes.find((n) => n.id === id) ?? null;
      setSelected(found);
    });
    graph.render().catch(() => {});
    return () => {
      graphRef.current = null;
      graph.destroy();
    };
  }, [nodeOptions, edgeOptions]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    let live = true;
    graph.setData(data);
    // A render settling after unmount (or an HMR remount) would otherwise
    // reject against a destroyed instance.
    graph
      .render()
      .then(() => {
        if (live && !graph.destroyed) graph.fitView();
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [data]);

  // Toggles are read through refs inside the style mappers, so a change only
  // needs a redraw — the data and the coordinates are untouched.
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    graph.draw().catch(() => {});
  }, [toggles]);

  const setToggle = useCallback((key: keyof Toggles) => {
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const toggleEdgeType = useCallback((type: EdgeType) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  const metrics = map?.layout_metrics;
  const lenses = map?.available_lenses ?? ["canonical"];
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of map?.edges ?? []) counts[e.type] = (counts[e.type] ?? 0) + 1;
    return counts;
  }, [map]);

  const depths = useMemo(() => {
    if (!map || !toggles.depth) return [];
    return [...new Set(map.nodes.map((n) => n.depth ?? 0))].sort(
      (a, b) => a - b,
    );
  }, [map, toggles.depth]);

  return (
    <div className="arr">
      <header className="arr__header">
        <div>
          <p className="arr__nav">
            <a href="#/explorations">Explorations</a> · Arrangement
          </p>
          <h1>Arrangement</h1>
          <p>
            The server decides where every node goes and persists it, so the map
            is a place rather than a picture. This page only renders those
            coordinates — there is no layout in the browser. Switch the lens to
            ask the graph a different question; switch the read-outs to see what
            the arrangement was built from.
          </p>
        </div>
        <div className="arr__header-actions">
          <span>Lens</span>
          {lenses.map((name) => (
            <button
              key={name}
              type="button"
              className={name === lens ? "is-on" : ""}
              title={LENS_HINTS[name] ?? ""}
              onClick={() => setLens(name)}
            >
              {LENS_LABELS[name] ?? name}
            </button>
          ))}
        </div>
      </header>

      <div className="arr__body">
        <aside className="arr__controls">
          <section>
            <h2>Graph</h2>
            <select value={graphId} onChange={(e) => setGraphId(e.target.value)}>
              {graphs.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.label} · {g.node_count ?? "?"}n
                </option>
              ))}
            </select>
            <p className="arr__copy">
              Every graph the server can open. Layout is cached per graph, so
              the second visit is the same map as the first.
            </p>
          </section>

          <section>
            <h2>Read-outs</h2>
            <Toggle
              label="Regions"
              on={toggles.regions}
              onChange={() => setToggle("regions")}
              hint="Tint by the spine's region root — what the backbone decomposed the graph into."
            />
            <Toggle
              label="Isolated"
              on={toggles.isolated}
              onChange={() => setToggle("isolated")}
              hint="Nothing connects to these. A fact about the graph's shape — not a verdict; only a query can be governed or ungoverned."
            />
            <Toggle
              label="Tier sizing"
              on={toggles.tier}
              onChange={() => setToggle("tier")}
              hint="Server-decided size band. Unmeasured renders neutral, never smallest."
            />
            <Toggle
              label="Depth"
              on={toggles.depth}
              onChange={() => setToggle("depth")}
              hint="How many levels the arrangement ranked."
            />
            <Toggle
              label="Labels"
              on={toggles.labels}
              onChange={() => setToggle("labels")}
            />
            <Toggle
              label="Spine only"
              on={toggles.spineOnly}
              onChange={() => setToggle("spineOnly")}
              hint="Fade everything the spine did not follow. CONTAINS and LEADSTO decide depth; EXPRESSES and NEARTO never do."
            />
          </section>

          <section>
            <h2>Relationships</h2>
            <p className="arr__copy">
              Hide a type to see what the arrangement would have to work with
              without it.
            </p>
            {EDGE_TYPES.map((type) => (
              <Toggle
                key={type}
                label={`${type} · ${typeCounts[type] ?? 0}`}
                on={!hidden.has(type)}
                onChange={() => toggleEdgeType(type)}
              />
            ))}
          </section>
        </aside>

        <main className="arr__stage-shell">
          {error ? (
            <p className="arr__state arr__state--error">
              {error}. This page needs the live backend — open it with{" "}
              <code>?api=live&amp;apiToken=devtoken</code>.
            </p>
          ) : null}
          {loading ? <p className="arr__state">Reading the map…</p> : null}
          <div className="arr__stage" ref={stageRef}>
            {depths.length ? (
              <div className="arr__depth" aria-hidden>
                {depths.map((d) => (
                  <span key={d}>depth {d}</span>
                ))}
              </div>
            ) : null}
          </div>
        </main>

        <aside className="arr__readout">
          <section>
            <h2>This arrangement</h2>
            <dl>
              <Row label="lens" value={map?.lens ?? "—"} />
              <Row label="nodes" value={map?.node_count ?? "—"} />
              <Row label="edges" value={map?.edge_count ?? "—"} />
              <Row label="isolated" value={map?.gutter?.length ?? 0} />
              <Row
                label="topology"
                value={map?.topology_version?.slice(0, 10) ?? "—"}
              />
            </dl>
            <p className="arr__copy">
              Topology is the layout cache key. It only moves when nodes or
              edges move — not when a label or a centrality score is rewritten.
            </p>
          </section>

          <section>
            <h2>Quality</h2>
            <dl>
              <Row label="crossings" value={metrics?.crossings ?? "—"} />
              <Row label="overlap" value={metrics?.overlap ?? "—"} />
              <Row label="aspect" value={metrics?.aspect ?? "—"} />
              <Row label="ink" value={metrics?.ink?.toFixed(0) ?? "—"} />
              <Row
                label="delta"
                value={
                  map?.layout_delta === null || map?.layout_delta === undefined
                    ? "unmeasured"
                    : map.layout_delta
                }
              />
            </dl>
            <p className="arr__copy">
              Delta is how far the average node moved when the layout was last
              rebuilt. <strong>Unmeasured</strong> means there was no previous
              arrangement to compare against — it does not mean nothing moved.
            </p>
            {metrics && metrics.aspect > 6 ? (
              <p className="arr__flag">
                Aspect {metrics.aspect}. A shallow, wide graph gives every leaf
                its own column, so it renders as a ribbon. Known open defect —
                see §9.2 of the arrangement doc.
              </p>
            ) : null}
          </section>

          <section>
            <h2>Selected</h2>
            {selected ? (
              <dl>
                <Row label="id" value={selected.id} />
                <Row label="tier" value={selected.tier ?? "unmeasured"} />
                <Row label="depth" value={selected.depth ?? "—"} />
                <Row label="region" value={selected.region_id || "—"} />
                <Row
                  label="betweenness"
                  value={
                    selected.betweenness === null
                      ? "unmeasured"
                      : selected.betweenness.toFixed(4)
                  }
                />
              </dl>
            ) : (
              <p className="arr__copy">Click a node.</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

function Toggle({
  label,
  on,
  onChange,
  hint,
}: {
  label: string;
  on: boolean;
  onChange: () => void;
  hint?: string;
}) {
  return (
    <label className="arr__toggle">
      <input type="checkbox" checked={on} onChange={onChange} />
      <span>{label}</span>
      {hint ? <em>{hint}</em> : null}
    </label>
  );
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{String(value)}</dd>
    </>
  );
}
