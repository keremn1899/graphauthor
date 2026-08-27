import { useCallback, useState } from "react";
import { MotionConfig } from "motion/react";
import { OrbiterSystem } from "./orbiter/OrbiterSystem";
import {
  ORBITER_FORM_COPY,
  type ClutterMode,
  type OrbiterForm,
} from "./orbiter/types";
import { useReducedMotion } from "../trial-legacy/hooks/useReducedMotion";
import "./OrbiterLabPage.css";

export function OrbiterLabPage() {
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion(motionOverride);
  const [mode, setMode] = useState<ClutterMode>("distributed");
  const [nodeSettled, setNodeSettled] = useState(true);
  const [log, setLog] = useState("Tap an orbiter to attend.");
  const [accreteForm, setAccreteForm] = useState<OrbiterForm | null>(null);

  const onAttend = useCallback((form: OrbiterForm, id: string) => {
    setLog(`Attending: ${ORBITER_FORM_COPY[form].title} (${id})`);
  }, []);

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <div
        className={
          reducedMotion ? "orbiter-lab reduced-motion" : "orbiter-lab"
        }
      >
        <header className="orbiter-lab__chrome">
          <p className="orbiter-lab__eyebrow">Design lab</p>
          <h1 className="orbiter-lab__title">Orbiters (refined)</h1>
          <p className="orbiter-lab__lede">
            Small physical forms held in a settled mass&apos;s gravity — no
            drawn rings. Belonging by proximity. Wobbly nodes hold none.
          </p>
          <p className="orbiter-lab__nav">
            <a href="#/explorations/trial">Trial</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/tether">Tether</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/membrane">Membrane</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/connect">Connect</a>
          </p>

          <div className="orbiter-lab__controls">
            <div className="orbiter-lab__group">
              <span className="orbiter-lab__label">Node state</span>
              <div className="orbiter-lab__chips">
                <button
                  type="button"
                  className={
                    nodeSettled
                      ? "orbiter-lab__chip orbiter-lab__chip--on"
                      : "orbiter-lab__chip"
                  }
                  onClick={() => {
                    setNodeSettled(true);
                    setLog("Tap an orbiter to attend.");
                  }}
                >
                  Settled
                </button>
                <button
                  type="button"
                  className={
                    !nodeSettled
                      ? "orbiter-lab__chip orbiter-lab__chip--on"
                      : "orbiter-lab__chip"
                  }
                  onClick={() => {
                    setNodeSettled(false);
                    setLog("Provisional — orbiters withheld until the mass settles.");
                  }}
                >
                  Provisional
                </button>
              </div>
            </div>

            <div className="orbiter-lab__group">
              <span className="orbiter-lab__label">Clutter mode</span>
              <div className="orbiter-lab__chips">
                <button
                  type="button"
                  className={
                    mode === "aggregate"
                      ? "orbiter-lab__chip orbiter-lab__chip--on"
                      : "orbiter-lab__chip"
                  }
                  onClick={() => setMode("aggregate")}
                >
                  Aggregate → expand
                </button>
                <button
                  type="button"
                  className={
                    mode === "distributed"
                      ? "orbiter-lab__chip orbiter-lab__chip--on"
                      : "orbiter-lab__chip"
                  }
                  onClick={() => setMode("distributed")}
                >
                  Distributed
                </button>
              </div>
            </div>

            <div className="orbiter-lab__group">
              <span className="orbiter-lab__label">Accrete</span>
              <div className="orbiter-lab__chips">
                {(["wobbly", "crisp", "triangle"] as OrbiterForm[]).map(
                  (form) => (
                    <button
                      key={form}
                      type="button"
                      className="orbiter-lab__chip"
                      disabled={!nodeSettled}
                      onClick={() => setAccreteForm(form)}
                    >
                      {ORBITER_FORM_COPY[form].title}
                    </button>
                  ),
                )}
              </div>
            </div>

            <label className="orbiter-lab__toggle">
              <input
                type="checkbox"
                checked={reducedMotion}
                onChange={(e) => setMotionOverride(e.target.checked)}
              />
              Reduced motion
            </label>
          </div>
        </header>

        <div className="orbiter-lab__stage">
          <OrbiterSystem
            key={`${mode}-${nodeSettled}`}
            mode={mode}
            reducedMotion={reducedMotion}
            nodeSettled={nodeSettled}
            onAttend={onAttend}
            accreteForm={accreteForm}
            onAccreteDone={() => {
              setAccreteForm(null);
              setLog("Accreted — orbiter merged into the mass.");
            }}
          />
          <p className="orbiter-lab__log" role="status">
            {log}
          </p>
        </div>
      </div>
    </MotionConfig>
  );
}
