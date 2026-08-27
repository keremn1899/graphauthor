import { useState } from "react";
import { MotionConfig } from "motion/react";
import { useReducedMotion } from "../../shared/hooks/useReducedMotion";
import { DragStage } from "./connect-drag/DragStage";
import "./ConnectRingLabPage.css";

export function ConnectDragLabPage() {
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion(motionOverride);
  const [log, setLog] = useState(
    "Right-click a disc to start — then left-click a target, or empty to cancel.",
  );

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <div className="connect-ring-lab">
        <header className="connect-ring-lab__chrome">
          <p className="connect-ring-lab__eyebrow">Design lab</p>
          <h1 className="connect-ring-lab__title">Connect drag</h1>
          <p className="connect-ring-lab__lede">
            No proximity ring. Right-click a disc to initiate — the line
            follows the cursor. Left-click another disc to finalise; click
            empty space to disengage. Target hover uses an inset selection
            wash.
          </p>
          <p className="connect-ring-lab__nav">
            <a href="#/explorations">← Explorations</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/connect-ring">Connect ring</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/connect-flow">Connect flow</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/tether">Tether</a>
            <span aria-hidden> · </span>
            <a href="#/">Field</a>
          </p>

          <label className="connect-ring-lab__toggle">
            <input
              type="checkbox"
              checked={reducedMotion}
              onChange={(e) => setMotionOverride(e.target.checked)}
            />
            Reduced motion
          </label>

          <p className="connect-ring-lab__log" role="status">
            {log}
          </p>
        </header>

        <DragStage reducedMotion={reducedMotion} onLog={setLog} />
      </div>
    </MotionConfig>
  );
}
