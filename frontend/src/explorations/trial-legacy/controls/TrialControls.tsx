import type { EdgeKind } from "../../../primitives/edge/types";
import "./TrialControls.css";

export type TrialControlsProps = {
  lens: EdgeKind;
  onLensChange: (lens: EdgeKind) => void;
  reducedMotion: boolean;
  onReducedMotionChange: (value: boolean) => void;
  onBirth: () => void;
  onDeath: () => void;
  onConnect: () => void;
  onAccrete: () => void;
  onReheat: () => void;
  canAccrete: boolean;
};

const LENSES: EdgeKind[] = ["CONTAINS", "LEADSTO", "EXPRESSES", "NEARTO"];

export function TrialControls({
  lens,
  onLensChange,
  reducedMotion,
  onReducedMotionChange,
  onBirth,
  onDeath,
  onConnect,
  onAccrete,
  onReheat,
  canAccrete,
}: TrialControlsProps) {
  return (
    <div className="trial-controls">
      <div className="trial-controls__group">
        <span className="trial-controls__label">
          Lens · CONTAINS first
        </span>
        <div className="trial-controls__lenses" role="group" aria-label="Edge lens">
          {LENSES.map((l) => (
            <button
              key={l}
              type="button"
              title={
                l === "CONTAINS"
                  ? "Default containment view"
                  : "Architecturally available — deferred until needed"
              }
              className={
                l === lens
                  ? "trial-controls__chip trial-controls__chip--active"
                  : l === "CONTAINS"
                    ? "trial-controls__chip"
                    : "trial-controls__chip trial-controls__chip--deferred"
              }
              onClick={() => onLensChange(l)}
            >
              {l}
            </button>
          ))}
        </div>
      </div>

      <div className="trial-controls__group">
        <span className="trial-controls__label">Events</span>
        <div className="trial-controls__actions">
          <button type="button" onClick={onBirth}>
            Birth
          </button>
          <button type="button" onClick={onDeath}>
            Death
          </button>
          <button type="button" onClick={onConnect}>
            Connect
          </button>
          <button type="button" onClick={onAccrete} disabled={!canAccrete}>
            Accrete
          </button>
          <button type="button" onClick={onReheat}>
            Re-settle
          </button>
        </div>
      </div>

      <label className="trial-controls__toggle">
        <input
          type="checkbox"
          checked={reducedMotion}
          onChange={(e) => onReducedMotionChange(e.target.checked)}
        />
        Reduced motion
      </label>
    </div>
  );
}
