import { useEffect, useRef, useState } from "react";
import { Graph, type EdgeData, type GraphData } from "@antv/g6";
import { PHYSICS_ENABLED, birthPositionNear } from "../g6/forcePresets";
import "./G6MotionLabPage.css";

/**
 * Trial of the "Tier 1 + physics" animation language proposed for a G6
 * migration:
 *   - physics (d3-force layout) owns continuity — position, drag response,
 *     the settle after any change to the graph.
 *   - Tier 1 declarative animations own punctuation — discrete state
 *     changes: birth (enter), death (exit), edge draw-in, and hover/select.
 *   - two easings only: a springy "ease-out with a touch of overshoot" for
 *     arrival, a plain "ease-in" for departure. Three duration tiers:
 *     quick (~150ms, state changes), medium (~350ms, birth), and its
 *     slightly-shorter mirror for death (~200ms — leaving reads faster
 *     than arriving).
 *
 * Edge kinds are drawn entirely from built-in edge *style* (arrow / dot /
 * plain) — no custom edge classes. CONTAINS isn't shown here at all: it
 * doesn't belong as a drawn edge in G6's model, it belongs as combo
 * membership (see the G6 combos lab). Note: plain `d3-force` layout doesn't
 * know about combos, mixing the two here made layout convergence hang, so
 * this trial stays flat on purpose — combos + physics is its own spike.
 */

type EdgeKind = "leadsto" | "expresses" | "nearto";

/** Round line-cap + zero-length dash → dots (not dashes). */
const DOTTED: [number, number] = [0, 6.5];

const KIND_LABEL: Record<EdgeKind, string> = {
  leadsto: "LEADSTO — arrow",
  expresses: "EXPRESSES — dotted",
  nearto: "NEARTO — plain",
};

const KIND_STROKE: Record<EdgeKind, string> = {
  leadsto: "#111",
  expresses: "#111",
  nearto: "#888",
};

const KIND_CYCLE: EdgeKind[] = ["leadsto", "expresses", "nearto"];

const INITIAL_DATA: GraphData = {
  nodes: [
    { id: "idea", style: { x: 140, y: 260 } },
    { id: "draft", style: { x: 320, y: 160 } },
    { id: "notes", style: { x: 520, y: 200 } },
    { id: "insight", style: { x: 380, y: 400 } },
    { id: "archive", style: { x: 580, y: 400 } },
  ],
  edges: [
    { id: "e-idea-draft", source: "idea", target: "draft", data: { kind: "leadsto" } },
    { id: "e-draft-notes", source: "draft", target: "notes", data: { kind: "leadsto" } },
    { id: "e-notes-insight", source: "notes", target: "insight", data: { kind: "expresses" } },
    { id: "e-idea-insight", source: "idea", target: "insight", data: { kind: "nearto" } },
    { id: "e-insight-archive", source: "insight", target: "archive", data: { kind: "expresses" } },
  ],
};

const ARRIVE_EASE = "cubic-bezier(0.34, 1.56, 0.64, 1)";
const LEAVE_EASE = "ease-in";
const QUICK_MS = 150;
const BIRTH_MS = 360;
const DEATH_MS = 200;

export function G6MotionLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const counterRef = useRef(0);
  const kindCursorRef = useRef(0);
  const addedRef = useRef<string[]>([]);
  const [note, setNote] = useState(
    PHYSICS_ENABLED
      ? "Physics settles position; Tier 1 animation only punctuates birth, death, draw-in, and selection."
      : "Physics paused; Tier 1 animation only punctuates birth, death, draw-in, and selection.",
  );
  const [drift, setDrift] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      data: INITIAL_DATA,
      node: {
        style: {
          size: 50,
          labelText: (d) => String(d.id),
          labelPlacement: "center",
          labelFill: "#fff",
          labelFontSize: 10,
          labelFontWeight: 600,
          fill: "#111",
          stroke: "#111",
          lineWidth: 1,
        },
        animation: {
          enter: [
            { fields: ["opacity"], duration: QUICK_MS, easing: LEAVE_EASE },
            { fields: ["opacity"], duration: BIRTH_MS, delay: QUICK_MS - 60, easing: ARRIVE_EASE },
            { fields: ["r"], shape: "key", duration: BIRTH_MS, delay: QUICK_MS - 60, easing: ARRIVE_EASE },
          ],
          exit: [
            { fields: ["opacity"], duration: DEATH_MS, easing: LEAVE_EASE },
            { fields: ["r"], shape: "key", duration: DEATH_MS, easing: LEAVE_EASE },
          ],
          update: [
            { fields: ["fill", "stroke", "lineWidth"], shape: "key", duration: QUICK_MS, easing: "ease-out" },
          ],
        },
        state: {
          active: { lineWidth: 2.5, stroke: "#111" },
          selected: { lineWidth: 3, stroke: "#111" },
        },
      },
      edge: {
        style: {
          stroke: (d: EdgeData) => KIND_STROKE[(d.data?.kind as EdgeKind) ?? "nearto"],
          lineWidth: (d: EdgeData) => ((d.data?.kind as EdgeKind) === "leadsto" ? 1.75 : 1.4),
          endArrow: (d: EdgeData) => (d.data?.kind as EdgeKind) === "leadsto",
          endArrowType: "triangle",
          endArrowSize: 8,
          lineDash: (d: EdgeData) =>
            (d.data?.kind as EdgeKind) === "expresses" ? DOTTED : undefined,
          lineCap: "round",
        },
        state: {
          active: { lineWidth: 2, stroke: "#111" },
          selected: { lineWidth: 2.2, stroke: "#111" },
        },
        animation: {
          // Built-in stage presets — this IS the "thin line dilates into a
          // typed edge" idea, already shipped as a named animation in G6.
          enter: "path-in",
          exit: "path-out",
          update: [{ fields: ["stroke", "lineWidth"], shape: "key", duration: QUICK_MS, easing: "ease-out" }],
        },
      },
      layout: PHYSICS_ENABLED
        ? {
            type: "d3-force",
            link: { distance: 220, strength: 0.09, iterations: 1 },
            manyBody: false,
            collide: { radius: 48, strength: 1, iterations: 3 },
            center: false,
            alphaDecay: 0.035,
            velocityDecay: 0.42,
            alphaTarget: 0,
          }
        : undefined,
      behaviors: [
        "drag-canvas",
        "zoom-canvas",
        // With physics on, plain drag-element never talks to the live
        // simulation — it fights back on the next tick. drag-element-force
        // hands the pointer to the sim instead. See PHYSICS_ENABLED in
        // forcePresets.ts.
        PHYSICS_ENABLED
          ? { type: "drag-element-force", fixed: false }
          : "drag-element",
        "click-select",
        {
          type: "hover-activate",
          degree: 0,
          state: "active",
        },
      ],
    });

    graph.render().catch(() => {});
    graphRef.current = graph;

    return () => {
      graph.destroy();
      graphRef.current = null;
    };
  }, []);

  const addNode = async () => {
    const graph = graphRef.current;
    if (!graph) return;
    const existing = graph.getNodeData().map((n) => n.id);
    const target = existing[Math.floor(Math.random() * existing.length)];
    const kind = KIND_CYCLE[kindCursorRef.current % KIND_CYCLE.length];
    kindCursorRef.current += 1;
    const id = `note-${counterRef.current++}`;
    addedRef.current.push(id);

    // draw() diffs + runs enter/exit animation without waiting for physics
    // to fully settle. layout() is fired but intentionally not awaited — a
    // live force simulation has no obligation to ever cross alphaMin, and
    // the UI shouldn't block on that.
    if (PHYSICS_ENABLED) graph.stopLayout();
    graph.addNodeData([
      { id, style: birthPositionNear(graph, String(target)) },
    ]);
    graph.addEdgeData([
      { id: `e-${id}`, source: String(target), target: id, data: { kind } },
    ]);
    await graph.draw();
    if (PHYSICS_ENABLED) graph.layout().catch(() => {});
    setNote(
      PHYSICS_ENABLED
        ? `Born "${id}" — ${KIND_LABEL[kind]} edge from "${target}". Fade-in, then a spring pop; physics resettles everything.`
        : `Born "${id}" — ${KIND_LABEL[kind]} edge from "${target}". Fade-in, then a spring pop.`,
    );
  };

  const removeNode = async () => {
    const graph = graphRef.current;
    if (!graph) return;
    const id = addedRef.current.pop();
    if (!id) {
      setNote("Nothing left to remove — only the original graph remains.");
      return;
    }
    if (PHYSICS_ENABLED) graph.stopLayout();
    graph.removeNodeData([id]);
    await graph.draw();
    if (PHYSICS_ENABLED) graph.layout().catch(() => {});
    setNote(
      PHYSICS_ENABLED
        ? `Removed "${id}" — quick ease-in fade+shrink, edge draws itself back out (path-out), physics resettles.`
        : `Removed "${id}" — quick ease-in fade+shrink, edge draws itself back out (path-out).`,
    );
  };

  const toggleDrift = () => {
    if (!PHYSICS_ENABLED) {
      setNote("Idle drift needs physics, which is paused for now.");
      return;
    }
    const graph = graphRef.current;
    if (!graph) return;
    const next = !drift;
    setDrift(next);
    graph.stopLayout();
    graph.setLayout((prev) => ({
      ...prev,
      alphaTarget: next ? 0.02 : 0,
      alphaDecay: next ? 0.01 : 0.02,
    }));
    graph.layout().catch(() => {});
    setNote(
      next
        ? "Idle drift on — alphaTarget stays above zero, so the simulation never fully cools. Continuous motion, no keyframes."
        : "Idle drift off — physics settles to rest as usual.",
    );
  };

  return (
    <div className="g6-motion-lab">
      <header className="g6-motion-lab__chrome">
        <p className="g6-motion-lab__eyebrow">Design lab</p>
        <h1 className="g6-motion-lab__title">G6 motion — Tier 1 + physics</h1>
        <p className="g6-motion-lab__lede">
          {PHYSICS_ENABLED
            ? "Physics (d3-force) owns continuity. "
            : "Physics is paused for now — positions are static, so dragging one node never disturbs the rest. "}
          Declarative Tier 1 animation
          only punctuates: birth (hesitate, then a springy pop), death (quick
          ease-in fade+shrink — leaving reads faster than arriving), edge
          draw-in on birth via the built-in <code>path-in</code> preset, and
          a snappy state change on hover/select. <code>CONTAINS</code> is
          deliberately absent here — see the combos lab for that redesign.
        </p>
        <div className="g6-motion-lab__actions">
          <button type="button" onClick={addNode}>
            Add node
          </button>
          <button type="button" onClick={removeNode}>
            Remove last added
          </button>
          <button type="button" onClick={toggleDrift} aria-pressed={drift}>
            {drift ? "Idle drift: on" : "Idle drift: off"}
          </button>
        </div>
        <p className="g6-motion-lab__legend">
          {KIND_CYCLE.map((k) => (
            <span key={k} className="g6-motion-lab__legend-item">
              <span
                className="g6-motion-lab__legend-swatch"
                style={{ background: KIND_STROKE[k] }}
              />
              {KIND_LABEL[k]}
            </span>
          ))}
        </p>
        <p className="g6-motion-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-combo">G6 combos</a>
          <span aria-hidden> · </span>
          <a href="#/">Field</a>
        </p>
      </header>

      <p className="g6-motion-lab__note">{note}</p>
      <div className="g6-motion-lab__stage" ref={containerRef} />
    </div>
  );
}
