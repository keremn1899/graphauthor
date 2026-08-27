import {
  Graph,
  type EdgeData,
  type GraphData,
  type NodeData,
} from "@antv/g6";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  fetchMap,
  listGraphs,
  type GraphMap,
  type GraphSummary,
  type MapNode,
} from "../api/graph";
import { FONT_SANS_FAMILY } from "../styles/typography";
import type { MotionPlans } from "../styles/motion";
import { g6StateMotion } from "../styles/motionG6";

type LodPalette = {
  canvas: string;
  surface: string;
  node: string;
  nodeLabel: string;
  filament: string;
  muted: string;
};

type RegionalMassLodSectionProps = {
  palette: LodPalette;
  nodeDiameter: number;
  labelSize: number;
  labelMaxWidth: number;
  edgeWidth: number;
  edgeOpacity: number;
  motion: MotionPlans;
};

type RegionalModel = {
  representativeByNode: Map<string, string>;
  membersByRepresentative: Map<string, MapNode[]>;
  rankByNode: Map<string, number>;
};

type ViewCounts = {
  visible: number;
  fields: number;
  represented: number;
  regionalEdges: number;
};

const PRIORITY = [
  "deep_space_operations",
  "corpus_lotr",
  "corpus_agreements",
];

function clamp(value: number, min = 0, max = 1) {
  return Math.max(min, Math.min(max, value));
}

function smoothstep(value: number) {
  const x = clamp(value);
  return x * x * (3 - 2 * x);
}

function graphPriority(graph: GraphSummary) {
  const exact = PRIORITY.indexOf(graph.id);
  if (exact >= 0) return exact;
  const label = `${graph.id} ${graph.label}`.toLowerCase();
  if (label.includes("deep_space") || label.includes("deep space")) return 0;
  if (label.includes("lotr")) return 1;
  if (label.includes("agreement")) return 2;
  return 10;
}

function importance(node: MapNode) {
  const tier = node.tier === "landmark" ? 3 : node.tier === "hub" ? 2 : 1;
  return tier * 10 + node.centrality_score + (node.betweenness ?? 0);
}

/**
 * A region is the first containment child below a graph root. This is more
 * useful for visual LOD than blindly using the ultimate spine root: a corpus
 * with one handbook root would otherwise become one enormous field.
 */
function buildRegionalModel(map: GraphMap): RegionalModel {
  const parent = new Map<string, string>();
  for (const edge of map.edges) {
    if (edge.type === "CONTAINS" && !parent.has(edge.target)) {
      parent.set(edge.target, edge.source);
    }
  }

  const regionalRoot = (nodeId: string) => {
    const chain = [nodeId];
    const seen = new Set(chain);
    let cursor = nodeId;
    while (parent.has(cursor)) {
      const next = parent.get(cursor)!;
      if (seen.has(next)) break;
      chain.push(next);
      seen.add(next);
      cursor = next;
    }
    // Last item is the graph root; its child is the operational region.
    return chain.length >= 2 ? chain[chain.length - 2] : nodeId;
  };

  const nodeById = new Map(map.nodes.map((node) => [node.id, node]));
  const groups = new Map<string, MapNode[]>();
  for (const node of map.nodes) {
    const key = regionalRoot(node.id) || node.region_id || node.id;
    const members = groups.get(key) ?? [];
    members.push(node);
    groups.set(key, members);
  }

  const representativeByNode = new Map<string, string>();
  const membersByRepresentative = new Map<string, MapNode[]>();
  const rankByNode = new Map<string, number>();

  for (const [candidate, members] of groups) {
    const ordered = [...members].sort((a, b) => {
      if (a.id === candidate) return -1;
      if (b.id === candidate) return 1;
      const delta = importance(b) - importance(a);
      return delta || a.id.localeCompare(b.id);
    });
    const representative =
      nodeById.has(candidate) ? candidate : ordered[0]?.id;
    if (!representative) continue;
    membersByRepresentative.set(representative, ordered);
    ordered.forEach((node, index) => {
      representativeByNode.set(node.id, representative);
      rankByNode.set(node.id, index);
    });
  }

  return { representativeByNode, membersByRepresentative, rankByNode };
}

function foldAmount(
  node: MapNode,
  representative: string,
  members: MapNode[],
  rank: number,
  abstraction: number,
) {
  if (node.id === representative || members.length <= 1) return 0;
  const rankPosition = rank / Math.max(1, members.length - 1);
  // Peripheral concepts depart first. Hubs and landmarks hold until the field
  // is already legible, so abstraction grows as a region rather than a wipe.
  const tierDelay =
    node.tier === "landmark" ? 0.18 : node.tier === "hub" ? 0.09 : 0;
  const start = 0.12 + (1 - rankPosition) * 0.5 + tierDelay;
  return smoothstep((abstraction - start) / 0.24);
}

function regionalView(
  map: GraphMap,
  model: RegionalModel,
  abstraction: number,
  fieldScale: number,
  palette: LodPalette,
  nodeDiameter: number,
  edgeWidth: number,
  edgeOpacity: number,
): { data: GraphData; counts: ViewCounts } {
  const nodesById = new Map(map.nodes.map((node) => [node.id, node]));
  const fold = new Map<string, number>();
  const representedMass = new Map<string, number>();

  for (const node of map.nodes) {
    const representative = model.representativeByNode.get(node.id) ?? node.id;
    const members = model.membersByRepresentative.get(representative) ?? [node];
    const amount = foldAmount(
      node,
      representative,
      members,
      model.rankByNode.get(node.id) ?? 0,
      abstraction,
    );
    fold.set(node.id, amount);
    representedMass.set(
      representative,
      (representedMass.get(representative) ?? 1) + amount,
    );
  }

  const nodes: NodeData[] = [];
  for (const [representative, members] of model.membersByRepresentative) {
    const home = nodesById.get(representative);
    if (!home) continue;
    const mass = representedMass.get(representative) ?? 1;
    const hiddenMass = Math.max(0, mass - 1);
    const mantleDiameter =
      nodeDiameter +
      10 +
      nodeDiameter * (Math.sqrt(mass) - 1) * fieldScale;
    nodes.push({
      id: `__mass_field__${representative}`,
      data: {
        kind: "mass-field",
        labelText: "",
        size: mantleDiameter,
        opacity: hiddenMass <= 0.005 ? 0 : clamp(0.08 + hiddenMass * 0.018, 0, 0.28),
        fill: palette.filament,
        stroke: palette.filament,
        lineWidth: 1,
        zIndex: 0,
      },
      style: { x: home.x, y: home.y },
    });

    for (const node of members) {
      const amount = fold.get(node.id) ?? 0;
      const presence = 1 - amount;
      const x = node.x + (home.x - node.x) * amount;
      const y = node.y + (home.y - node.y) * amount;
      const isRepresentative = node.id === representative;
      const representativeDiameter = isRepresentative
        ? nodeDiameter *
          (1 + abstraction * 0.22 * Math.max(0, Math.sqrt(mass) - 1))
        : nodeDiameter;
      nodes.push({
        id: node.id,
        data: {
          kind: "concept",
          isAbstractRepresentative: isRepresentative && abstraction > 0.32,
          labelText:
            isRepresentative || presence > 0.72 ? node.label || node.id : "",
          size: representativeDiameter,
          opacity: isRepresentative ? 1 : presence,
          fill: palette.node,
          stroke: palette.node,
          lineWidth: 1,
          zIndex: 2,
        },
        style: { x, y },
      });
    }
  }

  const edges: EdgeData[] = [];
  const regional = new Map<
    string,
    { source: string; target: string; type: string; count: number }
  >();
  map.edges.forEach((edge, index) => {
    const sourcePresence = 1 - (fold.get(edge.source) ?? 0);
    const targetPresence = 1 - (fold.get(edge.target) ?? 0);
    edges.push({
      id: `detail:${index}:${edge.source}:${edge.target}:${edge.type}`,
      source: edge.source,
      target: edge.target,
      data: {
        opacity: edgeOpacity * sourcePresence * targetPresence,
        width: edgeWidth,
        stroke: palette.filament,
        zIndex: 1,
      },
    });

    const source = model.representativeByNode.get(edge.source) ?? edge.source;
    const target = model.representativeByNode.get(edge.target) ?? edge.target;
    if (source === target) return;
    const key = `${source}:${target}:${edge.type}`;
    const aggregate = regional.get(key);
    if (aggregate) aggregate.count += 1;
    else regional.set(key, { source, target, type: edge.type, count: 1 });
  });

  const regionalPresence = smoothstep((abstraction - 0.28) / 0.42);
  for (const [key, edge] of regional) {
    edges.push({
      id: `regional:${key}`,
      source: edge.source,
      target: edge.target,
      data: {
        opacity:
          regionalPresence *
          clamp(edgeOpacity * (0.75 + Math.log2(edge.count + 1) * 0.18), 0, 0.9),
        width: edgeWidth + Math.min(1.2, Math.log2(edge.count + 1) * 0.22),
        stroke: palette.filament,
        zIndex: 1,
      },
    });
  }

  const visible = map.nodes.filter((node) => (fold.get(node.id) ?? 0) < 0.92).length;
  const represented = Math.round(
    map.nodes.reduce(
      (sum, node) =>
        // Every concept is either still present as itself or has transferred
        // exactly the complementary fraction into its regional mantle.
        sum + (1 - (fold.get(node.id) ?? 0)) + (fold.get(node.id) ?? 0),
      0,
    ),
  );
  return {
    data: { nodes, edges },
    counts: {
      visible,
      fields: [...representedMass.values()].filter((mass) => mass > 1.02).length,
      represented,
      regionalEdges: regional.size,
    },
  };
}

export function RegionalMassLodSection({
  palette,
  nodeDiameter,
  labelSize,
  labelMaxWidth,
  edgeWidth,
  edgeOpacity,
  motion,
}: RegionalMassLodSectionProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const renderedRef = useRef(false);
  const previousAbstractionRef = useRef(0);
  const detailZoomRef = useRef<number | null>(null);
  const linkedZoomRef = useRef(true);
  const suppressZoomLinkRef = useRef(false);
  const zoomTimerRef = useRef<number | null>(null);

  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [graphId, setGraphId] = useState("");
  const [lens, setLens] = useState("canonical");
  const [map, setMap] = useState<GraphMap | null>(null);
  const [abstraction, setAbstraction] = useState(0);
  const [fieldScale, setFieldScale] = useState(0.9);
  const [linkedZoom, setLinkedZoom] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [drawMs, setDrawMs] = useState<number | null>(null);

  linkedZoomRef.current = linkedZoom;

  useEffect(() => {
    const abort = new AbortController();
    listGraphs(abort.signal)
      .then((available) => {
        const sorted = [...available].sort(
          (a, b) =>
            graphPriority(a) - graphPriority(b) ||
            (b.node_count ?? 0) - (a.node_count ?? 0),
        );
        setGraphs(sorted);
        setGraphId((current) => current || sorted[0]?.id || "");
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
    return () => abort.abort();
  }, []);

  useEffect(() => {
    if (!graphId) return;
    const abort = new AbortController();
    setLoading(true);
    setError("");
    detailZoomRef.current = null;
    fetchMap(graphId, abort.signal, lens)
      .then((next) => {
        setMap(next);
        setAbstraction(0);
        previousAbstractionRef.current = 0;
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
    return () => abort.abort();
  }, [graphId, lens]);

  const model = useMemo(
    () => (map ? buildRegionalModel(map) : null),
    [map],
  );
  const view = useMemo(
    () =>
      map && model
        ? regionalView(
            map,
            model,
            abstraction,
            fieldScale,
            palette,
            nodeDiameter,
            edgeWidth,
            edgeOpacity,
          )
        : null,
    [
      abstraction,
      edgeOpacity,
      edgeWidth,
      fieldScale,
      labelMaxWidth,
      labelSize,
      map,
      model,
      nodeDiameter,
      palette,
    ],
  );

  useEffect(() => {
    if (!stageRef.current) return;
    const graph = new Graph({
      container: stageRef.current,
      autoResize: true,
      zoomRange: [0.02, 4],
      behaviors: [
        "drag-canvas",
        "zoom-canvas",
        {
          key: "lod-readable-representatives",
          type: "fix-element-size",
          enable: true,
          nodeFilter: (datum: NodeData) =>
            Boolean(datum.data?.isAbstractRepresentative),
          node: { shape: "label" },
        },
      ],
      data: { nodes: [], edges: [] },
      node: {
        type: "circle",
        style: {
          size: (datum: NodeData) => Number(datum.data?.size ?? nodeDiameter),
          fill: (datum: NodeData) => String(datum.data?.fill ?? palette.node),
          stroke: (datum: NodeData) => String(datum.data?.stroke ?? palette.node),
          lineWidth: (datum: NodeData) => Number(datum.data?.lineWidth ?? 1),
          opacity: (datum: NodeData) => Number(datum.data?.opacity ?? 1),
          zIndex: (datum: NodeData) => Number(datum.data?.zIndex ?? 1),
          labelText: (datum: NodeData) => String(datum.data?.labelText ?? ""),
          labelFill: palette.nodeLabel,
          labelFontFamily: FONT_SANS_FAMILY,
          labelFontSize: labelSize,
          labelFontWeight: 400,
          labelLineHeight: labelSize * 1.12,
          labelPlacement: "center",
          labelWordWrap: true,
          labelMaxWidth: nodeDiameter * (labelMaxWidth / 100),
          labelMaxLines: 2,
          labelTextOverflow: "ellipsis",
          pointerEvents: (datum: NodeData) =>
            datum.data?.kind === "mass-field" ? "none" : "auto",
        },
        animation: {
          enter: false,
          exit: false,
          update: [
            g6StateMotion(motion.absorb, {
              fields: ["x", "y", "opacity", "size"],
            }),
          ],
        },
      },
      edge: {
        type: "line",
        style: {
          stroke: (datum: EdgeData) =>
            String(datum.data?.stroke ?? palette.filament),
          lineWidth: (datum: EdgeData) => Number(datum.data?.width ?? edgeWidth),
          opacity: (datum: EdgeData) => Number(datum.data?.opacity ?? 0),
          zIndex: (datum: EdgeData) => Number(datum.data?.zIndex ?? 1),
          pointerEvents: "none",
        },
        animation: {
          enter: false,
          exit: false,
          update: [
            g6StateMotion(motion.absorb, {
              fields: ["opacity", "lineWidth"],
            }),
          ],
        },
      },
    });
    graphRef.current = graph;
    graph.on("aftertransform", () => {
      if (
        suppressZoomLinkRef.current ||
        !linkedZoomRef.current ||
        detailZoomRef.current === null
      ) return;
      if (zoomTimerRef.current !== null) window.clearTimeout(zoomTimerRef.current);
      zoomTimerRef.current = window.setTimeout(() => {
        const detailZoom = detailZoomRef.current;
        if (!detailZoom || graph.destroyed) return;
        const zoom = graph.getZoom();
        setAbstraction(
          clamp(Math.log(detailZoom / Math.max(0.001, zoom)) / Math.log(3)),
        );
      }, 90);
    });
    return () => {
      if (zoomTimerRef.current !== null) window.clearTimeout(zoomTimerRef.current);
      graphRef.current = null;
      graph.destroy();
    };
  }, [
    edgeWidth,
    labelMaxWidth,
    labelSize,
    motion.absorb,
    nodeDiameter,
    palette,
  ]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed || !view || !map) return;
    const absorbing = abstraction >= previousAbstractionRef.current;
    const plan = absorbing ? motion.absorb : motion.emit;
    graph.setNode({
      type: "circle",
      style: {
        size: (datum: NodeData) => Number(datum.data?.size ?? nodeDiameter),
        fill: (datum: NodeData) => String(datum.data?.fill ?? palette.node),
        stroke: (datum: NodeData) => String(datum.data?.stroke ?? palette.node),
        lineWidth: (datum: NodeData) => Number(datum.data?.lineWidth ?? 1),
        opacity: (datum: NodeData) => Number(datum.data?.opacity ?? 1),
        zIndex: (datum: NodeData) => Number(datum.data?.zIndex ?? 1),
        labelText: (datum: NodeData) => String(datum.data?.labelText ?? ""),
        labelFill: palette.nodeLabel,
        labelFontFamily: FONT_SANS_FAMILY,
        labelFontSize: labelSize,
        labelFontWeight: 400,
        labelLineHeight: labelSize * 1.12,
        labelPlacement: "center",
        labelWordWrap: true,
        labelMaxWidth: nodeDiameter * (labelMaxWidth / 100),
        labelMaxLines: 2,
        labelTextOverflow: "ellipsis",
        pointerEvents: (datum: NodeData) =>
          datum.data?.kind === "mass-field" ? "none" : "auto",
      },
      animation: {
        enter: false,
        exit: false,
        update: [
          g6StateMotion(plan, {
            fields: ["x", "y", "opacity", "size"],
          }),
        ],
      },
    });
    graph.setEdge({
      type: "line",
      style: {
        stroke: (datum: EdgeData) =>
          String(datum.data?.stroke ?? palette.filament),
        lineWidth: (datum: EdgeData) => Number(datum.data?.width ?? edgeWidth),
        opacity: (datum: EdgeData) => Number(datum.data?.opacity ?? 0),
        zIndex: (datum: EdgeData) => Number(datum.data?.zIndex ?? 1),
        pointerEvents: "none",
      },
      animation: {
        enter: false,
        exit: false,
        update: [
          g6StateMotion(plan, {
            fields: ["opacity", "lineWidth"],
          }),
        ],
      },
    });
    graph.setData(view.data);
    const started = performance.now();
    const firstRender = !renderedRef.current;
    const operation = firstRender ? graph.render() : graph.draw();
    renderedRef.current = true;
    operation
      .then(async () => {
        if (graph.destroyed) return;
        setDrawMs(performance.now() - started);
        if (detailZoomRef.current === null) {
          await graph.fitView({ when: "always", direction: "both" }, false);
          detailZoomRef.current = graph.getZoom();
        } else if (abstraction > 0.32) {
          // Lets G6's native fix-element-size behavior re-evaluate the nodes
          // that have just become abstract representatives.
          suppressZoomLinkRef.current = true;
          await graph.zoomTo(graph.getZoom(), false);
          suppressZoomLinkRef.current = false;
        }
      })
      .catch(() => {});
    previousAbstractionRef.current = abstraction;
  }, [
    abstraction,
    edgeWidth,
    labelMaxWidth,
    labelSize,
    map,
    motion,
    nodeDiameter,
    palette,
    view,
  ]);

  const regionCount = model?.membersByRepresentative.size ?? 0;

  return (
    <section
      className="gdna-lod"
      style={{
        "--lod-canvas": palette.canvas,
        "--lod-surface": palette.surface,
        "--lod-ink": palette.node,
        "--lod-muted": palette.muted,
        "--lod-filament": palette.filament,
      } as React.CSSProperties}
    >
      <header className="gdna-lod__header">
        <div>
          <p>Regional mass field · new prototype</p>
          <h2>Detail remains democratic; distance creates abstraction</h2>
        </div>
        <p>
          Equal cores are the resolved concept layer. A surviving regional core
          grows only after abstraction begins; the translucent mantle remains
          separate field area and carries the larger square-root mass signal.
          Zoom out to absorb; zoom in to emit.
        </p>
      </header>

      <div className="gdna-lod__body">
        <aside className="gdna-lod__controls">
          <section>
            <h3>Construction graph</h3>
            <select value={graphId} onChange={(event) => setGraphId(event.target.value)}>
              {graphs.map((graph) => (
                <option key={graph.id} value={graph.id}>
                  {graph.label} · {graph.node_count ?? "?"}n
                </option>
              ))}
            </select>
            <label>
              <span>Server lens</span>
              <select value={lens} onChange={(event) => setLens(event.target.value)}>
                {(map?.available_lenses ?? ["canonical", "causal"]).map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
            <p>
              Deep-space is the 109-node construction run. LOTR and Agreements
              remain useful small baselines.
            </p>
          </section>

          <section>
            <h3>Distance</h3>
            <label>
              <span>
                Abstraction <output>{Math.round(abstraction * 100)}%</output>
              </span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={abstraction}
                onChange={(event) => setAbstraction(Number(event.target.value))}
              />
            </label>
            <label className="gdna-lod__check">
              <input
                type="checkbox"
                checked={linkedZoom}
                onChange={(event) => setLinkedZoom(event.target.checked)}
              />
              Link abstraction to zoom
            </label>
            <div className="gdna-lod__quick">
              <button type="button" onClick={() => setAbstraction(0)}>
                Full detail
              </button>
              <button type="button" onClick={() => setAbstraction(1)}>
                Regional
              </button>
            </div>
          </section>

          <section>
            <h3>Field geometry</h3>
            <label>
              <span>
                Mantle growth <output>{fieldScale.toFixed(2)}×</output>
              </span>
              <input
                type="range"
                min={0.25}
                max={1.8}
                step={0.05}
                value={fieldScale}
                onChange={(event) => setFieldScale(Number(event.target.value))}
              />
            </label>
            <div className="gdna-lod__legend" aria-label="Field geometry legend">
              <i />
              <span>
                <strong>core</strong> concept identity
                <strong>mantle</strong> absorbed regional mass
              </span>
            </div>
          </section>

          <section>
            <h3>Invariant read-out</h3>
            <dl>
              <div><dt>source</dt><dd>{map?.node_count ?? "—"} nodes</dd></div>
              <div><dt>visible</dt><dd>{view?.counts.visible ?? "—"}</dd></div>
              <div><dt>represented</dt><dd>{view?.counts.represented ?? "—"}</dd></div>
              <div><dt>fields</dt><dd>{view?.counts.fields ?? "—"} / {regionCount}</dd></div>
              <div><dt>regional bonds</dt><dd>{view?.counts.regionalEdges ?? "—"}</dd></div>
              <div><dt>draw</dt><dd>{drawMs === null ? "—" : `${drawMs.toFixed(1)} ms`}</dd></div>
            </dl>
            <p>
              Represented must equal source. A fold may change depiction; it
              may not drop matter.
            </p>
          </section>
        </aside>

        <div className="gdna-lod__stage-shell">
          {loading ? <p className="gdna-lod__state">Reading graph…</p> : null}
          {error ? (
            <p className="gdna-lod__state gdna-lod__state--error">
              {error}. Start the backend, then open this route with{" "}
              <code>?api=live&amp;apiToken=devtoken</code>.
            </p>
          ) : null}
          <div className="gdna-lod__stage" ref={stageRef} />
          <div className="gdna-lod__scale">
            <span>near · concepts</span>
            <i />
            <span>far · regions</span>
          </div>
        </div>
      </div>
    </section>
  );
}
