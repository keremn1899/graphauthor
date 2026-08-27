import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from "react";
import { MotionConfig } from "motion/react";
import { useReducedMotion } from "../trial-legacy/hooks/useReducedMotion";
import { MASS_NODE_SIZE, ORBIT_TRACKS } from "../trial-legacy/data/trialGraph";
import { OrbiterBody } from "./orbiter/OrbiterBody";
import {
  MEMBRANE_DEFAULTS,
  type MembraneStatus,
} from "./membrane/membraneDefaults";
import {
  noiseMembranePath,
  type MembraneNoiseParams,
} from "./membrane/noiseMembrane";
import "./MembraneLabPage.css";

type Treatment = "restrained" | "tense" | "permeable";

type TreatmentConfig = {
  label: string;
  /** Provisional: alive but calm */
  provisional: Omit<MembraneNoiseParams, "seed">;
  /** Unresolved: frayed / permeable */
  unresolved: Omit<MembraneNoiseParams, "seed">;
};

const TREATMENTS: Record<Treatment, TreatmentConfig> = {
  restrained: {
    label: "A · Restrained",
    provisional: { ...MEMBRANE_DEFAULTS.provisional },
    unresolved: { ...MEMBRANE_DEFAULTS.unresolved },
  },
  tense: {
    label: "B · Tense",
    provisional: { amp: 2.4, spatial: 3.2, step: 0.95, detail: 0.88 },
    unresolved: { amp: 4.5, spatial: 2.4, step: 0.95, detail: 0.65 },
  },
  permeable: {
    label: "C · Permeable",
    provisional: { amp: 3.0, spatial: 3.6, step: 1.1, detail: 0.92 },
    unresolved: { amp: 5.5, spatial: 2.8, step: 1.1, detail: 0.75 },
  },
};

const MASS = 168;
const R = MASS / 2;
const PAD = 22;
const VIEW = MASS + PAD * 2;

/** TEMP: show only restrained in the UI — set true to restore A/B/C batch. */
const SHOW_TREATMENT_BATCH = false;

const SLIDER_META: {
  key: keyof Omit<MembraneNoiseParams, "seed">;
  label: string;
  min: number;
  max: number;
  step: number;
}[] = [
  { key: "amp", label: "Amp", min: 0, max: 14, step: 0.1 },
  { key: "spatial", label: "Spatial", min: 0.4, max: 6, step: 0.05 },
  { key: "step", label: "Step", min: 0.05, max: 1.5, step: 0.01 },
  { key: "detail", label: "Detail", min: 0, max: 1, step: 0.01 },
];

function statusFor(certainty: number): MembraneStatus {
  if (certainty >= 72) return "settled";
  if (certainty >= 38) return "provisional";
  return "unresolved";
}

function formatParam(n: number) {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, "");
}

export function MembraneLabPage() {
  const [certainty, setCertainty] = useState(52);
  const [treatment, setTreatment] = useState<Treatment>("restrained");
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion(motionOverride);
  const membraneRef = useRef<SVGPathElement | null>(null);
  /** Stable seed for this specimen — many nodes would each get their own */
  const seedRef = useRef(0.37);
  const timeRef = useRef(0);
  const uid = useId().replace(/:/g, "");

  // TEMP live tuners — defaults = locked restrained values
  const [amp, setAmp] = useState(MEMBRANE_DEFAULTS.provisional.amp);
  const [spatial, setSpatial] = useState(MEMBRANE_DEFAULTS.provisional.spatial);
  const [step, setStep] = useState(MEMBRANE_DEFAULTS.provisional.step);
  const [detail, setDetail] = useState(MEMBRANE_DEFAULTS.provisional.detail);

  // Orbiter wobble preview (trial-scale mass + orbiter)
  const [orbiterSize, setOrbiterSize] = useState(20);
  const orbitAngleRef = useRef(40);
  const orbitSlotRef = useRef<HTMLDivElement | null>(null);
  const orbitRadius = ORBIT_TRACKS[0];

  const status = statusFor(certainty);
  const live = { amp, spatial, step, detail };

  const noiseParams: MembraneNoiseParams | null = useMemo(() => {
    if (status === "settled") return null;
    return { ...live, seed: seedRef.current };
  }, [status, amp, spatial, step, detail]);

  const statusCopy = useMemo(() => {
    if (status === "settled") return "Firm boundary · decided · still";
    if (status === "provisional")
      return "Noise-living edge · in question · one body, no ring";
    return "Frayed noise edge · unresolved · permeable";
  }, [status]);

  const loadRestrainedDefaults = (forStatus: "provisional" | "unresolved") => {
    const base = TREATMENTS.restrained[forStatus];
    setAmp(base.amp);
    setSpatial(base.spatial);
    setStep(base.step);
    setDetail(base.detail);
  };

  // Drive membrane path via DOM — fill + label never re-render for the life
  useEffect(() => {
    if (!noiseParams) return;
    const path = membraneRef.current;
    if (!path) return;

    const paint = (time: number) => {
      path.setAttribute(
        "d",
        noiseMembranePath(R, R, R, time, noiseParams),
      );
    };

    if (reducedMotion) {
      paint(seedRef.current * 12.7);
      return;
    }

    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      timeRef.current += noiseParams.step * dt;
      paint(timeRef.current);
      raf = requestAnimationFrame(tick);
    };
    paint(timeRef.current);
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [noiseParams, reducedMotion]);

  // Slow orbit for the wobbly orbiter preview (trial radius)
  useEffect(() => {
    const el = orbitSlotRef.current;
    if (!el) return;

    const place = (deg: number) => {
      const a = (deg * Math.PI) / 180;
      const x = Math.cos(a) * orbitRadius;
      const y = Math.sin(a) * orbitRadius;
      el.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    };

    if (reducedMotion) {
      place(orbitAngleRef.current);
      return;
    }

    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      orbitAngleRef.current = (orbitAngleRef.current + 14 * dt) % 360;
      place(orbitAngleRef.current);
      raf = requestAnimationFrame(tick);
    };
    place(orbitAngleRef.current);
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reducedMotion, orbitRadius]);

  const uncertain = status === "provisional" || status === "unresolved";

  const setters: Record<
    keyof Omit<MembraneNoiseParams, "seed">,
    (n: number) => void
  > = {
    amp: setAmp,
    spatial: setSpatial,
    step: setStep,
    detail: setDetail,
  };

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <main className={`membrane-lab membrane-lab--${status}`}>
        <header className="membrane-lab__chrome">
          <p className="membrane-lab__eyebrow">Design lab</p>
          <h1 className="membrane-lab__title">Membrane boundary</h1>
          <p className="membrane-lab__lede">
            Boundary definiteness carries certainty: unresolved frays,
            provisional lives with slow noise, settled holds still. One body —
            the edge is the membrane; the label stays still.
          </p>
          <nav className="membrane-lab__nav" aria-label="Labs">
            <a href="#/explorations/trial">Trial</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/tether">Tether</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/orbiters">Orbiters</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/connect">Connect</a>
          </nav>

          <div className="membrane-lab__controls">
            {SHOW_TREATMENT_BATCH ? (
              <fieldset className="membrane-lab__group">
                <legend>Treatment batch</legend>
                <div className="membrane-lab__choices">
                  {(Object.keys(TREATMENTS) as Treatment[]).map((key) => (
                    <button
                      key={key}
                      type="button"
                      className={treatment === key ? "is-active" : ""}
                      onClick={() => setTreatment(key)}
                    >
                      {TREATMENTS[key].label}
                    </button>
                  ))}
                </div>
              </fieldset>
            ) : (
              <p className="membrane-lab__temp-note">
                Tuning · restrained defaults (B/C hidden)
              </p>
            )}

            <label className="membrane-lab__range">
              <span>Certainty</span>
              <input
                type="range"
                min="0"
                max="100"
                value={certainty}
                onChange={(event) => setCertainty(Number(event.target.value))}
              />
              <output>{certainty}</output>
            </label>

            <div className="membrane-lab__choices" aria-label="Certainty states">
              <button
                type="button"
                onClick={() => {
                  setCertainty(12);
                  loadRestrainedDefaults("unresolved");
                }}
              >
                Unresolved
              </button>
              <button
                type="button"
                onClick={() => {
                  setCertainty(52);
                  loadRestrainedDefaults("provisional");
                }}
              >
                Provisional
              </button>
              <button type="button" onClick={() => setCertainty(100)}>
                Resolve
              </button>
            </div>

            <label className="membrane-lab__toggle">
              <input
                type="checkbox"
                checked={reducedMotion}
                onChange={(event) => setMotionOverride(event.target.checked)}
              />
              Reduced motion
            </label>
          </div>

          {uncertain && (
            <div className="membrane-lab__tuners" aria-label="Noise parameters">
              {SLIDER_META.map((meta) => (
                <label key={meta.key} className="membrane-lab__range">
                  <span>{meta.label}</span>
                  <input
                    type="range"
                    min={meta.min}
                    max={meta.max}
                    step={meta.step}
                    value={live[meta.key]}
                    onChange={(e) =>
                      setters[meta.key](Number(e.target.value))
                    }
                  />
                  <output>{formatParam(live[meta.key])}</output>
                </label>
              ))}
              <button
                type="button"
                className="membrane-lab__reset"
                onClick={() =>
                  loadRestrainedDefaults(
                    status === "unresolved" ? "unresolved" : "provisional",
                  )
                }
              >
                Reset to restrained
              </button>
            </div>
          )}
        </header>

        <section className="membrane-lab__stage" aria-label="Membrane test">
          <div className="membrane-lab__specimen">
            {uncertain ? (
              <svg
                className="membrane-lab__node-svg"
                width={VIEW}
                height={VIEW}
                viewBox={`${-PAD} ${-PAD} ${VIEW} ${VIEW}`}
                aria-hidden
              >
                <path
                  ref={membraneRef}
                  id={`${uid}-membrane`}
                  className={
                    status === "provisional"
                      ? "membrane-lab__noise membrane-lab__noise--provisional"
                      : "membrane-lab__noise membrane-lab__noise--unresolved"
                  }
                  fill="var(--node-fill)"
                  stroke="none"
                />
              </svg>
            ) : (
              <div
                className="membrane-lab__core membrane-lab__core--settled"
                style={{ width: MASS, height: MASS }}
              />
            )}

            <span className="membrane-lab__label">Policy mass</span>
          </div>

          <div className="membrane-lab__reading" aria-live="polite">
            <p className="membrane-lab__status">{status}</p>
            <p>{statusCopy}</p>
            {uncertain && (
              <pre className="membrane-lab__values">{`{ amp: ${formatParam(amp)}, spatial: ${formatParam(spatial)}, step: ${formatParam(step)}, detail: ${formatParam(detail)} }`}</pre>
            )}
            <p className="membrane-lab__instruction">
              Drag Amp / Spatial / Step / Detail to tune. Copy the values block
              when it looks right. Trial graph uses the locked restrained
              defaults (amp scaled to node size).
            </p>
          </div>
        </section>

        <section
          className="membrane-lab__orbiter-stage"
          aria-label="Orbiter wobble test"
        >
          <div className="membrane-lab__orbiter-copy">
            <p className="membrane-lab__status">Orbiter wobble</p>
            <p>
              Trial-scale settled mass ({MASS_NODE_SIZE}px) with a wobbly
              orbiter on track {orbitRadius}px — check relative size and motion.
            </p>
            <label className="membrane-lab__range">
              <span>Orbiter size</span>
              <input
                type="range"
                min={10}
                max={36}
                step={1}
                value={orbiterSize}
                onChange={(e) => setOrbiterSize(Number(e.target.value))}
              />
              <output>{orbiterSize}</output>
            </label>
          </div>

          <div
            className={
              reducedMotion
                ? "membrane-lab__orbit-demo reduced-motion"
                : "membrane-lab__orbit-demo"
            }
            style={
              {
                ["--orbiter-demo-size"]: `${orbiterSize}px`,
              } as CSSProperties
            }
          >
            <div
              className="membrane-lab__orbit-mass"
              style={{ width: MASS_NODE_SIZE, height: MASS_NODE_SIZE }}
            >
              <span>Settled</span>
            </div>
            <div
              ref={orbitSlotRef}
              className="membrane-lab__orbit-slot"
            >
              <OrbiterBody form="wobbly" reducedMotion={reducedMotion} />
            </div>
          </div>
        </section>
      </main>
    </MotionConfig>
  );
}
