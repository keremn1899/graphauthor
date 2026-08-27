import type { NodeProps } from "@xyflow/react";
import type { GapFlowNode } from "../../types";
import { GapShell } from "../../shared/GapShell";
import "./v02.css";

/** Fully sealed — decision closed. */
export function Intended(_props: NodeProps<GapFlowNode>) {
  return (
    <GapShell>
      <rect
        x="16"
        y="18"
        width="80"
        height="52"
        fill="none"
        stroke="var(--gap-stroke)"
        strokeWidth="2"
      />
    </GapShell>
  );
}
