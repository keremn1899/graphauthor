import { useEffect, useRef, useState } from "react";
import { Graph } from "@antv/g6";
import { CONNECT_GRAPH_DATA } from "../g6/graphData";
import {
  BASE_BEHAVIORS,
  buildEdgeOptions,
  buildNodeOptions,
  withPhysicsDrag,
} from "../g6/graphOptions";
import {
  DEFAULT_FORCE_PRESET,
  DEFAULT_FORCE_TUNING,
  FORCE_PRESETS,
  FORCE_PRESET_IDS,
  PHYSICS_ENABLED,
  birthPositionNear,
  forceTuningFromPreset,
  layoutFromTuning,
  softSettle,
  type ForcePresetId,
  type ForceTuning,
} from "../g6/forcePresets";
import { MOTION_SPINES, SPINE_IDS, type SpineId } from "../g6/motionSpines";
import "../g6/g6Lab.css";

export function G6PhysicsLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const counterRef = useRef(0);
  const addedRef = useRef<string[]>([]);

  const [spineId, setSpineId] = useState<SpineId>("breath");
  const [forceId, setForceId] = useState<ForcePresetId>(DEFAULT_FORCE_PRESET);
  const [tuning, setTuning] = useState<ForceTuning>(DEFAULT_FORCE_TUNING);
  const [note, setNote] = useState(
    PHYSICS_ENABLED
      ? "Physics owns continuity. Pick a preset, then fine-tune raw d3-force parameters."
      : "Physics is paused for now (see PHYSICS_ENABLED) — sliders still update state but the simulation isn't running.",
  );

  const applyLayout = (nextTuning: ForceTuning) => {
    if (!PHYSICS_ENABLED) return;
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    graph.stopLayout();
    graph.setLayout(layoutFromTuning(nextTuning));
    graph.layout().catch(() => {});
  };

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      data: CONNECT_GRAPH_DATA,
      node: buildNodeOptions("breath"),
      edge: buildEdgeOptions("breath"),
      layout: PHYSICS_ENABLED ? layoutFromTuning(DEFAULT_FORCE_TUNING) : undefined,
      behaviors: withPhysicsDrag(BASE_BEHAVIORS, PHYSICS_ENABLED),
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
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    graph.setNode(buildNodeOptions(id));
    graph.setEdge(buildEdgeOptions(id));
  };

  const selectPreset = (id: ForcePresetId) => {
    const next = forceTuningFromPreset(id);
    setForceId(id);
    setTuning(next);
    applyLayout(next);
    setNote(`Preset: ${FORCE_PRESETS[id].label} — ${FORCE_PRESETS[id].metaphor}`);
  };

  const updateTuning = (key: keyof ForceTuning, value: number) => {
    setTuning((prev) => {
      const next = { ...prev, [key]: value };
      applyLayout(next);
      return next;
    });
    setNote(`Tuned ${key} → ${value}`);
  };

  const addNode = async () => {
    const graph = graphRef.current;
    if (!graph) return;
    const existing = graph.getNodeData().map((n) => n.id);
    const target = existing[Math.floor(Math.random() * existing.length)];
    const id = `probe-${counterRef.current++}`;
    addedRef.current.push(id);
    const position = birthPositionNear(graph, String(target));

    graph.addNodeData([{ id, style: position }]);
    graph.addEdgeData([
      { id: `e-${id}`, source: String(target), target: id, data: { kind: "nearto" } },
    ]);
    await graph.draw();
    softSettle(graph);
    setNote(`Added "${id}" — watch how the current physics settles it.`);
  };

  const removeNode = async () => {
    const graph = graphRef.current;
    if (!graph) return;
    const id = addedRef.current.pop();
    if (!id) {
      setNote("Nothing left to remove.");
      return;
    }
    graph.removeNodeData([id]);
    await graph.draw();
    softSettle(graph);
    setNote(`Removed "${id}".`);
  };

  const reheat = () => {
    if (!PHYSICS_ENABLED) {
      setNote("Reheat needs physics, which is paused for now.");
      return;
    }
    const graph = graphRef.current;
    if (!graph) return;
    graph.stopLayout();
    graph.setLayout((prev) => ({
      ...prev,
      alpha: 0.3,
      alphaTarget: tuning.alphaTarget,
    }));
    graph.layout().catch(() => {});
    setNote("Reheated simulation — feel the current tuning on an already-settled graph.");
  };

  const sliders: Array<{
    key: keyof ForceTuning;
    label: string;
    min: number;
    max: number;
    step: number;
  }> = [
    { key: "manyBodyStrength", label: "Charge", min: -400, max: -40, step: 10 },
    { key: "linkDistance", label: "Link dist", min: 60, max: 240, step: 5 },
    { key: "linkStrength", label: "Link str", min: 0.05, max: 1, step: 0.05 },
    { key: "collideRadius", label: "Collide r", min: 24, max: 72, step: 2 },
    { key: "collideStrength", label: "Collide str", min: 0.1, max: 1, step: 0.05 },
    { key: "velocityDecay", label: "Velocity decay", min: 0.1, max: 0.7, step: 0.02 },
    { key: "alphaDecay", label: "Alpha decay", min: 0.005, max: 0.05, step: 0.001 },
    { key: "alphaTarget", label: "Alpha target", min: 0, max: 0.05, step: 0.001 },
  ];

  return (
    <div className="g6-lab">
      <header className="g6-lab__chrome">
        <p className="g6-lab__eyebrow">Design lab</p>
        <h1 className="g6-lab__title">G6 physics — force character</h1>
        <p className="g6-lab__lede">
          {PHYSICS_ENABLED
            ? "d3-force owns continuity. "
            : "Physics is paused for now — dragging one node never disturbs the rest. "}
          <strong>Glide</strong> is the Field default —
          other presets are contrast. Sliders expose the raw parameters underneath.
        </p>

        <div className="g6-lab__controls">
          <div className="g6-lab__control-row">
            <span className="g6-lab__control-label">Preset</span>
            {FORCE_PRESET_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={"g6-lab__chip" + (forceId === id ? " g6-lab__chip--active" : "")}
                onClick={() => selectPreset(id)}
                title={FORCE_PRESETS[id].metaphor}
              >
                {FORCE_PRESETS[id].label}
              </button>
            ))}
          </div>

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
            <span className="g6-lab__control-label">Forces</span>
            {sliders.map((s) => (
              <label key={s.key} className="g6-lab__slider">
                {s.label}
                <input
                  type="range"
                  min={s.min}
                  max={s.max}
                  step={s.step}
                  value={tuning[s.key]}
                  onChange={(e) => updateTuning(s.key, Number(e.target.value))}
                />
                {typeof tuning[s.key] === "number" && tuning[s.key] < 1
                  ? tuning[s.key].toFixed(3)
                  : tuning[s.key]}
              </label>
            ))}
          </div>
        </div>

        <div className="g6-lab__actions">
          <button type="button" onClick={addNode}>
            Add node
          </button>
          <button type="button" onClick={removeNode}>
            Remove last added
          </button>
          <button type="button" onClick={reheat}>
            Reheat
          </button>
        </div>

        <p className="g6-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-connect">Connect</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-lifecycle">Lifecycle</a>
        </p>
      </header>

      <p className="g6-lab__note">{note}</p>
      <div className="g6-lab__stage" ref={containerRef} />
    </div>
  );
}
