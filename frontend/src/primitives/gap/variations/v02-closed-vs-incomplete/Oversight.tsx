import type { NodeProps } from "@xyflow/react";
import type { GapFlowNode } from "../../types";
import { GapShell } from "../../shared/GapShell";
import "./v02.css";

/**
 * Three walls present; the left wall never written.
 * Large missing side — not a chamfer, dog-ear, or stylized cut.
 */
export function Oversight(_props: NodeProps<GapFlowNode>) {
  return (
    <GapShell>
      {/* top */}
      <line x1="16" y1="18" x2="96" y2="18" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      {/* right */}
      <line x1="96" y1="18" x2="96" y2="70" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      {/* bottom */}
      <line x1="96" y1="70" x2="16" y2="70" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      {/* left wall absent — only short failed stubs at the joints */}
      <line
        className="v02-stub-top"
        x1="16"
        y1="18"
        x2="16"
        y2="26"
        stroke="var(--gap-stroke)"
        strokeWidth="1.5"
        strokeLinecap="square"
      />
      <line
        className="v02-stub-bottom"
        x1="16"
        y1="70"
        x2="16"
        y2="60"
        stroke="var(--gap-stroke)"
        strokeWidth="1.5"
        strokeLinecap="square"
      />
    </GapShell>
  );
}
