import { useEffect, useRef, useState } from "react";
import {
  Graph,
  type EdgeData,
  type GraphData,
  type IPointerEvent,
  type LayoutOptions,
  type NodeData,
} from "@antv/g6";
import {
  ACTIVITY_BY_ID,
  GRAPH_CHECKPOINTS,
  type Activity,
  type GraphCheckpoint,
} from "./architectureActivityData";
import {
  BASE_EDGE_STATE,
  BASE_NODE_STATE,
  NODE_FONTS,
} from "../g6/graphOptions";
import { FORCE_PRESETS } from "../g6/forcePresets";
import { ensureContainsEdgeRegistered } from "../g6/containsEdge";
import {
  LENS_EDGE_STYLE,
  LENS_EDGE_TYPE,
} from "../g6/lensEdgeOptions";
import "../g6/g6Lab.css";
import "./G6HistoryOverlayLabPage.css";

function graphDataForCheckpoint(checkpoint: GraphCheckpoint): GraphData {
  const changedNodes = new Set(checkpoint.changedNodeIds);
  const changedEdges = new Set(checkpoint.changedEdgeIds);
  const tone =
    checkpoint.eventType === "graph.reverted" ? "reverted" : "committed";

  return {
    nodes: (checkpoint.graphData.nodes ?? []).map((node) => ({
      ...structuredClone(node),
      data: {
        ...structuredClone(node.data),
        checkpointChanged: changedNodes.has(String(node.id)),
        checkpointTone: tone,
      },
    })),
    edges: (checkpoint.graphData.edges ?? []).map((edge) => ({
      ...structuredClone(edge),
      data: {
        ...structuredClone(edge.data),
        checkpointChanged: changedEdges.has(String(edge.id)),
        checkpointTone: tone,
      },
    })),
  };
}

function selectedActivity(checkpoint: GraphCheckpoint): Activity | undefined {
  return checkpoint.activityId
    ? ACTIVITY_BY_ID.get(checkpoint.activityId)
    : undefined;
}

function writeEvent(activity: Activity | undefined) {
  return activity?.events.find(
    (event) =>
      event.type === "graph.committed" || event.type === "graph.reverted",
  );
}

function isChanged(datum: NodeData | EdgeData) {
  return Boolean(datum.data?.checkpointChanged);
}

const HISTORY_NODE_SIZE = 88;

/** Spacious structural seed — places the graph before soft physics takes over. */
function dagreSeedLayout(): LayoutOptions {
  return {
    type: "antv-dagre",
    rankdir: "TB",
    // Wide gaps for 88px discs so ranks don't stack into each other.
    nodesep: 120,
    ranksep: 180,
    controlPoints: false,
    animation: false,
  };
}

function glideLooseLayout(): LayoutOptions {
  return {
    ...FORCE_PRESETS["glide-loose"].layout,
    // Match dagre spacing so soft physics doesn't collapse the ranks.
    link: { distance: 280, strength: 0.04, iterations: 1 },
    manyBody: false,
    collide: { radius: 48, strength: 1, iterations: 3 },
    center: false,
    velocityDecay: 0.42,
    animation: true,
  } as LayoutOptions;
}

async function seedThenSoftPhysics(graph: Graph) {
  if (graph.destroyed) return;
  try {
    graph.stopLayout();
  } catch {
    /* ok */
  }
  graph.setLayout(dagreSeedLayout());
  await graph.layout();
  if (graph.destroyed) return;
  try {
    graph.stopLayout();
  } catch {
    /* ok */
  }
  graph.setLayout(glideLooseLayout());
  await graph.layout();
}

function CheckpointActivity({
  activity,
  open,
  onToggle,
}: {
  activity: Activity;
  open: boolean;
  onToggle: () => void;
}) {
  const event = writeEvent(activity);

  return (
    <article className={`history-overlay-lab__activity is-${activity.tone}`}>
      <button
        type="button"
        className="history-overlay-lab__activity-summary"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className={`history-overlay-lab__activity-outcome is-${activity.tone}`}>
          {activity.outcome}
        </span>
        <span className="history-overlay-lab__activity-copy">
          <strong>{activity.title}</strong>
          <small>
            {activity.actor} · {activity.authority} · {activity.reference}
          </small>
        </span>
        <span className="history-overlay-lab__activity-stats">
          <strong>{activity.events.length}</strong>
          <small>related events</small>
        </span>
        <span className="history-overlay-lab__activity-toggle" aria-hidden>
          {open ? "×" : "Details"}
        </span>
      </button>

      {open ? (
        <div className="history-overlay-lab__sheet">
          <div className="history-overlay-lab__sheet-intro">
            <section>
              <p className="history-overlay-lab__section-label">Rationale</p>
              <p>{activity.rationale}</p>
            </section>
            <section>
              <p className="history-overlay-lab__section-label">Evidence</p>
              <ul>
                {activity.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          </div>

          {activity.graphDiff ? (
            <section className="history-overlay-lab__sheet-diff">
              <p className="history-overlay-lab__section-label">Graph diff</p>
              <div>
                <span className="is-add">+</span>
                <p>{activity.graphDiff.added.join(" · ") || "Nothing added"}</p>
                <span className="is-change">~</span>
                <p>{activity.graphDiff.changed.join(" · ") || "Nothing changed"}</p>
                <span className="is-remove">−</span>
                <p>{activity.graphDiff.removed.join(" · ") || "Nothing removed"}</p>
              </div>
            </section>
          ) : null}

          <section className="history-overlay-lab__sheet-events">
            <div className="history-overlay-lab__sheet-events-heading">
              <div>
                <p className="history-overlay-lab__section-label">
                  Correlated events
                </p>
                <p>Only the graph write creates a timeline checkpoint.</p>
              </div>
              {event ? <code>{event.id}</code> : null}
            </div>
            <ol>
              {activity.events.map((item, index) => {
                const isWrite =
                  item.type === "graph.committed" ||
                  item.type === "graph.reverted";
                return (
                  <li className={isWrite ? "is-write" : ""} key={item.id}>
                    <span className={`history-overlay-lab__event-dot is-${item.tone}`} />
                    <div>
                      <code>{item.type}</code>
                      <p>{item.summary}</p>
                      <small>
                        {item.time} · {item.actor}
                        {index > 0
                          ? ` · caused by ${activity.events[index - 1].id}`
                          : ""}
                      </small>
                    </div>
                    {isWrite ? <strong>Checkpoint</strong> : null}
                  </li>
                );
              })}
            </ol>
          </section>
        </div>
      ) : null}
    </article>
  );
}

export function G6HistoryOverlayLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [checkpointIndex, setCheckpointIndex] = useState(
    GRAPH_CHECKPOINTS.length - 1,
  );
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [graphReady, setGraphReady] = useState(false);

  const checkpoint = GRAPH_CHECKPOINTS[checkpointIndex];
  const activity = selectedActivity(checkpoint);
  const nodeCount = checkpoint.graphData.nodes?.length ?? 0;
  const edgeCount = checkpoint.graphData.edges?.length ?? 0;

  const selectCheckpoint = (index: number) => {
    const next = Math.max(0, Math.min(GRAPH_CHECKPOINTS.length - 1, index));
    setCheckpointIndex(next);
    setDetailsOpen(false);
  };

  useEffect(() => {
    if (!containerRef.current) return;
    ensureContainsEdgeRegistered();
    let cancelled = false;
    const initial = GRAPH_CHECKPOINTS[GRAPH_CHECKPOINTS.length - 1];

    const graph = new Graph({
      container: containerRef.current,
      data: graphDataForCheckpoint(initial),
      animation: true,
      autoFit: {
        type: "view",
        options: { when: "always", direction: "both" },
        animation: false,
      },
      padding: [62, 46, 190, 46],
      // Soft physics only on construct — seedThenSoftPhysics owns the radial pass.
      layout: glideLooseLayout(),
      node: {
        style: {
          size: HISTORY_NODE_SIZE,
          fill: "#111",
          fillOpacity: 1,
          stroke: "#111",
          strokeOpacity: 1,
          lineWidth: (datum) => (isChanged(datum) ? 2.5 : 1),
          lineDash: (datum) =>
            datum.data?.checkpointChanged &&
            datum.data?.checkpointTone === "reverted"
              ? ([0, 6.5] as [number, number])
              : undefined,
          lineCap: "round",
          halo: isChanged,
          haloStroke: "#111",
          haloLineWidth: 1,
          haloStrokeOpacity: 1,
          labelText: (datum) => String(datum.data?.label ?? datum.id),
          labelPlacement: "center",
          labelFill: "#fff",
          labelFontFamily: NODE_FONTS.plexCondensed.family,
          labelFontSize: 11,
          labelFontWeight: 600,
          labelLineHeight: 13,
          labelWordWrap: true,
          labelMaxWidth: "76%",
          labelMaxLines: 2,
          cursor: "grab",
        },
        state: BASE_NODE_STATE,
      },
      edge: {
        type: LENS_EDGE_TYPE,
        style: {
          ...LENS_EDGE_STYLE,
          strokeOpacity: 1,
          increasedLineWidthForHitTesting: 20,
          labelText: (datum) => String(datum.data?.label ?? ""),
          labelFontFamily: '"IBM Plex Mono", monospace',
          labelFontSize: 7,
          labelFill: "#555",
          labelBackground: true,
          labelBackgroundFill: "#fff",
          labelBackgroundOpacity: 0.94,
          labelPadding: [2, 3],
          labelOpacity: 0,
        },
        state: {
          ...BASE_EDGE_STATE,
          active: {
            ...BASE_EDGE_STATE.active,
            labelOpacity: 1,
          },
        },
      },
      behaviors: [
        "drag-canvas",
        "zoom-canvas",
        "click-select",
        {
          type: "hover-activate",
          degree: 0,
          animation: true,
          enable: (event: IPointerEvent) => event.targetType === "edge",
        },
        { type: "drag-element-force", fixed: false },
      ],
    });

    graphRef.current = graph;
    graph
      .render()
      .then(async () => {
        if (cancelled || graph.destroyed) return;
        await seedThenSoftPhysics(graph);
        if (cancelled || graph.destroyed) return;
        setGraphReady(true);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      graphRef.current = null;
      try {
        graph.stopLayout();
      } catch {
        /* already stopped */
      }
      graph.destroy();
    };
  }, []);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graphReady || !graph || graph.destroyed) return;
    let cancelled = false;

    try {
      graph.stopLayout();
    } catch {
      /* first layout may already be settled */
    }
    graph.setData(graphDataForCheckpoint(checkpoint));
    graph
      .draw()
      .then(async () => {
        if (cancelled || graph.destroyed) return;
        await seedThenSoftPhysics(graph);
        if (cancelled || graph.destroyed) return;
        await graph.fitView({ when: "always", direction: "both" }, false);
        if (
          !cancelled &&
          !graph.destroyed &&
          (containerRef.current?.clientWidth ?? 0) > 900
        ) {
          await graph.zoomTo(graph.getZoom() * 1.35, false);
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [checkpoint, graphReady]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") selectCheckpoint(checkpointIndex - 1);
      if (event.key === "ArrowRight") selectCheckpoint(checkpointIndex + 1);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [checkpointIndex]);

  return (
    <main className="history-overlay-lab">
      <header className="history-overlay-lab__header">
        <div>
          <p>Architecture governance · graph writes</p>
          <h1>Graph activity</h1>
        </div>
        <nav>
          <a href="#/explorations">Explorations</a>
          <a href="#/explorations/architecture-activity">Full activity ledger</a>
        </nav>
      </header>

      <section className="history-overlay-lab__stage-shell">
        <div className="history-overlay-lab__stage" ref={containerRef} />

        <div className="history-overlay-lab__graph-meta">
          <span>platform-core</span>
          <strong>V{checkpoint.version}</strong>
          <span>
            {nodeCount} nodes · {edgeCount} edges
          </span>
        </div>

        {activity ? (
          <CheckpointActivity
            activity={activity}
            open={detailsOpen}
            onToggle={() => setDetailsOpen((value) => !value)}
          />
        ) : (
          <article className="history-overlay-lab__activity is-baseline">
            <div className="history-overlay-lab__baseline">
              <span>Baseline</span>
              <strong>Graph V10 · ownership change active</strong>
              <small>
                Starting snapshot for this example chronology. No event is
                synthesized for the baseline.
              </small>
            </div>
          </article>
        )}

        <div className="history-overlay-lab__timeline">
          <button
            type="button"
            className="history-overlay-lab__step"
            onClick={() => selectCheckpoint(checkpointIndex - 1)}
            disabled={checkpointIndex === 0}
            aria-label="Previous graph write"
          >
            ←
          </button>

          <div className="history-overlay-lab__timeline-copy">
            <span>{checkpoint.eventType}</span>
            <strong>{checkpoint.label}</strong>
            <small>{checkpoint.occurredAt}</small>
          </div>

          <div className="history-overlay-lab__rail">
            <div className="history-overlay-lab__markers">
              {GRAPH_CHECKPOINTS.map((item, index) => (
                <button
                  type="button"
                  key={item.id}
                  className={[
                    index === checkpointIndex ? "is-current" : "",
                    index < checkpointIndex ? "is-past" : "",
                    item.eventType === "graph.reverted" ? "is-revert" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => selectCheckpoint(index)}
                  aria-label={`${item.shortLabel}: ${item.label}`}
                >
                  <span />
                  <strong>{item.shortLabel}</strong>
                  <small>{item.eventType === "baseline" ? "start" : item.eventType.replace("graph.", "")}</small>
                </button>
              ))}
            </div>
            <input
              type="range"
              min={0}
              max={GRAPH_CHECKPOINTS.length - 1}
              value={checkpointIndex}
              onChange={(event) => selectCheckpoint(Number(event.target.value))}
              aria-label="Graph write timeline"
            />
          </div>

          <div className="history-overlay-lab__version">
            <span>Version</span>
            <strong>
              {checkpointIndex === 0
                ? "V10"
                : `V${GRAPH_CHECKPOINTS[checkpointIndex - 1].version} → V${checkpoint.version}`}
            </strong>
          </div>

          <button
            type="button"
            className="history-overlay-lab__step"
            onClick={() => selectCheckpoint(checkpointIndex + 1)}
            disabled={checkpointIndex === GRAPH_CHECKPOINTS.length - 1}
            aria-label="Next graph write"
          >
            →
          </button>
        </div>
      </section>
    </main>
  );
}
