import type { NodeProps } from "@xyflow/react";
import type { GapFlowNode } from "../../types";
import { GapShell } from "../../shared/GapShell";
import "./v01.css";

/**
 * Mostly absent perimeter — only sparse remains of a boundary.
 * Not sketchy-even dashes: large voids dominate; fragments are few.
 */
export function Oversight(_props: NodeProps<GapFlowNode>) {
  return (
    <GapShell>
      <line x1="18" y1="20" x2="40" y2="20" stroke="var(--gap-stroke)" strokeWidth="1.75" strokeLinecap="square" />
      <line x1="68" y1="19" x2="78" y2="22" stroke="var(--gap-stroke)" strokeWidth="1.5" strokeLinecap="square" />
      <line x1="94" y1="34" x2="94" y2="48" stroke="var(--gap-stroke)" strokeWidth="1.75" strokeLinecap="square" />
      <line x1="70" y1="70" x2="42" y2="70" stroke="var(--gap-stroke)" strokeWidth="1.75" strokeLinecap="square" />
      <line x1="18" y1="58" x2="18" y2="40" stroke="var(--gap-stroke)" strokeWidth="1.5" strokeLinecap="square" />
    </GapShell>
  );
}
