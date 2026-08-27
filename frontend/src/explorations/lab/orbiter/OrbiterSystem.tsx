import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { AnimatePresence, motion } from "motion/react";
import { OrbiterBody } from "./OrbiterBody";
import {
  DEFAULT_ORBITERS,
  NODE_SIZE,
  ORBIT_RADIUS,
  ORBIT_SPEED_DEG,
  ORBITER_FORM_COPY,
  type ClutterMode,
  type OrbiterForm,
  type OrbiterSpec,
} from "./types";
import "./OrbiterSystem.css";

type OrbiterSystemProps = {
  mode: ClutterMode;
  reducedMotion: boolean;
  nodeSettled: boolean;
  onAttend: (form: OrbiterForm, id: string) => void;
  accreteForm: OrbiterForm | null;
  onAccreteDone: () => void;
};

function polar(angleDeg: number, radius: number) {
  const a = (angleDeg * Math.PI) / 180;
  return { x: Math.cos(a) * radius, y: Math.sin(a) * radius };
}

export function OrbiterSystem({
  mode,
  reducedMotion,
  nodeSettled,
  onAttend,
  accreteForm,
  onAccreteDone,
}: OrbiterSystemProps) {
  const [orbiters, setOrbiters] = useState<OrbiterSpec[]>(DEFAULT_ORBITERS);
  const [expanded, setExpanded] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [accretingId, setAccretingId] = useState<string | null>(null);

  const anglesRef = useRef<Record<string, number>>(
    Object.fromEntries(DEFAULT_ORBITERS.map((o) => [o.id, o.angle])),
  );
  const slotRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const accretingRef = useRef<string | null>(null);

  useEffect(() => {
    accretingRef.current = accretingId;
  }, [accretingId]);

  // Key rule: provisional/wobbly node cannot hold orbiters
  useEffect(() => {
    if (!nodeSettled) {
      setExpanded(false);
      setSelectedId(null);
      setAccretingId(null);
    }
  }, [nodeSettled]);

  useEffect(() => {
    if (!accreteForm || !nodeSettled) return;
    const target = orbiters.find((o) => o.form === accreteForm);
    if (!target) {
      onAccreteDone();
      return;
    }
    setAccretingId(target.id);
    setExpanded(true);
  }, [accreteForm, orbiters, onAccreteDone, nodeSettled]);

  const visible = useMemo(() => {
    if (!nodeSettled) return [];
    if (mode === "distributed") return orbiters;
    if (!expanded) return [];
    return orbiters;
  }, [mode, expanded, orbiters, nodeSettled]);

  // Slow shared orbit at equal radius — RAF on DOM, no React per-frame
  useEffect(() => {
    if (!nodeSettled || visible.length === 0) return;

    // Snap still positions when reduced motion
    if (reducedMotion) {
      for (const o of visible) {
        if (accretingRef.current === o.id) continue;
        const el = slotRefs.current.get(o.id);
        if (!el) continue;
        const angle = anglesRef.current[o.id] ?? o.angle;
        const pos = polar(angle, ORBIT_RADIUS);
        el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0)`;
        // Tip defaults up (−Y); +270° aims it at the mass center
        el.style.setProperty("--orbiter-face", `${angle + 270}deg`);
      }
      return;
    }

    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      for (const o of visible) {
        if (accretingRef.current === o.id) continue;
        const next =
          ((anglesRef.current[o.id] ?? o.angle) + ORBIT_SPEED_DEG * dt) % 360;
        anglesRef.current[o.id] = next;
        const el = slotRefs.current.get(o.id);
        if (!el) continue;
        const pos = polar(next, ORBIT_RADIUS);
        el.style.transform = `translate3d(${pos.x}px, ${pos.y}px, 0)`;
        el.style.setProperty("--orbiter-face", `${next + 270}deg`);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [nodeSettled, reducedMotion, visible]);

  const finishAccrete = (id: string) => {
    setOrbiters((list) => list.filter((o) => o.id !== id));
    setAccretingId(null);
    setSelectedId(null);
    onAccreteDone();
  };

  const aggregatePos = polar(40, ORBIT_RADIUS);

  return (
    <div className="orbiter-system">
      {/* No field rings — belonging is proximity/gravity only */}
      <div
        className={[
          "orbiter-system__mass",
          nodeSettled
            ? "orbiter-system__mass--settled"
            : "orbiter-system__mass--wobbly",
        ].join(" ")}
        style={{ width: NODE_SIZE, height: NODE_SIZE }}
      >
        <span className="orbiter-system__mass-label">
          {nodeSettled ? "Settled mass" : "Provisional"}
        </span>
      </div>

      <svg width="0" height="0" aria-hidden className="orbiter-system__defs">
        <defs>
          <filter id="orbiter-goo">
            <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur" />
            <feColorMatrix
              in="blur"
              mode="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -7"
              result="goo"
            />
            <feBlend in="SourceGraphic" in2="goo" />
          </filter>
        </defs>
      </svg>

      {mode === "aggregate" &&
        nodeSettled &&
        !expanded &&
        orbiters.length > 0 && (
          <button
            type="button"
            className="orbiter-system__aggregate"
            style={{
              transform: `translate(${aggregatePos.x}px, ${aggregatePos.y}px)`,
            }}
            onClick={() => setExpanded(true)}
            aria-label="Pending activity — expand"
          >
            <span className="orbiter-system__aggregate-mark" />
            <span className="orbiter-system__aggregate-count">
              {orbiters.length}
            </span>
          </button>
        )}

      {mode === "aggregate" && expanded && nodeSettled && (
        <button
          type="button"
          className="orbiter-system__collapse"
          onClick={() => setExpanded(false)}
        >
          Collapse
        </button>
      )}

      <div
        className="orbiter-system__orbiters"
        style={{ filter: accretingId ? "url(#orbiter-goo)" : undefined }}
      >
        <AnimatePresence>
          {visible.map((o) => {
            const angle = anglesRef.current[o.id] ?? o.angle;
            const pos = polar(angle, ORBIT_RADIUS);

            if (accretingId === o.id) {
              return (
                <motion.div
                  key={o.id}
                  className="orbiter-system__slot"
                  initial={{ x: pos.x, y: pos.y, scale: 1, opacity: 1 }}
                  animate={{ x: 0, y: 0, scale: 0.2, opacity: 0 }}
                  transition={
                    reducedMotion
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 90, damping: 14 }
                  }
                  style={
                    {
                      ["--orbiter-face"]: `${angle + 270}deg`,
                    } as CSSProperties
                  }
                  onAnimationComplete={() => finishAccrete(o.id)}
                >
                  <OrbiterBody form={o.form} reducedMotion={reducedMotion} />
                </motion.div>
              );
            }

            return (
              <div
                key={o.id}
                className="orbiter-system__slot"
                ref={(el) => {
                  if (el) slotRefs.current.set(o.id, el);
                  else slotRefs.current.delete(o.id);
                }}
                style={
                  {
                    transform: `translate3d(${pos.x}px, ${pos.y}px, 0)`,
                    ["--orbiter-face"]: `${angle + 270}deg`,
                  } as CSSProperties
                }
              >
                <OrbiterBody
                  form={o.form}
                  selected={selectedId === o.id}
                  reducedMotion={reducedMotion}
                  onPointerDown={() => {
                    setSelectedId(o.id);
                    onAttend(o.form, o.id);
                  }}
                />
              </div>
            );
          })}
        </AnimatePresence>
      </div>

      {nodeSettled && selectedId && (
        <p className="orbiter-system__caption">
          {(() => {
            const o = orbiters.find((x) => x.id === selectedId);
            if (!o) return null;
            const copy = ORBITER_FORM_COPY[o.form];
            return (
              <>
                <strong>{copy.title}</strong> — {copy.meaning}
              </>
            );
          })()}
        </p>
      )}
    </div>
  );
}
