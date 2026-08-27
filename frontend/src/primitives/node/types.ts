import type { Node, NodeProps } from "@xyflow/react";

export type GovernanceNodeData = {
  label: string;
};

export type GovernanceNodeType = Node<GovernanceNodeData, "governance">;

export type GovernanceNodeProps = NodeProps<GovernanceNodeType>;
