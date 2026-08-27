import type { NodeProps } from "@xyflow/react";
import type { GapNode } from "./types";
import { GapShell } from "./shared/GapShell";
import "./gap.css";

/** v01 chosen — sealed membrane, decided void, at rest. */
export function GapIntended(_props: NodeProps<GapNode>) {
  return (
    <GapShell width={120} height={88}>
      <rect
        className="gap-intended"
        x="12"
        y="14"
        width="96"
        height="60"
        fill="none"
        stroke="var(--gap-stroke)"
        strokeWidth="2"
      />
    </GapShell>
  );
}
