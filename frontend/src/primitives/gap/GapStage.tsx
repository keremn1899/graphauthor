import { useMemo } from "react";
import { ReactFlow, type NodeTypes } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GapVariation, GapFlowNode } from "./types";
import "./GapStage.css";

type GapStageProps = {
  variation: GapVariation;
};

export function GapStage({ variation }: GapStageProps) {
  const nodeTypes = useMemo(
    () =>
      ({
        intended: variation.Intended,
        oversight: variation.Oversight,
      }) as NodeTypes,
    [variation.Intended, variation.Oversight],
  );

  const nodes: GapFlowNode[] = useMemo(
    () => [
      {
        id: `${variation.id}-intended`,
        type: "intended",
        position: { x: 40, y: 70 },
        data: { kind: "intended" },
        draggable: false,
        selectable: false,
      },
      {
        id: `${variation.id}-oversight`,
        type: "oversight",
        position: { x: 220, y: 70 },
        data: { kind: "oversight" },
        draggable: false,
        selectable: false,
      },
    ],
    [variation.id],
  );

  return (
    <div className="gap-stage">
      <ReactFlow
        nodes={nodes}
        edges={[]}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.35 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      />
    </div>
  );
}
