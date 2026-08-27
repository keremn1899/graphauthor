import type { NodeProps } from "@xyflow/react";
import type { GapFlowNode } from "../../types";
import { GapShell } from "../../shared/GapShell";
import "./v04.css";

/**
 * Blunt breach — bottom edge simply fails to continue.
 * No angled “entrance” lips (those read as a designed doorway).
 */
export function Oversight(_props: NodeProps<GapFlowNode>) {
  return (
    <GapShell>
      <line x1="16" y1="18" x2="96" y2="18" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      <line x1="96" y1="18" x2="96" y2="70" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      <line x1="16" y1="18" x2="16" y2="70" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />

      {/* bottom interrupted — blunt ends, slightly misaligned (not a motif) */}
      <line x1="16" y1="70" x2="46" y2="70" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      <line
        className="v04-far"
        x1="70"
        y1="71"
        x2="96"
        y2="70"
        stroke="var(--gap-stroke)"
        strokeWidth="2"
        strokeLinecap="square"
      />
    </GapShell>
  );
}
