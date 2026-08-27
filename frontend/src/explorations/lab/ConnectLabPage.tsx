import { useState } from "react";
import { MotionConfig } from "motion/react";
import { ConnectStage } from "./connect/ConnectStage";
import type { InitMode, TypeTiming } from "./connect/types";
import { useReducedMotion } from "../trial-legacy/hooks/useReducedMotion";
import "./ConnectLabPage.css";

export function ConnectLabPage() {
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion(motionOverride);
  const [initMode, setInitMode] = useState<InitMode>("near-node");
  const [typeTiming, setTypeTiming] = useState<TypeTiming>("after-land");
  const [log, setLog] = useState(
    "Long-press (touch) or right-click (mouse) the source to extend a reach.",
  );

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <div className="connect-lab">
        <header className="connect-lab__chrome">
          <p className="connect-lab__eyebrow">Design lab</p>
          <h1 className="connect-lab__title">Connection gesture</h1>
          <p className="connect-lab__lede">
            Pull a bridge out of a mass&apos;s field. While unformed it is
            wobbly (uncertain); on land it firms taut (certain). A{" "}
            <em>reach</em>, not an orbit.
          </p>
          <p className="connect-lab__nav">
            <a href="#/explorations/trial">Trial</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/edges">Edges</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/membrane">Membrane</a>
          </p>

          <div className="connect-lab__controls">
            <div className="connect-lab__group">
              <span className="connect-lab__label">Initiate</span>
              <div className="connect-lab__chips">
                <button
                  type="button"
                  className={
                    initMode === "on-node"
                      ? "connect-lab__chip connect-lab__chip--on"
                      : "connect-lab__chip"
                  }
                  onClick={() => setInitMode("on-node")}
                >
                  On-node
                </button>
                <button
                  type="button"
                  className={
                    initMode === "near-node"
                      ? "connect-lab__chip connect-lab__chip--on"
                      : "connect-lab__chip"
                  }
                  onClick={() => setInitMode("near-node")}
                >
                  Field reach
                </button>
              </div>
            </div>

            <div className="connect-lab__group">
              <span className="connect-lab__label">Type timing</span>
              <div className="connect-lab__chips">
                <button
                  type="button"
                  className={
                    typeTiming === "after-land"
                      ? "connect-lab__chip connect-lab__chip--on"
                      : "connect-lab__chip"
                  }
                  onClick={() => setTypeTiming("after-land")}
                >
                  After landing
                </button>
                <button
                  type="button"
                  className={
                    typeTiming === "before-drag"
                      ? "connect-lab__chip connect-lab__chip--on"
                      : "connect-lab__chip"
                  }
                  onClick={() => setTypeTiming("before-drag")}
                >
                  Before dragging
                </button>
              </div>
            </div>

            <label className="connect-lab__toggle">
              <input
                type="checkbox"
                checked={reducedMotion}
                onChange={(e) => setMotionOverride(e.target.checked)}
              />
              Reduced motion
            </label>
          </div>
        </header>

        <div className="connect-lab__stage-wrap">
          <ConnectStage
            key={`${initMode}-${typeTiming}`}
            initMode={initMode}
            typeTiming={typeTiming}
            reducedMotion={reducedMotion}
            onLog={setLog}
          />
          <p className="connect-lab__log" role="status">
            {log}
          </p>
        </div>
      </div>
    </MotionConfig>
  );
}
