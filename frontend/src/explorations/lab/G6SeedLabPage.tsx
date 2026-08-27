import { useEffect, useMemo, useRef, useState } from "react";
import { Graph, type IElementDragEvent } from "@antv/g6";
import {
  BASE_BEHAVIORS,
  BASE_EDGE_STATE,
  BASE_NODE_STATE,
} from "../g6/graphOptions";
import { edgeStyleMapper } from "../g6/edgeKinds";
import { FORCE_PRESETS, PHYSICS_ENABLED, birthPositionNear } from "../g6/forcePresets";
import { ensureSeedLabCircleRegistered } from "../g6/seedLabCircle";
import {
  DEFAULT_SEED_FAMILY,
  SEED_CURVE_FAMILIES,
  driveFromFamily,
  getSeedDrive,
  sampleCssEase,
  sampleDilateEase,
  setSeedDrive,
  type SeedCurveFamily,
  type SeedDriveConfig,
} from "../g6/seedLabDrive";
import { ensureIntentionD3ForceRegistered } from "../g6/intentionD3Force";
import type { DilateCurveParams } from "../../shared/motion/dilateCurve";
import "../g6/g6Lab.css";
import "./G6SeedLabPage.css";

const SEED_LAB_DATA = {
  nodes: [
    { id: "anchor", style: { x: 200, y: 190 } },
    { id: "field", style: { x: 340, y: 150 } },
    { id: "pond", style: { x: 300, y: 280 } },
  ],
  edges: [
    {
      id: "e-a-f",
      source: "anchor",
      target: "field",
      data: { kind: "leadsto" },
    },
    {
      id: "e-f-p",
      source: "field",
      target: "pond",
      data: { kind: "expresses" },
    },
  ],
};

function seedLabData() {
  return structuredClone(SEED_LAB_DATA);
}

function intentionLayout() {
  return {
    ...FORCE_PRESETS["glide-loose"].layout,
    type: "intention-d3-force",
    // Required for DragElementForce: G6 only wires onTick → element
    // updates when layout animation is on. Without it, drag mutates
    // model x/y but the rendered node stays put (and hit-testing breaks).
    animation: true,
    center: false,
  } as unknown as typeof FORCE_PRESETS["glide-loose"]["layout"];
}

const CURVE_W = 280;
const CURVE_H = 140;
const CURVE_PAD = 16;

function mapX(t: number) {
  return CURVE_PAD + t * (CURVE_W - CURVE_PAD * 2);
}

function mapY(v: number, vMin: number, vMax: number) {
  const span = vMax - vMin || 1;
  return CURVE_H - CURVE_PAD - ((v - vMin) / span) * (CURVE_H - CURVE_PAD * 2);
}

function CurvePlot({
  title,
  samples,
  stroke,
}: {
  title: string;
  samples: { t: number; v: number }[];
  stroke: string;
}) {
  const vMin = Math.min(0, ...samples.map((s) => s.v)) - 0.05;
  const vMax = Math.max(1, ...samples.map((s) => s.v)) + 0.1;
  const path = samples
    .map(
      (s, i) =>
        `${i === 0 ? "M" : "L"} ${mapX(s.t).toFixed(1)},${mapY(s.v, vMin, vMax).toFixed(1)}`,
    )
    .join(" ");
  const linear = `M ${mapX(0)},${mapY(0, vMin, vMax)} L ${mapX(1)},${mapY(1, vMin, vMax)}`;
  const oneY = mapY(1, vMin, vMax);

  return (
    <figure className="seed-lab__curve">
      <figcaption>{title}</figcaption>
      <svg width={CURVE_W} height={CURVE_H} viewBox={`0 0 ${CURVE_W} ${CURVE_H}`}>
        <line
          x1={CURVE_PAD}
          x2={CURVE_W - CURVE_PAD}
          y1={oneY}
          y2={oneY}
          className="seed-lab__curve-ref"
        />
        <path d={linear} className="seed-lab__curve-linear" />
        <path d={path} fill="none" stroke={stroke} strokeWidth="2" />
      </svg>
    </figure>
  );
}

function seedNodeOptions(cfg: SeedDriveConfig) {
  return {
    type: "seed-lab-circle" as const,
    style: {
      size: 50,
      labelText: (d: { id: string | number }) => String(d.id),
      labelPlacement: "center" as const,
      labelFill: "#fff",
      labelFontSize: 10,
      labelFontWeight: 600,
      fill: "#111",
      stroke: "#111",
      lineWidth: 1,
    },
    state: BASE_NODE_STATE,
    animation: {
      enter: false as const,
      exit: [{ fields: ["size"], duration: cfg.exitMs, easing: "linear" }],
      update: [
        {
          fields: ["fill", "stroke", "lineWidth"],
          shape: "key",
          duration: 150,
          easing: "ease-out",
        },
      ],
    },
  };
}

export function G6SeedLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const counterRef = useRef(0);
  const [liveId, setLiveId] = useState<string | null>(null);
  const liveIdRef = useRef<string | null>(null);

  const [familyId, setFamilyId] = useState(DEFAULT_SEED_FAMILY.id);
  const [drive, setDriveState] = useState<SeedDriveConfig>(() =>
    driveFromFamily(DEFAULT_SEED_FAMILY),
  );
  const [note, setNote] = useState(
    PHYSICS_ENABLED
      ? "Gravity on Glide Loose. Birth holds the field — no force reheat after scale."
      : "Gravity, physics paused. Dragging one node never disturbs the rest.",
  );
  const [copied, setCopied] = useState(false);

  const family =
    SEED_CURVE_FAMILIES.find((f) => f.id === familyId) ?? DEFAULT_SEED_FAMILY;

  const syncDrive = (next: SeedDriveConfig) => {
    setSeedDrive(next);
    setDriveState(next);
    const graph = graphRef.current;
    if (graph && !graph.destroyed) {
      graph.setNode(seedNodeOptions(next));
    }
  };

  const pickFamily = (f: SeedCurveFamily) => {
    setFamilyId(f.id);
    syncDrive(driveFromFamily(f));
    setNote(`${f.label}: ${f.metaphor}`);
  };

  const patchDrive = (partial: Partial<SeedDriveConfig>) => {
    syncDrive({ ...getSeedDrive(), ...partial });
  };

  const patchEnterDilate = (partial: Partial<DilateCurveParams>) => {
    const cur = getSeedDrive();
    patchDrive({ enterDilate: { ...cur.enterDilate, ...partial } });
  };

  const patchExitDilate = (partial: Partial<DilateCurveParams>) => {
    const cur = getSeedDrive();
    patchDrive({ exitDilate: { ...cur.exitDilate, ...partial } });
  };

  const enterSamples = useMemo(() => {
    if (drive.mode === "dilate") return sampleDilateEase(drive.enterDilate);
    return sampleCssEase(drive.enterEase);
  }, [drive]);

  const exitSamples = useMemo(() => {
    if (drive.mode === "dilate") return sampleDilateEase(drive.exitDilate);
    return sampleCssEase(drive.exitEase);
  }, [drive]);

  const birthReleaseRef = useRef<number | null>(null);
  // Tracks the node currently mid-drag-gesture (between node:dragstart and
  // node:dragend). Needed because death() must never remove a node while
  // it's being dragged — see dragEndWaitersRef below for why.
  const draggingIdRef = useRef<string | null>(null);
  // If death() is asked to remove the node the user is *currently*
  // dragging, DragElementForce has already reheated the d3 simulation
  // (alphaTarget 0.3) for that gesture and only its own dragend handler
  // cools it back down. Deleting the node out from under an in-flight drag
  // means that handler's cleanup can be skipped, leaving the simulation
  // permanently hot and trying to sync the now-gone node on every tick —
  // an infinite "Node not found" flood. So death() parks here until the
  // drag actually ends, then proceeds.
  const dragEndWaitersRef = useRef<Array<() => void>>([]);
  const deathPendingRef = useRef(false);
  // Bumped on every dragstart/dragend, for *any* node — lets
  // refreshFieldMembership notice "a drag touched the sim while I was
  // mid-swap" even if that drag started and finished entirely inside the
  // window (draggingIdRef would already be back to null by the time we
  // check it). See refreshFieldMembership's retry loop.
  const dragGenRef = useRef(0);
  // Serializes anything that touches the d3-force layout instance
  // (refreshFieldMembership runs from both admit and death). Without this,
  // a death() that fires while a birth()'s admit is still rebuilding the
  // instance — or vice versa — races: both read/restore pins and swap the
  // tracked instance concurrently, which is exactly how a stale instance
  // slips through and starts throwing "Node not found" on later drags.
  const fieldQueueRef = useRef<Promise<void>>(Promise.resolve());
  const withFieldQueue = (task: () => Promise<void>) => {
    const run = fieldQueueRef.current.then(task, task);
    fieldQueueRef.current = run.catch(() => {});
    return run;
  };

  /** Resolves immediately if idle, or on the next dragend if a drag (of
   * any node) is currently in progress. */
  const waitForNoActiveDrag = () => {
    if (!draggingIdRef.current) return Promise.resolve();
    return new Promise<void>((resolve) => {
      dragEndWaitersRef.current.push(resolve);
    });
  };

  const clearNodePin = (graph: Graph, id: string) => {
    try {
      graph.updateNodeData([{ id, style: { fx: null, fy: null } }]);
    } catch {
      /* ok */
    }
    try {
      // @ts-expect-error layout controller is not on the public Graph type
      const layouts = graph.context?.layout?.getLayoutInstance?.() ?? [];
      for (const layout of layouts as Array<{
        setFixedPosition?: (id: string, pos: (number | null)[]) => void;
        instance?: {
          setFixedPosition?: (id: string, pos: (number | null)[]) => void;
        };
      }>) {
        const target = layout.instance ?? layout;
        target.setFixedPosition?.(id, [null, null, null]);
      }
    } catch {
      /* ok */
    }
  };

  /**
   * Rebuild the d3-force layout's tracked instance so it matches the graph's
   * *current* node set, without visibly moving anything.
   *
   * Why this is needed: G6 creates a brand-new layout instance (and a brand-
   * new d3 simulation) on every `graph.layout()` call — it never mutates the
   * previous one in place. `DragElementForce` always drags whatever instance
   * is currently tracked (`context.layout.getLayoutInstance()`), and that
   * instance's own tick loop pushes its (frozen-at-creation-time) node list
   * back into the *live* graph model on every tick. So if a node is removed
   * (death()) without rebuilding the tracked instance, that instance still
   * references the now-gone node. It sits dormant (stopLayout() halts its
   * timer) but is NOT cleared from `instances[]` — only `instance` is. The
   * next drag of *any* node calls `.restart()` on this exact stale instance
   * (reheating it), and every subsequent tick throws "Node not found for
   * id: <dead node>" while trying to sync it into the live model — forever,
   * since nothing else ever stops it. Calling this after every birth/death
   * keeps the tracked instance's node list in sync with reality.
   *
   * With PHYSICS_ENABLED false, there's no live layout instance to keep in
   * sync — addNodeData/removeNodeData are all a birth/death needs. This
   * whole function is a no-op below until physics comes back.
   */
  const runFieldRefreshPass = async (graph: Graph) => {
    // A prior drag can leave the current d3-force simulation "hot"
    // (alphaTarget 0.3, still ticking while it cools). The layout() calls
    // below replace the tracked instance — if that happens while the old
    // one is still ticking, it becomes unreachable/unstoppable and keeps
    // firing onTick against nodes that later get removed, which throws
    // "Node not found" forever. Stop it first so nothing orphans.
    try {
      graph.stopLayout();
    } catch {
      /* ok */
    }

    const priorPins = new Map<string, { fx: number; fy: number }>();
    for (const node of graph.getNodeData()) {
      const fx = (node.style as { fx?: number })?.fx;
      const fy = (node.style as { fy?: number })?.fy;
      if (typeof fx === "number" && typeof fy === "number") {
        priorPins.set(String(node.id), { fx, fy });
      }
      const x = (node.style as { x?: number })?.x;
      const y = (node.style as { y?: number })?.y;
      if (typeof x === "number" && typeof y === "number") {
        graph.updateNodeData([{ id: node.id, style: { fx: x, fy: y } }]);
      }
    }

    try {
      // Rebuild d3 membership against the current node set (fast,
      // synchronous ticking — this call never hangs).
      await graph.layout({
        ...intentionLayout(),
        animation: false,
      } as Parameters<Graph["layout"]>[0]);
      // The `await` above is a real yield point — a drag's dragstart can
      // fire in that gap and reheat the instance graph.layout() just
      // created (alphaTarget 0.3, still ticking). The next graph.layout()
      // call below unconditionally overwrites the tracked instance without
      // stopping whatever was there — without this second stopLayout(),
      // that reheated instance orphans while hot and ticks forever,
      // throwing "Node not found" on every tick once a later birth/death
      // removes a node it still references. Stopping here closes that gap.
      try {
        graph.stopLayout();
      } catch {
        /* ok */
      }
      // The animation:false pass leaves the layout instance without its
      // tick → element-sync wiring (only bound when setSimulation() first
      // runs with an onTick callback, which only the animated path
      // provides), so drag would mutate the sim's model but never repaint
      // the node. Redo it through the animated path at alpha 0 (no
      // movement, resolves in ~1 tick) to rebind that wiring. Race it
      // against a timeout: if something else calls graph.stopLayout()
      // concurrently, the 'end' event this awaits on may never fire, and we
      // must not hang.
      await Promise.race([
        graph.layout({
          ...intentionLayout(),
          animation: true,
          alpha: 0,
          alphaTarget: 0,
        } as Parameters<Graph["layout"]>[0]),
        new Promise((resolve) => window.setTimeout(resolve, 200)),
      ]);
    } catch {
      /* ok */
    }

    if (graph.destroyed) return;

    for (const node of graph.getNodeData()) {
      const id = String(node.id);
      const prior = priorPins.get(id);
      if (prior) {
        graph.updateNodeData([{ id, style: { fx: prior.fx, fy: prior.fy } }]);
        try {
          // @ts-expect-error layout controller is not on the public Graph type
          const layouts = graph.context?.layout?.getLayoutInstance?.() ?? [];
          for (const layout of layouts as Array<{
            setFixedPosition?: (id: string, pos: (number | null)[]) => void;
            instance?: {
              setFixedPosition?: (id: string, pos: (number | null)[]) => void;
            };
          }>) {
            (layout.instance ?? layout).setFixedPosition?.(id, [
              prior.fx,
              prior.fy,
              null,
            ]);
          }
        } catch {
          /* ok */
        }
      } else {
        clearNodePin(graph, id);
      }
    }
  };

  /**
   * Runs `runFieldRefreshPass`, but first waits out any drag in progress,
   * and re-runs the pass if a drag touched the sim *during* it.
   *
   * Why the retry: a pass takes real wall-clock time (two awaited
   * graph.layout() calls). If a dragstart fires inside that window, it
   * reheats whatever instance the pass just created; the pass's own
   * defensive stopLayout() calls only guard the gaps *it* knows about, not
   * a drag that starts and ends entirely inside one of its awaits.
   * dragGenRef ticks on every dragstart/dragend for any node, so comparing
   * it before/after catches that case even if draggingIdRef is back to
   * null by the time we check. Re-running the pass calls stopLayout()
   * again at its top, which by then correctly targets (and kills) whatever
   * the drag left hot, before rebuilding once more.
   */
  const refreshFieldMembership = async (graph: Graph) => {
    if (!PHYSICS_ENABLED) return;

    for (let attempt = 0; attempt < 4; attempt++) {
      if (graph.destroyed) return;
      await waitForNoActiveDrag();
      if (graph.destroyed) return;

      const genBefore = dragGenRef.current;
      await runFieldRefreshPass(graph);
      if (graph.destroyed) return;

      if (dragGenRef.current === genBefore && !draggingIdRef.current) return;
      // A drag started/ended (or is still going) during the pass — the
      // instance it touched may now be orphaned and hot. Loop and redo.
    }
  };

  /** Enroll a post-aperture newborn without letting topology rearrange peers. */
  const admitNewbornToField = async (graph: Graph, newbornId: string) => {
    if (graph.destroyed || liveIdRef.current !== newbornId) return;
    if (!graph.getNodeData().some((n) => n.id === newbornId)) return;
    await withFieldQueue(() => refreshFieldMembership(graph));
  };

  const birth = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    if (liveIdRef.current) return;

    const anchors = graph
      .getNodeData()
      .map((n) => n.id)
      .filter((id) => !String(id).startsWith("probe-"));
    const target = anchors[Math.floor(Math.random() * anchors.length)];
    const id = `probe-${counterRef.current++}`;
    const { x, y } = birthPositionNear(graph, String(target));

    liveIdRef.current = id;
    setLiveId(id);
    // No layout() here — aperture is the only motion beat.
    graph.addNodeData([{ id, style: { x, y } }]);
    graph.addEdgeData([
      {
        id: `e-${id}`,
        source: String(target),
        target: id,
        data: { kind: "leadsto" },
      },
    ]);
    await graph.draw();
    setNote(`Birth “${id}” ← ${target} · ${family.label}`);

    if (birthReleaseRef.current) window.clearTimeout(birthReleaseRef.current);
    const enterMs = getSeedDrive().enterMs;
    birthReleaseRef.current = window.setTimeout(() => {
      birthReleaseRef.current = null;
      const live = graphRef.current;
      if (!live || live.destroyed || liveIdRef.current !== id) return;
      void admitNewbornToField(live, id).then(() => {
        if (liveIdRef.current === id) {
          setNote(`Birth “${id}” settled · joins the field`);
        }
      });
    }, enterMs + 80);
  };

  const death = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    const id = liveIdRef.current;
    if (!id || deathPendingRef.current) return;
    deathPendingRef.current = true;
    try {
      if (birthReleaseRef.current) {
        window.clearTimeout(birthReleaseRef.current);
        birthReleaseRef.current = null;
      }
      // Never remove a node the user is actively dragging out from under
      // their cursor — park until the gesture ends, then proceed. (This
      // also sidesteps a real bug when physics was on: DragElementForce
      // reheats the simulation on dragstart and only its own dragend
      // handler cools it back down, so deleting the node mid-drag could
      // skip that cleanup and leave the simulation permanently hot.)
      if (draggingIdRef.current === id) {
        await new Promise<void>((resolve) => {
          dragEndWaitersRef.current.push(resolve);
        });
        if (graph.destroyed || liveIdRef.current !== id) return;
      }
      liveIdRef.current = null;
      setLiveId(null);
      try {
        graph.stopLayout();
      } catch {
        /* ok */
      }
      graph.removeNodeData([id]);
      await graph.draw();
      setNote(`Death “${id}” · ${family.label}`);
      // Keep the tracked d3-force instance in sync with the now-smaller
      // node set — see refreshFieldMembership's doc comment. No-op while
      // physics is off. Queued (not run directly) so a fast-following
      // birth()'s own admit can't run its refresh concurrently and race
      // this one.
      await withFieldQueue(() => refreshFieldMembership(graph));
    } finally {
      deathPendingRef.current = false;
    }
  };

  useEffect(() => {
    if (!containerRef.current) return;
    ensureSeedLabCircleRegistered();
    if (PHYSICS_ENABLED) ensureIntentionD3ForceRegistered();
    setSeedDrive(driveFromFamily(DEFAULT_SEED_FAMILY));

    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      data: seedLabData(),
      node: seedNodeOptions(getSeedDrive()),
      edge: {
        style: {
          stroke: (d) => edgeStyleMapper(d).stroke,
          lineWidth: (d) => edgeStyleMapper(d).lineWidth,
          endArrow: (d) => edgeStyleMapper(d).endArrow,
          endArrowType: "triangle",
          endArrowSize: 8,
          lineDash: (d) => edgeStyleMapper(d).lineDash,
        },
        state: BASE_EDGE_STATE,
        animation: {
          enter: "path-in",
          exit: "path-out",
          update: [
            {
              fields: ["stroke", "lineWidth"],
              shape: "key",
              duration: 150,
              easing: "ease-out",
            },
          ],
        },
      },
      layout: PHYSICS_ENABLED ? intentionLayout() : undefined,
      behaviors: PHYSICS_ENABLED
        ? [
            ...BASE_BEHAVIORS.filter((behavior) => behavior !== "drag-element"),
            { type: "drag-element-force", fixed: false },
          ]
        : [...BASE_BEHAVIORS],
    });

    graph.render().catch(() => {});
    graphRef.current = graph;
    // Browser-verification hook for manual/automated drag testing — not
    // used by the page itself.
    // @ts-expect-error not on the public Graph type
    window.__seedLabGraph = graph;

    graph.on("node:dragstart", (event: IElementDragEvent) => {
      draggingIdRef.current = (event?.target?.id as string | undefined) ?? null;
      dragGenRef.current += 1;
    });
    const onDragEnd = () => {
      dragGenRef.current += 1;
      draggingIdRef.current = null;
      const waiters = dragEndWaitersRef.current;
      dragEndWaitersRef.current = [];
      waiters.forEach((resolve) => resolve());
    };
    graph.on("node:dragend", onDragEnd);

    return () => {
      if (birthReleaseRef.current) window.clearTimeout(birthReleaseRef.current);
      graph.destroy();
      graphRef.current = null;
    };
  }, []);

  const copyConfig = async () => {
    const payload = {
      family: familyId,
      ...drive,
    };
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <div className="g6-lab seed-lab">
      <header className="g6-lab__chrome seed-lab__chrome">
        <p className="g6-lab__eyebrow">Design lab</p>
        <h1 className="g6-lab__title">Seed curve — find the language</h1>
        <p className="g6-lab__lede">
          {PHYSICS_ENABLED
            ? "Physics stays Glide Loose and stays still on birth — the node falls into size in place; force is not reheated. "
            : "Physics is paused for now — positions are static, so dragging one node never disturbs the rest. "}
          You are picking a <em>punctuation curve</em> reusable for discrete
          gestures. <strong>Gravity</strong> is the current choice.
        </p>

        <div className="g6-lab__controls">
          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Language</span>
            {SEED_CURVE_FAMILIES.map((f) => (
              <button
                key={f.id}
                type="button"
                className={
                  "g6-lab__chip" + (familyId === f.id ? " g6-lab__chip--active" : "")
                }
                onClick={() => pickFamily(f)}
                title={f.glideNote}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <p className="seed-lab__family-note">
          <span>{family.metaphor}</span>
          <span className="seed-lab__glide-note">{family.glideNote}</span>
        </p>

        <div className="g6-lab__actions">
          <button type="button" onClick={() => birth()} disabled={!!liveId}>
            Birth
          </button>
          <button type="button" onClick={() => death()} disabled={!liveId}>
            Death
          </button>
          <button type="button" onClick={copyConfig}>
            {copied ? "Copied" : "Copy config"}
          </button>
        </div>

        <p className="g6-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-lifecycle">Lifecycle</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/curve-lab">Dilate curve</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-physics">Physics</a>
        </p>
      </header>

      <p className="g6-lab__note">{note}</p>

      <div className="seed-lab__layout">
        <div className="seed-lab__stage-wrap">
          <div className="g6-lab__stage seed-lab__stage" ref={containerRef} />
        </div>

        <aside className="seed-lab__side">
          <div className="seed-lab__curves">
            <CurvePlot title="Birth (open)" samples={enterSamples} stroke="#111" />
            <CurvePlot title="Death (close)" samples={exitSamples} stroke="#666" />
          </div>

          <div className="seed-lab__sliders">
            <label className="g6-lab__slider">
              Birth {drive.enterMs}ms
              <input
                type="range"
                min={280}
                max={1600}
                step={20}
                value={drive.enterMs}
                onChange={(e) => patchDrive({ enterMs: Number(e.target.value) })}
              />
            </label>
            <label className="g6-lab__slider">
              Death {drive.exitMs}ms
              <input
                type="range"
                min={200}
                max={1200}
                step={20}
                value={drive.exitMs}
                onChange={(e) => patchDrive({ exitMs: Number(e.target.value) })}
              />
            </label>
            <label className="g6-lab__slider">
              Pin {Math.round(drive.pinRatio * 100)}%
              <input
                type="range"
                min={2}
                max={14}
                step={1}
                value={Math.round(drive.pinRatio * 100)}
                onChange={(e) =>
                  patchDrive({ pinRatio: Number(e.target.value) / 100 })
                }
              />
            </label>
          </div>

          {drive.mode === "dilate" ? (
            <div className="seed-lab__dilate">
              <p className="seed-lab__side-label">Birth spring</p>
              <label className="g6-lab__slider">
                Hesitation {drive.enterDilate.hesitation.toFixed(2)}
                <input
                  type="range"
                  min={0}
                  max={0.35}
                  step={0.01}
                  value={drive.enterDilate.hesitation}
                  onChange={(e) =>
                    patchEnterDilate({ hesitation: Number(e.target.value) })
                  }
                />
              </label>
              <label className="g6-lab__slider">
                Tension {drive.enterDilate.tension.toFixed(1)}
                <input
                  type="range"
                  min={3}
                  max={18}
                  step={0.1}
                  value={drive.enterDilate.tension}
                  onChange={(e) =>
                    patchEnterDilate({ tension: Number(e.target.value) })
                  }
                />
              </label>
              <label className="g6-lab__slider">
                Damping {drive.enterDilate.damping.toFixed(2)}
                <input
                  type="range"
                  min={0.25}
                  max={1.4}
                  step={0.01}
                  value={drive.enterDilate.damping}
                  onChange={(e) =>
                    patchEnterDilate({ damping: Number(e.target.value) })
                  }
                />
              </label>

              <p className="seed-lab__side-label">Death spring</p>
              <label className="g6-lab__slider">
                Hesitation {drive.exitDilate.hesitation.toFixed(2)}
                <input
                  type="range"
                  min={0}
                  max={0.2}
                  step={0.01}
                  value={drive.exitDilate.hesitation}
                  onChange={(e) =>
                    patchExitDilate({ hesitation: Number(e.target.value) })
                  }
                />
              </label>
              <label className="g6-lab__slider">
                Tension {drive.exitDilate.tension.toFixed(1)}
                <input
                  type="range"
                  min={4}
                  max={20}
                  step={0.1}
                  value={drive.exitDilate.tension}
                  onChange={(e) =>
                    patchExitDilate({ tension: Number(e.target.value) })
                  }
                />
              </label>
              <label className="g6-lab__slider">
                Damping {drive.exitDilate.damping.toFixed(2)}
                <input
                  type="range"
                  min={0.5}
                  max={1.5}
                  step={0.01}
                  value={drive.exitDilate.damping}
                  onChange={(e) =>
                    patchExitDilate({ damping: Number(e.target.value) })
                  }
                />
              </label>

              <label className="seed-lab__check">
                <input
                  type="checkbox"
                  checked={drive.allowOvershoot}
                  onChange={(e) => patchDrive({ allowOvershoot: e.target.checked })}
                />
                Allow overshoot (pupil habit)
              </label>
            </div>
          ) : (
            <div className="seed-lab__css">
              <p className="seed-lab__side-label">CSS easings</p>
              <label className="seed-lab__field">
                Birth
                <input
                  type="text"
                  value={drive.enterEase}
                  onChange={(e) => patchDrive({ enterEase: e.target.value })}
                />
              </label>
              <label className="seed-lab__field">
                Death
                <input
                  type="text"
                  value={drive.exitEase}
                  onChange={(e) => patchDrive({ exitEase: e.target.value })}
                />
              </label>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
