import { useEffect, useRef, useState } from "react";
import { Graph, type GraphData, type ID } from "@antv/g6";
import "./G6ComboLabPage.css";

/**
 * Minimal G6 demo — deliberately NOT reusing our node/edge visual language.
 * The point is to see what G6 gives us for free: combos as real containment
 * (instead of our hand-drawn CONTAINS paren), and what happens to ordinary
 * edges when they cross a combo boundary and that combo collapses.
 */
const DATA: GraphData = {
  nodes: [
    { id: "login", combo: "session" },
    { id: "token", combo: "session" },
    { id: "refresh", combo: "session" },
    { id: "audit", combo: "logging" },
    { id: "trace", combo: "logging" },
    { id: "dashboard" },
  ],
  edges: [
    { id: "e-login-token", source: "login", target: "token" },
    { id: "e-token-refresh", source: "token", target: "refresh" },
    { id: "e-audit-trace", source: "audit", target: "trace" },
    // Crosses the session → logging combo boundary — watch this one when
    // you collapse either group.
    { id: "e-token-audit", source: "token", target: "audit" },
    // Edges landing directly on a combo id, not a node inside it.
    { id: "e-dash-session", source: "dashboard", target: "session" },
    { id: "e-dash-logging", source: "dashboard", target: "logging" },
  ],
  combos: [
    { id: "session", data: { label: "Session" } },
    { id: "logging", data: { label: "Logging" } },
  ],
};

export function G6ComboLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const [note, setNote] = useState(
    "Double-click a combo to collapse or expand it.",
  );

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph({
      container: containerRef.current,
      autoFit: "view",
      data: DATA,
      node: {
        style: {
          size: 44,
          labelText: (d) => String(d.id),
          labelPlacement: "center",
          labelFill: "#fff",
          labelFontWeight: 600,
        },
        palette: {
          type: "group",
          field: (d) => (d.combo ? String(d.combo) : "none"),
        },
      },
      edge: {
        style: {
          endArrow: true,
          lineWidth: 1.5,
        },
      },
      combo: {
        type: "rect",
        style: {
          labelText: (d) => String(d.data?.label ?? d.id),
          labelPlacement: "top",
          radius: 12,
          padding: 24,
          collapsedLineDash: 0,
          collapsedSize: [64, 40],
          collapsedMarker: true,
        },
      },
      layout: {
        type: "combo-combined",
        spacing: 60,
        comboPadding: 24,
        nodeSize: 60,
      },
      behaviors: [
        "drag-canvas",
        "zoom-canvas",
        "drag-element",
        "click-select",
        "hover-activate",
        {
          type: "collapse-expand",
          onCollapse: (id: ID) => setNote(`Collapsed "${id}" — crossing edges now land on the group.`),
          onExpand: (id: ID) => setNote(`Expanded "${id}" — edges return to their original nodes.`),
        },
      ],
    });

    // Under React StrictMode, dev double-invokes this effect; the first
    // graph's render() can still be in flight when its cleanup destroys it.
    // That's a dev-only artifact (StrictMode never double-invokes in prod).
    graph.render().catch(() => {});
    graphRef.current = graph;

    return () => {
      graph.destroy();
      graphRef.current = null;
    };
  }, []);

  const collapseAll = async () => {
    const graph = graphRef.current;
    if (!graph) return;
    for (const combo of graph.getComboData()) {
      await graph.collapseElement(combo.id, { animation: true });
    }
    setNote("Collapsed both groups.");
  };

  const expandAll = async () => {
    const graph = graphRef.current;
    if (!graph) return;
    for (const combo of graph.getComboData()) {
      await graph.expandElement(combo.id, { animation: true });
    }
    setNote("Expanded both groups.");
  };

  return (
    <div className="g6-combo-lab">
      <header className="g6-combo-lab__chrome">
        <p className="g6-combo-lab__eyebrow">Design lab</p>
        <h1 className="g6-combo-lab__title">G6 combos</h1>
        <p className="g6-combo-lab__lede">
          Native AntV G6, no attempt to match our visual language yet.
          "Session" and "Logging" are real combos (containment as a first-class
          graph primitive, not a drawn parenthesis). Nodes/edges look however
          G6 draws them by default. Try: drag nodes, drag a whole combo,
          double-click a combo to collapse it, and watch what happens to the
          edge that crosses from <code>token</code> to <code>audit</code> —
          it re-targets onto the collapsed group instead of disappearing.
        </p>
        <div className="g6-combo-lab__actions">
          <button type="button" onClick={collapseAll}>
            Collapse all
          </button>
          <button type="button" onClick={expandAll}>
            Expand all
          </button>
        </div>
        <p className="g6-combo-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/">Field</a>
        </p>
      </header>

      <p className="g6-combo-lab__note">{note}</p>
      <div className="g6-combo-lab__stage" ref={containerRef} />
    </div>
  );
}
