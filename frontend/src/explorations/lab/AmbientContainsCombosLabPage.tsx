import { useEffect, useMemo, useRef, useState } from "react";
import {
  Graph,
  type EdgeData,
  type IElementEvent,
  type NodeData,
} from "@antv/g6";
import { FONT_MONO_FAMILY, FONT_SANS_FAMILY } from "../../styles/typography";
import { mauveDark } from "@radix-ui/colors";
import {
  arrowSizeForKind,
  ensureLinkageEdgeRegistered,
  isDirectedKind,
  LINKAGE_EDGE,
  linkageEdgeKind,
} from "../g6/linkageEdge";
import { labelOf } from "./ambientLodData";
import { createAmbientContainsComboGraph } from "./ambientContainsComboGraph";
import "./AmbientContainsCombosLabPage.css";

/**
 * Experiment: CONTAINS as G6 combos/hulls on the ambient fixture.
 * Collapse a region to fold its children; crossing LEADSTO edges retarget
 * onto the combo. Not product chrome — separate from ambient-canvas.
 */

const INK = mauveDark.mauve10;
const PAPER = mauveDark.mauve1;
const CHIP = mauveDark.mauve3;
const RULE = mauveDark.mauve5;
const NODE_SIZE = 52;

function edgeKindLabel(datum: EdgeData) {
  const kind = linkageEdgeKind(datum);
  if (kind === "leadsto") return "LEADSTO";
  if (kind === "contains") return "CONTAINS";
  if (kind === "expresses") return "EXPRESSES";
  if (kind === "nearto") return "NEARTO";
  return String(datum.data?.label ?? "").toUpperCase() || "EDGE";
}

export function AmbientContainsCombosLabPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const [ready, setReady] = useState(false);
  const [note, setNote] = useState("Building CONTAINS combos…");
  const [counts, setCounts] = useState({ nodes: 0, edges: 0, combos: 0 });

  const data = useMemo(() => createAmbientContainsComboGraph(), []);

  useEffect(() => {
    if (!containerRef.current) return;
    ensureLinkageEdgeRegistered();
    let cancelled = false;

    const graph = new Graph({
      container: containerRef.current,
      data,
      animation: false,
      padding: [40, 36, 40, 36],
      zoomRange: [0.05, 8],
      devicePixelRatio: 2,
      node: {
        type: "circle",
        style: {
          size: NODE_SIZE,
          fill: INK,
          stroke: INK,
          lineWidth: 1,
          labelText: (d: NodeData) => labelOf(d),
          labelPlacement: "center",
          labelFill: PAPER,
          labelFontSize: 8,
          labelFontWeight: 600,
          labelFontFamily: FONT_SANS_FAMILY,
          labelWordWrap: true,
          labelMaxWidth: NODE_SIZE * 0.78,
          labelMaxLines: 2,
          labelTextOverflow: "ellipsis",
          cursor: "grab",
        },
      },
      edge: {
        type: LINKAGE_EDGE,
        style: {
          edgeKind: (d: EdgeData) => linkageEdgeKind(d),
          stroke: INK,
          lineWidth: 1.1,
          lineCap: "round",
          opacity: 0.55,
          endArrow: (d: EdgeData) => isDirectedKind(linkageEdgeKind(d)),
          endArrowSize: (d: EdgeData) => arrowSizeForKind(linkageEdgeKind(d)),
          endArrowFill: INK,
          labelText: (d: EdgeData) => edgeKindLabel(d),
          labelFontFamily: FONT_MONO_FAMILY,
          labelFontSize: 7,
          labelFill: mauveDark.mauve9,
          labelBackground: true,
          labelBackgroundFill: CHIP,
          labelBackgroundOpacity: 0,
          labelOpacity: 0,
          labelAutoRotate: false,
          labelPadding: [2, 3],
          increasedLineWidthForHitTesting: 16,
        },
        state: {
          active: {
            opacity: 1,
            lineWidth: 1.6,
            labelOpacity: 1,
            labelBackgroundOpacity: 1,
            labelFill: mauveDark.mauve11,
          },
        },
        animation: false,
      },
      combo: {
        type: "circle",
        style: {
          fill: RULE,
          fillOpacity: 0.35,
          stroke: INK,
          lineWidth: 1.25,
          padding: 28,
          labelText: (d) => String(d.data?.label ?? d.id),
          labelPlacement: "top",
          labelFill: mauveDark.mauve11,
          labelFontSize: 11,
          labelFontWeight: 600,
          labelFontFamily: FONT_SANS_FAMILY,
          collapsedSize: 72,
          collapsedMarker: true,
          collapsedLineDash: 0,
          cursor: "pointer",
        },
      },
      layout: {
        type: "combo-combined",
        spacing: 48,
        comboPadding: 28,
        nodeSize: NODE_SIZE + 12,
      },
      behaviors: [
        "drag-canvas",
        "zoom-canvas",
        "drag-element",
        "click-select",
      ],
    });

    const onComboContextMenu = (event: IElementEvent) => {
      event.preventDefault?.();
      const native = (event as { originalEvent?: Event; nativeEvent?: Event })
        .originalEvent ?? (event as { nativeEvent?: Event }).nativeEvent;
      native?.preventDefault?.();
      const id = String(event.target?.id ?? "");
      if (!id || graph.destroyed) return;
      const datum = graph.getComboData(id);
      if (!datum) return;
      const closed = Boolean(datum.style?.collapsed);
      void (async () => {
        if (closed) {
          await graph.expandElement(id, { animation: true }).catch(() => {});
          setNote(`Expanded “${id}” — members and edges restored.`);
        } else {
          await graph.collapseElement(id, { animation: true }).catch(() => {});
          setNote(`Collapsed “${id}” — crossing edges retarget onto the hull.`);
        }
      })();
    };
    graph.on("combo:contextmenu", onComboContextMenu);

    graphRef.current = graph;
    setCounts({
      nodes: data.nodes?.length ?? 0,
      edges: data.edges?.length ?? 0,
      combos: data.combos?.length ?? 0,
    });

    graph
      .render()
      .then(async () => {
        if (cancelled || graph.destroyed) return;
        await graph.fitView().catch(() => {});
        if (cancelled || graph.destroyed) return;
        setNote(
          "Right-click a region hull to collapse/expand. CONTAINS is membership, not an edge.",
        );
        setReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("[ambient-combos] init failed", err);
        setNote("Init failed — see console");
      });

    return () => {
      cancelled = true;
      graph.off("combo:contextmenu", onComboContextMenu);
      graphRef.current = null;
      graph.destroy();
    };
  }, [data]);

  const collapseAll = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    for (const combo of graph.getComboData()) {
      await graph.collapseElement(combo.id, { animation: true }).catch(() => {});
    }
    setNote("All region hulls collapsed.");
  };

  const expandAll = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    for (const combo of graph.getComboData()) {
      await graph.expandElement(combo.id, { animation: true }).catch(() => {});
    }
    setNote("All region hulls expanded.");
  };

  const refit = async () => {
    const graph = graphRef.current;
    if (!graph || graph.destroyed) return;
    await graph.fitView().catch(() => {});
  };

  return (
    <main className="ambient-combos">
      <header className="ambient-combos__header">
        <div>
          <p className="ambient-combos__eyebrow">
            Experiment · CONTAINS as combos
          </p>
          <h1>Ambient contains hulls</h1>
          <p className="ambient-combos__lede">
            Same ambient fixture, but leaf-region CONTAINS becomes G6 combos instead
            of filaments. Collapse a hull to fold a region; LEADSTO / NEARTO /
            EXPRESSES stay drawn and retarget onto collapsed groups.
          </p>
          <p className="ambient-combos__nav">
            <a href="#/explorations">Explorations</a>
            {" · "}
            <a href="#/explorations/ambient-canvas">Ambient canvas</a>
            {" · "}
            <a href="#/explorations/g6-combo">G6 combos</a>
          </p>
        </div>
        <aside className="ambient-combos__note">
          <span>Structure</span>
          <strong>
            {counts.nodes} nodes · {counts.combos} combos · {counts.edges} edges
          </strong>
          <p>{note}</p>
        </aside>
      </header>

      <div className="ambient-combos__toolbar">
        <button type="button" disabled={!ready} onClick={() => void collapseAll()}>
          Collapse all
        </button>
        <button type="button" disabled={!ready} onClick={() => void expandAll()}>
          Expand all
        </button>
        <button type="button" disabled={!ready} onClick={() => void refit()}>
          Fit view
        </button>
        <p className="ambient-combos__status" role="status">
          {ready ? "combo-combined · freeze after layout" : "Loading…"}
        </p>
      </div>

      <div className="ambient-combos__stage-shell">
        <div
          className="ambient-combos__stage"
          ref={containerRef}
          onContextMenu={(e) => e.preventDefault()}
        />
      </div>
    </main>
  );
}
