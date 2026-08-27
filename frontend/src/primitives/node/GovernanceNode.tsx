import { Handle, Position } from "@xyflow/react";
import type { CSSProperties } from "react";
import type { GovernanceNodeProps } from "./types";
import { NODE_SIZE } from "./nodeDimensions";
import "./GovernanceNode.css";

/**
 * Circular governance node — firm boundary, filled (heavy / substance).
 *
 * React Flow still measures a square box. Circle is visual + edge math
 * (circumference intersection). Pattern from Note Prototype:
 * equal width/height + border-radius 50% + center-pinned invisible handles.
 */
export function GovernanceNode({ id, data }: GovernanceNodeProps) {
  return (
    <div
      className="governance-node"
      data-node-id={id}
      style={{ width: NODE_SIZE, height: NODE_SIZE }}
    >
      <Handle
        type="target"
        position={Position.Left}
        id={`central-target-${id}`}
        className="governance-node__handle"
        style={centerHandleStyle}
      />

      <div className="governance-node__face">
        <p className="governance-node__label">{data.label}</p>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        id={`central-source-${id}`}
        className="governance-node__handle"
        style={centerHandleStyle}
      />
    </div>
  );
}

const centerHandleStyle: CSSProperties = {
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
