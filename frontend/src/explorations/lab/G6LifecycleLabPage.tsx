import { useEffect, useRef, useState } from "react";
import { Graph, type GraphData } from "@antv/g6";
import { LIFECYCLE_GRAPH_DATA } from "../g6/graphData";
import {
  BASE_BEHAVIORS,
  buildEdgeOptions,
  buildNodeOptions,
  withPhysicsDrag,
} from "../g6/graphOptions";
import {
  DEFAULT_FORCE_PRESET,
  FORCE_PRESETS,
  FORCE_PRESET_IDS,
  PHYSICS_ENABLED,
  birthPositionNear,
  type ForcePresetId,
} from "../g6/forcePresets";
import { MOTION_SPINES, SPINE_IDS, type SpineId } from "../g6/motionSpines";
import { ensureIntentionD3ForceRegistered } from "../g6/intentionD3Force";
import "../g6/g6Lab.css";

function lifecycleData(): GraphData {
  return structuredClone(LIFECYCLE_GRAPH_DATA);
}

function intentionLayout(forceId: ForcePresetId = DEFAULT_FORCE_PRESET) {
  return {
    ...FORCE_PRESETS[forceId].layout,
    type: "intention-d3-force",
    animation: true,
    center: false,
  } as unknown as typeof FORCE_PRESETS[ForcePresetId]["layout"];
}

function SpineMiniStage({
  spineId,
  onReady,
  onDispose,
}: {
  spineId: SpineId;
  onReady: (spineId: SpineId, graph: Graph) => void;
  onDispose: (spineId: SpineId) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    ensureIntentionD3ForceRegistered();

    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      data: lifecycleData(),
      node: buildNodeOptions(spineId),
      edge: buildEdgeOptions(spineId),
      layout: PHYSICS_ENABLED ? intentionLayout() : undefined,
      behaviors: withPhysicsDrag(BASE_BEHAVIORS, PHYSICS_ENABLED),
    });

    graph.render().catch(() => {});
    graphRef.current = graph;
    onReady(spineId, graph);

    return () => {
      onDispose(spineId);
      graph.destroy();
      graphRef.current = null;
    };
  }, [spineId, onReady, onDispose]);

  return (
    <div className="g6-lab__mini-stage-wrap">
      <p className="g6-lab__mini-label">
        {MOTION_SPINES[spineId].label}
        <span className="g6-lab__mini-metaphor">{MOTION_SPINES[spineId].metaphor}</span>
      </p>
      <div className="g6-lab__mini-stage" ref={containerRef} />
    </div>
  );
}

export function G6LifecycleLabPage() {
  const graphsRef = useRef<Partial<Record<SpineId, Graph>>>({});
  const counterRef = useRef(0);
  const addedRef = useRef<string[]>([]);

  const [forceId, setForceId] = useState<ForcePresetId>(DEFAULT_FORCE_PRESET);
  const [note, setNote] = useState(
    "Four spines, same physics. Add/remove fires across all stages simultaneously.",
  );

  const handleReady = useRef((spineId: SpineId, graph: Graph) => {
    graphsRef.current[spineId] = graph;
  }).current;

  const handleDispose = useRef((spineId: SpineId) => {
    delete graphsRef.current[spineId];
  }).current;

  const pickForce = (id: ForcePresetId) => {
    setForceId(id);
    if (!PHYSICS_ENABLED) return;
    for (const spine of SPINE_IDS) {
      const graph = graphsRef.current[spine];
      if (!graph || graph.destroyed) continue;
      graph.stopLayout();
      graph.setLayout(intentionLayout(id));
      graph.layout().catch(() => {});
    }
  };

  const addNode = async () => {
    const graphs = graphsRef.current;
    const ids = SPINE_IDS.filter((id) => graphs[id]);
    if (!ids.length) return;

    const sample = graphs[ids[0]];
    if (!sample) return;
    const existing = sample.getNodeData().map((n) => n.id);
    const target = existing[Math.floor(Math.random() * existing.length)];
    const id = `bud-${counterRef.current++}`;
    addedRef.current.push(id);

    await Promise.all(
      ids.map(async (spineId) => {
        const graph = graphs[spineId];
        if (!graph || graph.destroyed) return;
        const style = birthPositionNear(graph, String(target));
        graph.addNodeData([{ id, style }]);
        graph.addEdgeData([
          { id: `e-${id}`, source: String(target), target: id, data: { kind: "leadsto" } },
        ]);
        await graph.draw();
      }),
    );

    setNote(`Born "${id}" from "${target}" — compare how each spine punctuates the same event.`);
  };

  const removeNode = async () => {
    const graphs = graphsRef.current;
    const id = addedRef.current.pop();
    if (!id) {
      setNote("Nothing left to remove.");
      return;
    }

    await Promise.all(
      SPINE_IDS.map(async (spineId) => {
        const graph = graphs[spineId];
        if (!graph || graph.destroyed) return;
        graph.removeNodeData([id]);
        // Stop any in-flight force tick before exit so d3-force doesn't
        // chase a node that's being demolished ("Node not found").
        try {
          graph.stopLayout();
        } catch {
          /* destroyed / not running */
        }
        await graph.draw();
      }),
    );

    setNote(`Removed "${id}" — death character should differ spine to spine.`);
  };

  return (
    <div className="g6-lab">
      <header className="g6-lab__chrome">
        <p className="g6-lab__eyebrow">Design lab</p>
        <h1 className="g6-lab__title">G6 lifecycle — birth &amp; death</h1>
        <p className="g6-lab__lede">
          Five animation spines side by side.{" "}
          {PHYSICS_ENABLED
            ? "Physics is held constant so the only variable is punctuation — how each spine handles the same birth and death."
            : "Physics is paused for now, so positions are static and the only variable is punctuation — how each spine handles the same birth and death."}
        </p>

        <div className="g6-lab__controls">
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
        </div>

        <div className="g6-lab__actions">
          <button type="button" onClick={addNode}>
            Add node
          </button>
          <button type="button" onClick={removeNode}>
            Remove last added
          </button>
        </div>

        <p className="g6-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-seed">Seed curve</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-connect">Connect</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/g6-physics">Physics</a>
        </p>
      </header>

      <p className="g6-lab__note">{note}</p>

      <div className="g6-lab__stages-grid">
        {SPINE_IDS.map((spineId) => (
          <SpineMiniStage
            key={spineId}
            spineId={spineId}
            onReady={handleReady}
            onDispose={handleDispose}
          />
        ))}
      </div>
    </div>
  );
}
