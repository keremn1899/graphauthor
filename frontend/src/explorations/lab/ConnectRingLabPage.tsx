import { useState } from "react";
import { MotionConfig } from "motion/react";
import { useReducedMotion } from "../../shared/hooks/useReducedMotion";
import { RingStage } from "./connect-ring/RingStage";
import "./ConnectRingLabPage.css";

export function ConnectRingLabPage() {
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion(motionOverride);
  const [log, setLog] = useState(
    "Right-click near the outside of a disc to arm the grey ring.",
  );

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <div className="connect-ring-lab">
        <header className="connect-ring-lab__chrome">
          <p className="connect-ring-lab__eyebrow">Design lab</p>
          <h1 className="connect-ring-lab__title">Connect ring</h1>
          <p className="connect-ring-lab__lede">
            Annulus arm → drag → firm edge. No land / taut animation — release
            on a valid target locks a straight rim chord immediately.
          </p>
          <p className="connect-ring-lab__nav">
            <a href="#/explorations">← Explorations</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/edges">Edge forms</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/lifecycle">Lifecycle</a>
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

        <RingStage reducedMotion={reducedMotion} onLog={setLog} />
      </div>
    </MotionConfig>
  );
}
