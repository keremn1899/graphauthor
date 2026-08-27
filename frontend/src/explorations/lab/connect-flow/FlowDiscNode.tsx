import {
  Handle,
  Position,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import type { CSSProperties } from "react";
import "./FlowDiscNode.css";

export const FLOW_DISC_SIZE = 104;

export type FlowDiscData = {
  label: string;
  role?: "idle" | "source" | "target";
};

export type FlowDiscNode = Node<FlowDiscData, "disc">;

export function FlowDiscNode({ id, data }: NodeProps<FlowDiscNode>) {
  const role = data.role ?? "idle";
  return (
    <div
      className={`flow-disc flow-disc--${role}`}
      data-node-id={id}
      style={{ width: FLOW_DISC_SIZE, height: FLOW_DISC_SIZE }}
    >
      <Handle
        type="target"
        position={Position.Left}
        id={`central-target-${id}`}
        className="flow-disc__handle"
        style={centerHandle}
      />
      <div className="flow-disc__face">
        <span>{data.label}</span>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        id={`central-source-${id}`}
        className="flow-disc__handle"
        style={centerHandle}
      />
    </div>
  );
}

const centerHandle: CSSProperties = {
  position: "absolute",
  top: "50%",
  left: "50%",
  transform: "translate(-50%, -50%)",
  width: 1,
  height: 1,
  opacity: 0,
  pointerEvents: "none",
  border: "none",
  minWidth: 0,
  minHeight: 0,
};
