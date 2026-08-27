import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { TrialGapData } from "../data/trialGraph";
import "./ContextualGap.css";

export type GapFlowNode = Node<TrialGapData, "gap">;

const W = 110;
const H = 80;

/**
 * Contextual gap — shown inside a containment region, not scattered.
 * Intended: sealed membrane, calm. Oversight: sparse remains, restless.
 */
export function ContextualGap({ data }: NodeProps<GapFlowNode>) {
  const isIntended = data.kind === "intended";

  return (
    <div
      className={`contextual-gap contextual-gap--${data.kind}`}
      style={{ width: W, height: H }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="contextual-gap__handle"
      />
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden>
        {isIntended ? (
          <rect
            x="10"
            y="10"
            width="80"
            height="52"
            fill="none"
            stroke="var(--gap-stroke)"
            strokeWidth="2"
          />
        ) : (
          <g className="contextual-gap__oversight">
            <line
              x1="12"
              y1="14"
              x2="38"
              y2="14"
              stroke="var(--gap-stroke)"
              strokeWidth="1.75"
              strokeLinecap="square"
            />
            <line
              x1="58"
              y1="12"
              x2="72"
              y2="16"
              stroke="var(--gap-stroke)"
              strokeWidth="1.5"
              strokeLinecap="square"
            />
            <line
              x1="86"
              y1="26"
              x2="86"
              y2="42"
              stroke="var(--gap-stroke)"
              strokeWidth="1.75"
              strokeLinecap="square"
            />
            <line
              x1="64"
              y1="60"
              x2="36"
              y2="60"
              stroke="var(--gap-stroke)"
              strokeWidth="1.75"
              strokeLinecap="square"
            />
            <line
              x1="12"
              y1="50"
              x2="12"
              y2="30"
              stroke="var(--gap-stroke)"
              strokeWidth="1.5"
              strokeLinecap="square"
            />
          </g>
        )}
      </svg>
      <Handle
        type="source"
        position={Position.Right}
        className="contextual-gap__handle"
      />
    </div>
  );
}
