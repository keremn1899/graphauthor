import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Graph,
  type GraphData,
  type IElementEvent,
} from "@antv/g6";
import { createAmbientLodGraph } from "./ambientLodData";
import {
  AMBIENT_FOCUS_GROUP_IDS,
  applyAmbientSeamMode,
  type AmbientSeamMode,
} from "./ambientSeamModes";
import {
  AMBIENT_LINKAGE_EDGE,
  ensureAmbientLinkageEdgeRegistered,
} from "./ambientLinkageEdge";
import {
  buildAmbientEdgeState,
  buildAmbientEdgeStyle,
  buildAmbientNodeState,
  buildAmbientNodeStyle,
  clearAmbientHoverStates,
  emptyHoverBundle,
  hoverBundleFor,
  isAmbientFocusLitNode,
  prepareAmbientTrialData,
  rebindAmbientStyles,
  setAmbientFocusInverted,
  type HoverBundle,
} from "./ambientGraphEffects";
import { SelectionOrbiter, SELECTION_ORBITER_ID } from "./SelectionOrbiter";
import {
  type FrameStat,
  frameSummary,
  sampleFrames,
  verdictFor,
} from "./frameSampler";
import "./GraphAnimationsLabPage.css";

/**
 * Graph animation trials — ambient canvas visual language (hover bond,
 * charcoal focus, linkage-idle edges). A = product-cheap (animation:false);
 * B = prettier workaround.
 *
 * Graph look matches ambient defaults: Ø50, Jost @ 0.12×Ø / weight 400,
 * padding [48,44,48,44], dpr 2. The curated slice is 10 nodes, which is the
 * size at which an effect can be *seen*; `SCALES` is the size at which one can
 * be *decided*, because every animation here is free on ten nodes.
 *
 * Two measurements, not one. `drawMs` is how long a repaint took; the frame
 * sampler is whether the thing keeps a frame while it runs, and those come
 * apart — an effect that repaints in 8 ms on every frame and one that repaints
 * once are the same `drawMs` and completely different products. Both are on
 * screen together for that reason.
 *
 * And every verdict is against a do-nothing arm at the same size. Without it
 * the page called a mounted 2000-node canvas with no effect running "drops to
 * ~30", which is true of the canvas and says nothing about the animation.
 */

type TrialId =
  | "hover"
  | "selection"
  | "seam"
  | "editor"
  | "wait"
  | "load";

type Mode = "A" | "B";

type Perf = { drawMs: number; nodes: number; edges: number; label: string };

const TRIAL_MAX_NODES = 10;

/**
 * How many nodes the trial runs against.
 *
 * This page measured draw-ms on ten curated nodes, which is the right size to
 * *see* an effect and the wrong size to decide anything about it. Every
 * animation looks free on ten nodes. The question that actually gates shipping
 * one is whether it still holds a frame on a real map, and nothing here could
 * ask it — so the trials were pretty and the decision stayed a guess.
 *
 * 2000 matches `scripts/make_perf_graph.py`, so a verdict here and a
 * measurement on the product canvas are talking about the same size of graph.
 */
const SCALES = [10, 250, 1000, 2000] as const;
type Scale = (typeof SCALES)[number];

/**
 * Grow the curated fixture to `target` nodes, keeping its shape.
 *
 * Synthetic, and deliberately so: the point is to put a realistic *count* of
 * elements under the renderer, not to say anything true about a domain. Same
 * topology the perf fixture uses — a shallow containment forest with
 * cross-cutting edges, because crossings are what cost.
 */
function scaleTrialGraph(base: GraphData, target: Scale): GraphData {
  const nodes = [...(base.nodes ?? [])];
  const edges = [...(base.edges ?? [])];
  if (target <= nodes.length) return { nodes, edges };

  // Deterministic, so two runs of the same trial compare like with like.
  let seed = 7;
  const rand = (n: number) => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed % Math.max(1, n);
  };

  const template = nodes[0];
  const start = nodes.length;
  for (let i = start; i < target; i += 1) {
    const id = `syn-${i}`;
    nodes.push({
      ...structuredClone(template),
      id,
      data: {
        ...structuredClone(template?.data ?? {}),
        label: `Node ${i}`,
        is_landmark: false,
        importance: 0.15,
      },
    });
    edges.push({
      id: `syn-e-${i}`,
      source: String(nodes[rand(Math.max(1, Math.floor(i / 3) + 1))]?.id ?? id),
      target: id,
      data: { ...structuredClone(edges[0]?.data ?? {}) },
    });
  }
  const crossings = Math.floor(target / 2);
  for (let i = 0; i < crossings; i += 1) {
    const a = String(nodes[rand(nodes.length)]?.id ?? "");
    const b = String(nodes[rand(nodes.length)]?.id ?? "");
    if (!a || !b || a === b) continue;
    edges.push({
      id: `syn-x-${i}`,
      source: a,
      target: b,
      data: { ...structuredClone(edges[0]?.data ?? {}) },
    });
  }
  return { nodes, edges };
}

/** Curated ambient neighbourhood — focus seeds + checkout spine (≤10). */
const TRIAL_NODE_IDS = [
  "platform-core",
  "commerce",
  "service-boundary",
  "checkout-api",
  "order-ledger",
  "ownership-rule",
  "payment-gateway",
  "cart-service",
  "auth-service",
  "tenant-isolation",
] as const;

const TRIALS: { id: TrialId; title: string; a: string; b: string }[] = [
  {
    id: "hover",
    title: "Hover bond",
    a: "Ambient out/inn bond · setElementState(false)",
    b: "Same ambient bond · setElementState(true)",
  },
  {
    id: "selection",
    title: "Selection → orbiter",
    a: "Hollow MassNode moon · slow CSS orbit (14°/s)",
    b: "Same orbit · measure draw cost only",
  },
  {
    id: "seam",
    title: "Seam / focus group",
    a: "Idle ↔ focus-group via ambient annotateFocus + draw",
    b: "Same data swap · rebind styles + draw",
  },
  {
    id: "editor",
    title: "Node editor pane",
    a: "DOM/CSS slide — ambient graph untouched",
    b: "Slide + canvas dim (still no per-node tween)",
  },
  {
    id: "wait",
    title: "Job / wait",
    a: "DOM overlay on ambient stage",
    b: "Overlay only (no pulse-all — that anti-pattern is retired)",
  },
  {
    id: "load",
    title: "Graph load",
    a: "Ambient mini fixture · instant paint",
    b: "Ambient mini fixture · opacity enter",
  },
];

function pickTrialGraph(data: GraphData): GraphData {
  const want = new Set<string>(TRIAL_NODE_IDS);
  for (const id of AMBIENT_FOCUS_GROUP_IDS) want.add(id);
  const nodes = (data.nodes ?? [])
    .filter((n) => want.has(String(n.id)))
    .slice(0, TRIAL_MAX_NODES);
  const ids = new Set(nodes.map((n) => String(n.id)));
  const edges = (data.edges ?? []).filter(
    (e) => ids.has(String(e.source)) && ids.has(String(e.target)),
  );
  return { nodes, edges };
}

function trialGraphData(scale: Scale = 10): GraphData {
  return scaleTrialGraph(pickTrialGraph(createAmbientLodGraph()), scale);
}

export function GraphAnimationsLabPage() {
  const [trial, setTrial] = useState<TrialId>("hover");
  const [scale, setScale] = useState<Scale>(10);
  const [stat, setStat] = useState<FrameStat | null>(null);
  /** Same scale, nothing running. Without it a verdict is not a comparison. */
  const [baseline, setBaseline] = useState<FrameStat | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const [mode, setMode] = useState<Mode>("A");
  const [editorOpen, setEditorOpen] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [focusOn, setFocusOn] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [graphReady, setGraphReady] = useState(false);
  const [perf, setPerf] = useState<Perf>({
    drawMs: 0,
    nodes: 0,
    edges: 0,
    label: "—",
  });
  const [note, setNote] = useState(
    "Ambient effects — hover a node for SST bond labels.",
  );

  const stageRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const baseDataRef = useRef<GraphData | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const mountGenRef = useRef(0);
  const hoverCleanupRef = useRef<(() => void) | null>(null);

  const meta = useMemo(() => TRIALS.find((t) => t.id === trial)!, [trial]);

  const stampPerf = useCallback(
    (graph: Graph, drawMs: number, label: string) => {
      setPerf({
        drawMs,
        nodes: graph.getNodeData().length,
        edges: graph.getEdgeData().length,
        label,
      });
    },
    [],
  );

  const destroyGraph = useCallback(() => {
    hoverCleanupRef.current?.();
    hoverCleanupRef.current = null;
    setGraphReady(false);
    const g = graphRef.current;
    graphRef.current = null;
    if (g && !g.destroyed) g.destroy();
    if (stageRef.current) stageRef.current.replaceChildren();
  }, []);

  const paintFocus = useCallback(
    async (
      graph: Graph,
      nextData: GraphData,
      inverted: boolean,
      label: string,
    ) => {
      if (graph.destroyed) return;
      await clearAmbientHoverStates(graph);
      setAmbientFocusInverted(inverted);
      graph.setData(prepareAmbientTrialData(nextData));
      rebindAmbientStyles(graph);
      const t0 = performance.now();
      await graph.draw();
      stampPerf(
        graph,
        Math.round((performance.now() - t0) * 10) / 10,
        label,
      );
      setFocusOn(inverted);
    },
    [stampPerf],
  );

  const applySeam = useCallback(
    async (seam: AmbientSeamMode) => {
      const graph = graphRef.current;
      const base = baseDataRef.current;
      if (!graph || !base || graph.destroyed) return;
      const applied = applyAmbientSeamMode(base, seam);
      await paintFocus(
        graph,
        applied.data,
        applied.inverted,
        `seam ${seam}`,
      );
    },
    [paintFocus],
  );

  // Remount on trial / load size. Mode only remounts the load trial (enter anim).
  useEffect(() => {
    const gen = ++mountGenRef.current;
    let cancelled = false;

    setEditorOpen(false);
    setWaiting(false);
    setSelectedId(null);
    setFocusOn(false);
    setAmbientFocusInverted(false);

    const data = trialGraphData(scale);
    const animatedEnter = trial === "load" && mode === "B";

    (async () => {
      if (!stageRef.current) return;
      destroyGraph();
      if (cancelled || gen !== mountGenRef.current) return;

      ensureAmbientLinkageEdgeRegistered();
      setAmbientFocusInverted(false);

      const prepared = prepareAmbientTrialData(data);
      baseDataRef.current = prepared;

      const graph = new Graph({
        container: stageRef.current,
        autoFit: "view",
        // Match AmbientCanvasLabPage mount options.
        padding: [48, 44, 48, 44],
        zoomRange: [0.02, 64],
        devicePixelRatio: 2,
        animation: false,
        data: prepared,
        node: {
          type: "circle",
          style: buildAmbientNodeStyle(),
          state: buildAmbientNodeState(),
          animation: animatedEnter
            ? {
                enter: [
                  {
                    fields: ["opacity"],
                    duration: 280,
                    easing: "ease-out",
                  },
                ],
              }
            : false,
        },
        edge: {
          type: AMBIENT_LINKAGE_EDGE,
          style: buildAmbientEdgeStyle(),
          state: buildAmbientEdgeState(),
          animation: animatedEnter
            ? {
                enter: [
                  { fields: ["opacity"], duration: 220, easing: "ease-out" },
                ],
              }
            : false,
        },
        // Ambient freezes physics and uses drag-canvas + drag-element
        // (LOD dial owns wheel). Keep zoom-canvas here so the mini graph is usable.
        behaviors: ["drag-canvas", "zoom-canvas", "drag-element"],
      });

      if (cancelled || gen !== mountGenRef.current) {
        graph.destroy();
        return;
      }

      const t0 = performance.now();
      try {
        await graph.render();
        // Ambient default layout chip = radial (unitRadius 220, linkDistance 240).
        //
        // Only at the curated size. `radial` with `preventOverlap` is
        // superlinear, and asking it for 2000 nodes took **443 seconds** — so
        // the first attempt to measure an animation at scale spent seven
        // minutes measuring a layout instead, and reported nothing about the
        // effect at all.
        //
        // The product never pays this: its positions are computed server-side
        // and arrive with the map, so the canvas only ever draws. Grid is the
        // cheap stand-in for that here — the arrangement is meaningless above
        // the curated slice anyway, and what the trial is asking about is
        // whether the *effect* holds a frame over N elements.
        graph.setLayout(
          data.nodes && data.nodes.length > TRIAL_MAX_NODES
            ? { type: "grid", nodeSize: 50 + 16 * 2, animation: false }
            : {
                type: "radial",
                unitRadius: 220,
                linkDistance: 240,
                preventOverlap: true,
                nodeSize: 50 + 16 * 2,
                focusNode: "platform-core",
                animation: false,
              },
        );
        await graph.layout().catch(() => {});
        try {
          graph.stopLayout();
        } catch {
          /* ok */
        }
        await graph
          .fitView({ when: "always", direction: "both" }, false)
          .catch(() => {});
      } catch {
        if (!cancelled && gen === mountGenRef.current) {
          setNote("Graph render failed — see console.");
        }
        graph.destroy();
        return;
      }

      if (cancelled || gen !== mountGenRef.current || graph.destroyed) {
        if (!graph.destroyed) graph.destroy();
        return;
      }

      graphRef.current = graph;
      setGraphReady(true);
      stampPerf(
        graph,
        Math.round((performance.now() - t0) * 10) / 10,
        animatedEnter ? "render+enter" : "render instant",
      );

      const needsHover =
        trial === "hover" || trial === "selection" || trial === "editor";

      if (needsHover) {
        let hoverActive = emptyHoverBundle();
        let hoverRaf = 0;
        let hoverPending: HoverBundle | null = null;
        let hoverLeaveTimer = 0;
        let lastHoverStamp = 0;

        const clearHoverState = (id: string, state: string) =>
          graph.getElementState(id).filter((s) => s !== state);

        const syncNamedState = (
          states: Record<string, string[]>,
          prev: Set<string>,
          next: Set<string>,
          state: string,
          cleanAlso?: string[],
        ) => {
          for (const id of prev) {
            if (next.has(id)) continue;
            states[id] = clearHoverState(id, state);
          }
          for (const id of next) {
            const cur = states[id] ?? graph.getElementState(id);
            let cleaned = cur.filter((s) => s !== state);
            if (cleanAlso) {
              cleaned = cleaned.filter((s) => !cleanAlso.includes(s));
            }
            states[id] = cleaned.includes(state)
              ? cleaned
              : [...cleaned, state];
          }
        };

        const commitHover = async (next: HoverBundle) => {
          if (graph.destroyed || gen !== mountGenRef.current) return;
          const animate = modeRef.current === "B" && trial === "hover";
          const states: Record<string, string[]> = {};
          syncNamedState(states, hoverActive.out, next.out, "out", ["inn"]);
          syncNamedState(states, hoverActive.inn, next.inn, "inn", ["out"]);
          hoverActive = next;
          const t1 = performance.now();
          await graph.setElementState(states, animate).catch(() => {});
          // Throttle React perf updates — hover fires every frame otherwise.
          if (performance.now() - lastHoverStamp > 120) {
            lastHoverStamp = performance.now();
            stampPerf(
              graph,
              Math.round((performance.now() - t1) * 10) / 10,
              `hover bond (anim=${animate})`,
            );
          }
        };

        const scheduleHover = (next: HoverBundle) => {
          hoverPending = next;
          if (hoverRaf) return;
          hoverRaf = requestAnimationFrame(() => {
            hoverRaf = 0;
            const bundle = hoverPending ?? emptyHoverBundle();
            hoverPending = null;
            void commitHover(bundle);
          });
        };

        const onEnter = (event: IElementEvent) => {
          if (graph.destroyed) return;
          if (hoverLeaveTimer) {
            window.clearTimeout(hoverLeaveTimer);
            hoverLeaveTimer = 0;
          }
          const id = String(event.target?.id ?? "");
          if (!id || id === SELECTION_ORBITER_ID) return;
          if (isAmbientFocusLitNode(graph, id)) {
            scheduleHover(emptyHoverBundle());
            return;
          }
          scheduleHover(hoverBundleFor(graph, id));
        };

        const onLeave = () => {
          if (graph.destroyed) return;
          if (hoverLeaveTimer) window.clearTimeout(hoverLeaveTimer);
          hoverLeaveTimer = window.setTimeout(() => {
            hoverLeaveTimer = 0;
            scheduleHover(emptyHoverBundle());
          }, 60);
        };

        graph.on("node:pointerenter", onEnter);
        graph.on("node:pointerleave", onLeave);

        const onClick =
          trial === "selection"
            ? (event: IElementEvent) => {
                const id = String(event.target?.id ?? "");
                if (!id || id === SELECTION_ORBITER_ID) return;
                const t0 = performance.now();
                setSelectedId(id);
                stampPerf(
                  graph,
                  Math.round((performance.now() - t0) * 10) / 10,
                  `select ${id} (orbiter)`,
                );
                setNote(
                  `Selected ${id} — solid moon in graph space (scales with zoom).`,
                );
              }
            : trial === "editor"
              ? (event: IElementEvent) => {
                  const id = String(event.target?.id ?? "");
                  if (!id) return;
                  setSelectedId(id);
                  setEditorOpen(true);
                }
              : null;

        if (onClick) graph.on("node:click", onClick);

        hoverCleanupRef.current = () => {
          if (hoverRaf) cancelAnimationFrame(hoverRaf);
          if (hoverLeaveTimer) window.clearTimeout(hoverLeaveTimer);
          graph.off("node:pointerenter", onEnter);
          graph.off("node:pointerleave", onLeave);
          if (onClick) graph.off("node:click", onClick);
        };
      }

      if (trial === "hover") {
        setNote(
          modeRef.current === "A"
            ? "Hover — ambient SST bond labels (out/inn), animation:false."
            : "Hover — same ambient bond with animated state transitions.",
        );
      } else if (trial === "selection") {
        setNote(
          "Click a node — hollow moon circles it (trial MassNode orbit).",
        );
      } else if (trial === "seam") {
        setNote("Toggle focus-group seam — ambient annotateFocus + draw.");
      } else if (trial === "editor") {
        setNote("Click a node to open the editor shell. Hover still works.");
      } else if (trial === "wait") {
        setNote(
          "Start wait — DOM overlay only. Ambient graph frozen underneath.",
        );
      } else if (trial === "load") {
        setNote(
          animatedEnter
            ? `Opacity enter · N=${data.nodes?.length ?? 0} (ambient defaults).`
            : `Instant paint · N=${data.nodes?.length ?? 0} (ambient defaults).`,
        );
      }
    })();

    return () => {
      cancelled = true;
      if (gen === mountGenRef.current) destroyGraph();
    };
  }, [
    trial,
    // Load enter animation is the only mode-driven remount.
    trial === "load" ? mode : "stable",
    // Changing the node count rebuilds the graph — that is the whole point.
    scale,
    destroyGraph,
    stampPerf,
    paintFocus,
  ]);

  // Keep notes in sync when A/B flips without remount.
  useEffect(() => {
    if (trial === "hover") {
      setNote(
        mode === "A"
          ? "Hover — ambient SST bond labels (out/inn), animation:false."
          : "Hover — same ambient bond with animated state transitions.",
      );
    } else if (trial === "selection") {
      setNote(
        "Click a node — hollow moon circles it slowly (MassNode orbit, 14°/s).",
      );
    } else if (trial === "seam") {
      setNote(
        mode === "A"
          ? "Toggle focus-group seam — ambient annotateFocus + draw."
          : "Toggle — same seam with style rebind + draw.",
      );
    }
  }, [mode, trial]);

  return (
    <main className="galab">
      <header className="galab__header">
        <p className="galab__nav">
          <a href="#/explorations">Explorations</a>
          {" · "}
          <a href="#/explorations/components-lab">Components lab</a>
          {" · "}
          <a href="#/explorations/ambient-canvas">Ambient canvas</a>
        </p>
        <h1>Graph animations</h1>
        <p className="galab__lede">
          Trials use the <strong>ambient canvas</strong> look — Ø50, Jost
          0.12× / weight 400, charcoal focus. <strong>A</strong> is cheap;{" "}
          <strong>B</strong> is prettier. Pick a size, measure the{" "}
          <strong>baseline</strong> with nothing running, then measure the
          effect: the verdict is the difference, because at 2000 nodes a bare
          canvas drops the same frames an effect would be blamed for.
        </p>
      </header>

      <nav className="galab__trials" aria-label="Trials">
        {TRIALS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={trial === t.id ? "is-active" : ""}
            onClick={() => setTrial(t.id)}
          >
            {t.title}
          </button>
        ))}
      </nav>

      <div className="galab__toolbar">
        <div className="galab__modes" role="group" aria-label="Mode">
          <button
            type="button"
            className={mode === "A" ? "is-active" : ""}
            onClick={() => setMode("A")}
          >
            A · cheap
          </button>
          <button
            type="button"
            className={mode === "B" ? "is-active" : ""}
            onClick={() => setMode("B")}
          >
            B · prettier
          </button>
        </div>
        {/* Scale is the axis this page was missing. Every effect below is
            free on ten nodes; the only question worth asking is which ones
            are still free on a map somebody would actually open. */}
        <div className="galab__modes" role="group" aria-label="Nodes">
          {SCALES.map((n) => (
            <button
              type="button"
              key={n}
              className={scale === n ? "is-active" : ""}
              onClick={() => {
                setScale(n);
                setStat(null);
                // A baseline belongs to one size; carrying it across would
                // compare an effect here against a graph that is not this one.
                setBaseline(null);
              }}
            >
              {n}n
            </button>
          ))}
        </div>
        <button
          type="button"
          className="galab__measure"
          disabled={measuring || !graphReady}
          onClick={async () => {
            setMeasuring(true);
            setNote(`Sampling the do-nothing arm at ${scale} nodes…`);
            const s = await sampleFrames(1400);
            setBaseline({ ...s, scale });
            setMeasuring(false);
            setNote(
              `Baseline ${s.median} / ${s.p95} ms at ${scale}n — what this size costs with nothing running.`,
            );
          }}
        >
          {measuring ? "Sampling…" : "Measure baseline"}
        </button>
        <button
          type="button"
          className="galab__measure"
          disabled={measuring || !graphReady}
          onClick={async () => {
            setMeasuring(true);
            setNote(`Sampling frames at ${scale} nodes…`);
            const s = await sampleFrames(1400);
            setStat({ ...s, scale });
            setMeasuring(false);
            setNote(
              `${s.median} ms median · ${s.p95} ms p95 over ${s.frames} frames.`,
            );
          }}
        >
          {measuring ? "Sampling…" : "Measure effect"}
        </button>
        <p className="galab__perf" aria-live="polite">
          <strong>{perf.drawMs} ms</strong>
          <span>
            {perf.nodes}n · {perf.edges}e · {perf.label}
          </span>
        </p>
        {/* Draw-ms says how long one repaint took. This says whether the thing
            keeps a frame while it runs, which is the shippable/not line. */}
        <p className="galab__verdict" aria-live="polite">
          <strong>{verdictFor(stat, baseline)}</strong>
          <span>
            {frameSummary(stat, baseline)}
          </span>
        </p>
      </div>

      <p className="galab__mode-copy">
        <strong>{mode}</strong>
        {" — "}
        {mode === "A" ? meta.a : meta.b}
      </p>
      <p className="galab__note">{note}</p>

      <div className="galab__actions">
        {trial === "seam" ? (
          <button
            type="button"
            onClick={() => void applySeam(focusOn ? "idle" : "focus-group")}
          >
            {focusOn ? "Clear focus" : "Apply focus-group"}
          </button>
        ) : null}
        {trial === "selection" && selectedId ? (
          <button
            type="button"
            onClick={() => {
              setSelectedId(null);
              setNote("Selection cleared.");
            }}
          >
            Clear selection
          </button>
        ) : null}
        {trial === "editor" ? (
          <button type="button" onClick={() => setEditorOpen((v) => !v)}>
            {editorOpen ? "Close editor" : "Open editor"}
          </button>
        ) : null}
        {trial === "wait" ? (
          <button type="button" onClick={() => setWaiting((v) => !v)}>
            {waiting ? "Stop wait" : "Start wait"}
          </button>
        ) : null}
        {trial === "load" ? (
          <p className="galab__load-hint">
            Mini ambient fixture · {TRIAL_MAX_NODES} nodes · Ø
            {50} · Jost 0.12×
          </p>
        ) : null}
      </div>

      <div
        className={[
          "galab__stage-wrap",
          focusOn ? "is-focus" : "",
          trial === "editor" && mode === "B" && editorOpen ? "is-dim" : "",
          waiting ? "is-waiting" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="galab__stage-slot">
          <div ref={stageRef} className="galab__stage" />
          {trial === "selection" ? (
            <SelectionOrbiter
              graph={graphReady ? graphRef.current : null}
              nodeId={selectedId}
            />
          ) : null}
          {waiting ? (
            <div className="galab__wait" role="status">
              <div className="galab__spinner" aria-hidden>
                <span />
                <span />
                <span />
              </div>
              <p>Build running… (honest status — no %)</p>
            </div>
          ) : null}
        </div>
        {trial === "editor" ? (
          <aside
            className="galab__editor"
            data-open={editorOpen ? "true" : "false"}
            aria-hidden={!editorOpen}
          >
            <header>
              <strong>{selectedId ?? "node"}</strong>
              <button type="button" onClick={() => setEditorOpen(false)}>
                Close
              </button>
            </header>
            <div className="galab__editor-body">
              Empty Markdown shell — ambient graph stays interactive behind.
            </div>
          </aside>
        ) : null}
      </div>
    </main>
  );
}
