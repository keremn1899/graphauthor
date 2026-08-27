import { useEffect, useRef, useState } from "react";
import { Graph, type EdgeData } from "@antv/g6";
import {
  edgeStyleForKind,
  KIND_CYCLE,
  KIND_LABEL,
  KIND_STROKE,
  type EdgeKind,
} from "../g6/edgeKinds";
import { CONNECT_GRAPH_DATA } from "../g6/graphData";
import {
  BASE_BEHAVIORS,
  DEFAULT_NODE_FONT,
  NODE_FONT_IDS,
  NODE_FONTS,
  withPhysicsDrag,
  buildEdgeOptions,
  buildNodeOptions,
  type NodeFontId,
} from "../g6/graphOptions";
import {
  DEFAULT_FORCE_PRESET,
  FORCE_PRESETS,
  FORCE_PRESET_IDS,
  PHYSICS_ENABLED,
  softSettle,
  type ForcePresetId,
} from "../g6/forcePresets";
import {
  MOTION_SPINES,
  SPINE_IDS,
  type SpineId,
} from "../g6/motionSpines";
import { ensureRightClickCreateEdgeRegistered } from "../g6/rightClickCreateEdge";
import "../g6/g6Lab.css";

const ARRIVE_EASE_OPTIONS = [
  { id: "spring", label: "Spring", value: "cubic-bezier(0.34, 1.56, 0.64, 1)" },
  { id: "ease-out", label: "Ease out", value: "ease-out" },
  { id: "ease-in-out", label: "Ease in-out", value: "ease-in-out" },
];

const LEAVE_EASE_OPTIONS = [
  { id: "ease-in", label: "Ease in", value: "ease-in" },
  { id: "ease-out", label: "Ease out", value: "ease-out" },
];

export function G6ConnectLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const edgeKindRef = useRef<EdgeKind>("leadsto");
  const spineRef = useRef<SpineId>("breath");
  const tuningRef = useRef({
    durationScale: 1,
    arriveEase: ARRIVE_EASE_OPTIONS[0].value,
    leaveEase: LEAVE_EASE_OPTIONS[0].value,
    labelFontFamily: NODE_FONTS[DEFAULT_NODE_FONT].family,
    labelFontWeight: NODE_FONTS[DEFAULT_NODE_FONT].weight,
  });

  const [spineId, setSpineId] = useState<SpineId>("breath");
  const [forceId, setForceId] = useState<ForcePresetId>(DEFAULT_FORCE_PRESET);
  const [edgeKind, setEdgeKind] = useState<EdgeKind>("leadsto");
  const [fontId, setFontId] = useState<NodeFontId>(DEFAULT_NODE_FONT);
  const [durationScale, setDurationScale] = useState(1);
  const [arriveEase, setArriveEase] = useState(ARRIVE_EASE_OPTIONS[0].value);
  const [leaveEase, setLeaveEase] = useState(LEAVE_EASE_OPTIONS[0].value);
  const [note, setNote] = useState(
    "Right-click a node to start, move, right-click a target to finish. Left-click canvas or Escape cancels.",
  );

  edgeKindRef.current = edgeKind;
  spineRef.current = spineId;
  tuningRef.current = {
    durationScale,
    arriveEase,
    leaveEase,
    labelFontFamily: NODE_FONTS[fontId].family,
    labelFontWeight: NODE_FONTS[fontId].weight,
  };

  const applyMotion = () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    graph.setNode(buildNodeOptions(spineRef.current, tuningRef.current));
    graph.setEdge(buildEdgeOptions(spineRef.current, tuningRef.current));
  };

  const applyForce = (nextForce: ForcePresetId) => {
    if (!PHYSICS_ENABLED) return;
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    graph.stopLayout();
    graph.setLayout(FORCE_PRESETS[nextForce].layout);
    graph.layout().catch(() => {});
  };

  const softSettleAfterConnect = () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    softSettle(graph);
  };

  const updateEdgeBehavior = (kind: EdgeKind) => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    graph.updateBehavior({
      key: "right-click-create-edge",
      style: edgeStyleForKind(kind),
      onCreate: (edge: EdgeData) => ({
        ...edge,
        data: { kind },
        style: edgeStyleForKind(kind),
      }),
    });
  };

  useEffect(() => {
    if (!containerRef.current) return;
    ensureRightClickCreateEdgeRegistered();

    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      data: CONNECT_GRAPH_DATA,
      node: buildNodeOptions("breath"),
      edge: buildEdgeOptions("breath"),
      layout: PHYSICS_ENABLED ? FORCE_PRESETS[DEFAULT_FORCE_PRESET].layout : undefined,
      behaviors: [
        ...withPhysicsDrag(BASE_BEHAVIORS, PHYSICS_ENABLED),
        {
          key: "right-click-create-edge",
          type: "right-click-create-edge",
          style: edgeStyleForKind("leadsto"),
          onCreate: (edge: EdgeData) => {
            const kind = edgeKindRef.current;
            return {
              ...edge,
              data: { kind },
              style: edgeStyleForKind(kind),
            };
          },
          onFinish: (edge: EdgeData) => {
            setNote(`Connected ${edge.source} → ${edge.target} (${KIND_LABEL[edgeKindRef.current]}).`);
            softSettleAfterConnect();
          },
          onCancel: () => {
            setNote("Connection cancelled.");
          },
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

  const pickSpine = (id: SpineId) => {
    setSpineId(id);
    spineRef.current = id;
    applyMotion();
  };

  const pickForce = (id: ForcePresetId) => {
    setForceId(id);
    applyForce(id);
  };

  const pickEdgeKind = (kind: EdgeKind) => {
    setEdgeKind(kind);
    updateEdgeBehavior(kind);
  };

  const pickFont = (id: NodeFontId) => {
    setFontId(id);
    tuningRef.current = {
      ...tuningRef.current,
      labelFontFamily: NODE_FONTS[id].family,
      labelFontWeight: NODE_FONTS[id].weight,
    };
    applyMotion();
  };

  const onDurationScale = (value: number) => {
    setDurationScale(value);
    tuningRef.current = { ...tuningRef.current, durationScale: value };
    applyMotion();
  };

  const onArriveEase = (value: string) => {
    setArriveEase(value);
    tuningRef.current = { ...tuningRef.current, arriveEase: value };
    applyMotion();
  };

  const onLeaveEase = (value: string) => {
    setLeaveEase(value);
    tuningRef.current = { ...tuningRef.current, leaveEase: value };
    applyMotion();
  };

  return (
    <div className="g6-lab">
      <header className="g6-lab__chrome">
        <p className="g6-lab__eyebrow">Design lab</p>
        <h1 className="g6-lab__title">G6 connect — right-click edges</h1>
        <p className="g6-lab__lede">
          Based on G6&apos;s{" "}
          <a
            href="https://g6.antv.antgroup.com/en/examples/behavior/create-edge/#by-click"
            target="_blank"
            rel="noreferrer"
          >
            create-edge
          </a>{" "}
          behavior, but wired to <strong>right-click</strong> instead of left.
          Animation spines stay independent.{" "}
          {PHYSICS_ENABLED
            ? "Physics defaults to Glide — alive enough, soft enough that a new edge is a tug, not an explosion."
            : "Physics is paused for now — positions are static, so dragging one node never disturbs the rest."}
        </p>

        <div className="g6-lab__controls">
          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Spine</span>
            {SPINE_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={"g6-lab__chip" + (spineId === id ? " g6-lab__chip--active" : "")}
                onClick={() => pickSpine(id)}
                title={MOTION_SPINES[id].metaphor}
              >
                {MOTION_SPINES[id].label}
              </button>
            ))}
          </div>

          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Physics</span>
            {FORCE_PRESET_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={"g6-lab__chip" + (forceId === id ? " g6-lab__chip--active" : "")}
                onClick={() => pickForce(id)}
                title={FORCE_PRESETS[id].metaphor}
              >
                {FORCE_PRESETS[id].label}
              </button>
            ))}
          </div>

          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Edge kind</span>
            {KIND_CYCLE.map((kind) => (
              <button
                key={kind}
                type="button"
                className={"g6-lab__chip" + (edgeKind === kind ? " g6-lab__chip--active" : "")}
                onClick={() => pickEdgeKind(kind)}
              >
                {KIND_LABEL[kind]}
              </button>
            ))}
          </div>

          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Label</span>
            {NODE_FONT_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={"g6-lab__chip" + (fontId === id ? " g6-lab__chip--active" : "")}
                onClick={() => pickFont(id)}
                title={NODE_FONTS[id].note}
              >
                {NODE_FONTS[id].label}
              </button>
            ))}
          </div>

          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Tune</span>
            <label className="g6-lab__slider">
              Duration ×
              <input
                type="range"
                min={0.5}
                max={1.8}
                step={0.05}
                value={durationScale}
                onChange={(e) => onDurationScale(Number(e.target.value))}
              />
              {durationScale.toFixed(2)}
            </label>
            <select
              className="g6-lab__chip"
              value={arriveEase}
              onChange={(e) => onArriveEase(e.target.value)}
              aria-label="Arrival easing"
            >
              {ARRIVE_EASE_OPTIONS.map((opt) => (
                <option key={opt.id} value={opt.value}>
                  Arrive: {opt.label}
                </option>
              ))}
            </select>
            <select
              className="g6-lab__chip"
              value={leaveEase}
              onChange={(e) => onLeaveEase(e.target.value)}
              aria-label="Departure easing"
            >
              {LEAVE_EASE_OPTIONS.map((opt) => (
                <option key={opt.id} value={opt.value}>
                  Leave: {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <p className="g6-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-lifecycle">Lifecycle</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-physics">Physics</a>
        </p>
      </header>

      <p className="g6-lab__note">{note}</p>
      <p className="g6-lab__note" style={{ marginTop: 0 }}>
        {KIND_CYCLE.map((k) => (
          <span key={k} style={{ marginRight: "0.9rem" }}>
            <span
              style={{
                display: "inline-block",
                width: "0.55rem",
                height: "0.55rem",
                borderRadius: "999px",
                background: KIND_STROKE[k],
                marginRight: "0.3rem",
              }}
            />
            {KIND_LABEL[k]}
          </span>
        ))}
      </p>
      <div className="g6-lab__stage" ref={containerRef} />
    </div>
  );
}
