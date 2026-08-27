import type { NodeProps } from "@xyflow/react";
import type { GapFlowNode } from "../../types";
import { GapShell } from "../../shared/GapShell";
import "./v03.css";

/**
 * Progressive loss of definiteness — not a dash pattern.
 * Few, uneven fragments with large irregular gaps.
 */
export function Oversight(_props: NodeProps<GapFlowNode>) {
  return (
    <GapShell>
      <line x1="16" y1="18" x2="96" y2="18" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      <line x1="16" y1="18" x2="16" y2="70" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />
      <line x1="16" y1="70" x2="96" y2="70" stroke="var(--gap-stroke)" strokeWidth="2" strokeLinecap="square" />

      <line className="v03-fray" x1="96" y1="18" x2="96" y2="34" stroke="var(--gap-stroke)" strokeWidth="1.75" strokeLinecap="square" />
      <line className="v03-fray v03-fray--2" x1="96" y1="48" x2="96" y2="54" stroke="var(--gap-stroke)" strokeWidth="1.35" strokeLinecap="square" />
      <line className="v03-fray v03-fray--3" x1="97" y1="64" x2="96" y2="66" stroke="var(--gap-stroke)" strokeWidth="1" strokeLinecap="square" />
    </GapShell>
  );
}
