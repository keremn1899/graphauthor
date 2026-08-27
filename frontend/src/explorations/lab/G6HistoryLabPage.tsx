import { useEffect, useRef, useState } from "react";
import {
  Graph,
  History,
  HistoryEvent,
  type GraphData,
  type IElementEvent,
} from "@antv/g6";
import "../g6/g6Lab.css";
import "./G6HistoryLabPage.css";

const HISTORY_KEY = "history-lab";

const INITIAL_DATA: GraphData = {
  nodes: [
    { id: "question", data: { label: "Question" }, style: { x: 430, y: 120 } },
    { id: "source", data: { label: "Source" }, style: { x: 235, y: 255 } },
    { id: "claim", data: { label: "Claim" }, style: { x: 430, y: 300 } },
    { id: "counter", data: { label: "Counterpoint" }, style: { x: 625, y: 255 } },
    { id: "finding", data: { label: "Finding" }, style: { x: 430, y: 480 } },
  ],
  edges: [
    { id: "e-question-source", source: "question", target: "source" },
    { id: "e-question-claim", source: "question", target: "claim" },
    { id: "e-question-counter", source: "question", target: "counter" },
    { id: "e-source-finding", source: "source", target: "finding" },
    { id: "e-claim-finding", source: "claim", target: "finding" },
    { id: "e-counter-finding", source: "counter", target: "finding" },
  ],
};

type HistoryCommand = History["undoStack"][number];

type TimelineState = {
  entries: string[];
  cursor: number;
  canUndo: boolean;
  canRedo: boolean;
};

const EMPTY_TIMELINE: TimelineState = {
  entries: [],
  cursor: 0,
  canUndo: false,
  canRedo: false,
};

function countData(data: GraphData) {
  return {
    nodes: data.nodes?.length ?? 0,
    edges: data.edges?.length ?? 0,
    combos: data.combos?.length ?? 0,
  };
}

function commandLabel(command: HistoryCommand, index: number) {
  const added = countData(command.current.add);
  const updated = countData(command.current.update);
  const removed = countData(command.current.remove);

  if (added.nodes && added.edges) return `Add thought ${index}`;
  if (added.nodes) return `Add node ${index}`;
  if (removed.nodes) return `Remove node ${index}`;
  if (updated.nodes) {
    const node = command.current.update.nodes?.[0];
    const label = node?.data?.label;
    return typeof label === "string" ? `Rename to “${label}”` : `Move node ${index}`;
  }
  if (added.edges) return `Add relation ${index}`;
  if (removed.edges) return `Remove relation ${index}`;
  if (updated.edges || updated.combos || added.combos || removed.combos) {
    return `Graph edit ${index}`;
  }
  return `Change ${index}`;
}

function snapshotHistory(history: History): TimelineState {
  const commands = [
    ...history.undoStack,
    ...history.redoStack.slice().reverse(),
  ];
  return {
    entries: commands.map((command, index) => commandLabel(command, index + 1)),
    cursor: history.undoStack.length,
    canUndo: history.canUndo(),
    canRedo: history.canRedo(),
  };
}

function cloneInitialData() {
  return structuredClone(INITIAL_DATA);
}

export function G6HistoryLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const historyRef = useRef<History | null>(null);
  const selectedIdRef = useRef("claim");
  const thoughtCounterRef = useRef(1);

  const [timeline, setTimeline] = useState<TimelineState>(EMPTY_TIMELINE);
  const [selectedId, setSelectedId] = useState("claim");
  const [status, setStatus] = useState(
    "Ready. Make an edit, drag a node, or walk the timeline.",
  );

  const syncTimeline = (message?: string) => {
    const history = historyRef.current;
    if (!history) return;
    setTimeline(snapshotHistory(history));
    if (message) setStatus(message);
  };

  const undo = () => {
    const history = historyRef.current;
    if (!history?.canUndo()) return;
    history.undo();
    syncTimeline("Rolled back one graph command.");
  };

  const redo = () => {
    const history = historyRef.current;
    if (!history?.canRedo()) return;
    history.redo();
    syncTimeline("Replayed one graph command.");
  };

  const seek = (target: number) => {
    const history = historyRef.current;
    if (!history) return;
    while (history.undoStack.length > target && history.canUndo()) history.undo();
    while (history.undoStack.length < target && history.canRedo()) history.redo();
    syncTimeline(
      target === 0
        ? "Rolled back to the initial graph."
        : `Moved to checkpoint ${target} of ${
            history.undoStack.length + history.redoStack.length
          }.`,
    );
  };

  const addThought = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;

    const index = thoughtCounterRef.current++;
    const id = `thought-${index}`;
    const parentId = selectedIdRef.current;
    const parent = graph.getNodeData(parentId);
    const x = Number(parent.style?.x ?? 430);
    const y = Number(parent.style?.y ?? 300);
    const angle = index * 1.8;

    graph.addData({
      nodes: [
        {
          id,
          data: { label: `Thought ${index}` },
          style: {
            x: x + Math.cos(angle) * 150,
            y: y + Math.sin(angle) * 125,
          },
        },
      ],
      edges: [{ id: `e-${parentId}-${id}`, source: parentId, target: id }],
    });
    await graph.draw();
    selectedIdRef.current = id;
    setSelectedId(id);
    setStatus(`Added “Thought ${index}” from ${parentId}.`);
  };

  const renameSelected = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    const id = selectedIdRef.current;
    if (!graph.getNodeData().some((node) => String(node.id) === id)) {
      setStatus("Select a visible node before renaming.");
      return;
    }
    const next = `Revised ${thoughtCounterRef.current++}`;
    graph.updateNodeData([{ id, data: { label: next } }]);
    await graph.draw();
    setStatus(`Renamed ${id} to “${next}”.`);
  };

  const removeSelected = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    const id = selectedIdRef.current;
    if (id === "question") {
      setStatus("The root question is kept as the stable starting point.");
      return;
    }
    if (!graph.getNodeData().some((node) => String(node.id) === id)) {
      setStatus("Select a visible node before removing.");
      return;
    }
    graph.removeNodeData([id]);
    await graph.draw();
    selectedIdRef.current = "question";
    setSelectedId("question");
    setStatus(`Removed ${id} and its connected relations.`);
  };

  const clearHistory = () => {
    historyRef.current?.clear();
    syncTimeline("Cleared history. The current graph is the new baseline.");
  };

  const reset = async () => {
    const graph = graphRef.current;
    const history = historyRef.current;
    if (!graph || graph.destroyed || !history) return;
    graph.setData(cloneInitialData());
    await graph.draw();
    history.clear();
    thoughtCounterRef.current = 1;
    selectedIdRef.current = "claim";
    setSelectedId("claim");
    syncTimeline("Reset the graph and cleared both history stacks.");
  };

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;

    const graph = new Graph({
      container: containerRef.current,
      data: cloneInitialData(),
      animation: true,
      node: {
        style: {
          size: 76,
          fill: "#f8f6f0",
          stroke: "#1e211c",
          lineWidth: 1.5,
          labelText: (datum) => String(datum.data?.label ?? datum.id),
          labelPlacement: "center",
          labelFontFamily: '"IBM Plex Sans", sans-serif',
          labelFontSize: 11,
          labelFontWeight: 600,
          labelWordWrap: true,
          labelMaxWidth: "78%",
          labelMaxLines: 2,
        },
        state: {
          selected: {
            fill: "#dbe8c8",
            stroke: "#2c451d",
            lineWidth: 2.5,
          },
        },
      },
      edge: {
        style: {
          stroke: "#a5a99f",
          lineWidth: 1.4,
          endArrow: true,
          endArrowType: "triangle",
          endArrowSize: 7,
        },
      },
      behaviors: ["drag-canvas", "zoom-canvas", "drag-element", "click-select"],
      plugins: [
        {
          type: "history",
          key: HISTORY_KEY,
          stackSize: 20,
        },
        "grid-line",
      ],
    });

    graphRef.current = graph;

    graph
      .render()
      .then(() => {
        if (cancelled || graph.destroyed) return;
        const history = graph.getPluginInstance<History>(HISTORY_KEY);
        historyRef.current = history;
        history.clear();

        history.on(HistoryEvent.ADD, () => syncTimeline());
        history.on(HistoryEvent.UNDO, () => syncTimeline());
        history.on(HistoryEvent.REDO, () => syncTimeline());
        history.on(HistoryEvent.CLEAR, () => syncTimeline());

        syncTimeline();
      })
      .catch(() => {
        if (!cancelled) setStatus("G6 could not initialize the history lab.");
      });

    graph.on("node:click", (event) => {
      const id = String((event as IElementEvent).target.id);
      selectedIdRef.current = id;
      setSelectedId(id);
    });

    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return;
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      cancelled = true;
      window.removeEventListener("keydown", onKeyDown);
      historyRef.current = null;
      graphRef.current = null;
      graph.destroy();
    };
  }, []);

  return (
    <main className="g6-lab history-lab">
      <header className="g6-lab__chrome history-lab__chrome">
        <p className="g6-lab__eyebrow">G6 plugin lab</p>
        <h1 className="g6-lab__title">History — roll the graph backward</h1>
        <p className="g6-lab__lede">
          This page uses G6 5’s native <code>history</code> plugin. Every draw
          records graph data changes; undo and redo replay the plugin’s commands.
          Dragging is history too. The timeline below is read directly from G6’s
          undo and redo stacks.
        </p>

        <div className="g6-lab__actions history-lab__actions">
          <button type="button" onClick={undo} disabled={!timeline.canUndo}>
            ← Undo
          </button>
          <button type="button" onClick={redo} disabled={!timeline.canRedo}>
            Redo →
          </button>
          <span className="history-lab__action-divider" aria-hidden />
          <button type="button" onClick={() => void addThought()}>
            Add thought
          </button>
          <button type="button" onClick={() => void renameSelected()}>
            Rename selected
          </button>
          <button type="button" onClick={() => void removeSelected()}>
            Remove selected
          </button>
          <span className="history-lab__action-divider" aria-hidden />
          <button type="button" onClick={clearHistory}>
            Clear history
          </button>
          <button type="button" onClick={() => void reset()}>
            Reset
          </button>
        </div>

        <p className="g6-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a
            href="https://g6.antv.antgroup.com/en/manual/plugin/history"
            target="_blank"
            rel="noreferrer"
          >
            G6 History docs ↗
          </a>
        </p>
      </header>

      <section className="history-lab__workspace">
        <div className="history-lab__graph-column">
          <div className="history-lab__status" aria-live="polite">
            <span>{status}</span>
            <span>Selected: {selectedId}</span>
          </div>
          <div className="g6-lab__stage history-lab__stage" ref={containerRef} />
          <p className="history-lab__hint">
            Try: add → rename → drag → remove, then click any checkpoint. Keyboard:
            Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z.
          </p>
        </div>

        <aside className="history-lab__timeline" aria-label="Graph history timeline">
          <div className="history-lab__timeline-heading">
            <div>
              <p className="g6-lab__eyebrow">Native command stack</p>
              <h2>Timeline</h2>
            </div>
            <output>
              {timeline.cursor}/{timeline.entries.length}
            </output>
          </div>

          <input
            className="history-lab__scrubber"
            type="range"
            min={0}
            max={Math.max(0, timeline.entries.length)}
            value={timeline.cursor}
            onChange={(event) => seek(Number(event.target.value))}
            aria-label="History checkpoint"
            disabled={timeline.entries.length === 0}
          />

          <ol className="history-lab__checkpoints">
            <li
              className={timeline.cursor === 0 ? "is-current" : "is-applied"}
            >
              <button type="button" onClick={() => seek(0)}>
                <span className="history-lab__dot" />
                <span>
                  <strong>Baseline</strong>
                  <small>Initial graph</small>
                </span>
              </button>
            </li>
            {timeline.entries.map((entry, index) => {
              const checkpoint = index + 1;
              const state =
                checkpoint === timeline.cursor
                  ? "is-current"
                  : checkpoint < timeline.cursor
                    ? "is-applied"
                    : "is-future";
              return (
                <li className={state} key={`${checkpoint}-${entry}`}>
                  <button type="button" onClick={() => seek(checkpoint)}>
                    <span className="history-lab__dot" />
                    <span>
                      <strong>{entry}</strong>
                      <small>
                        {checkpoint === timeline.cursor
                          ? "Current graph"
                          : checkpoint < timeline.cursor
                            ? "Applied"
                            : "Rolled back"}
                      </small>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>

          <div className="history-lab__research">
            <p className="g6-lab__eyebrow">What this verifies</p>
            <ul>
              <li>Data edits become commands after <code>draw()</code>.</li>
              <li>Undo/redo restores nodes, edges, labels, and positions.</li>
              <li><code>stackSize: 20</code> caps retained commands.</li>
              <li><code>clear()</code> makes the live graph a new baseline.</li>
            </ul>
          </div>
        </aside>
      </section>
    </main>
  );
}
