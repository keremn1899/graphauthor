import type { NodeProps } from "@xyflow/react";
import type { GapNode } from "./types";
import { GapShell } from "./shared/GapShell";
import "./gap.css";

/**
 * v01 chosen — sparse remains of a boundary.
 * Large voids dominate; fragments are few. No marching-ants.
 */
export function GapOversight(_props: NodeProps<GapNode>) {
  return (
    <GapShell width={120} height={88}>
      <line x1="14" y1="16" x2="42" y2="16" stroke="var(--gap-stroke)" strokeWidth="1.75" strokeLinecap="square" />
      <line x1="72" y1="15" x2="84" y2="19" stroke="var(--gap-stroke)" strokeWidth="1.5" strokeLinecap="square" />
      <line x1="102" y1="30" x2="102" y2="48" stroke="var(--gap-stroke)" strokeWidth="1.75" strokeLinecap="square" />
      <line x1="76" y1="72" x2="44" y2="72" stroke="var(--gap-stroke)" strokeWidth="1.75" strokeLinecap="square" />
      <line x1="14" y1="60" x2="14" y2="38" stroke="var(--gap-stroke)" strokeWidth="1.5" strokeLinecap="square" />
    </GapShell>
  );
}
