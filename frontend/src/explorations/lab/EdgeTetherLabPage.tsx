import { useEffect, useState } from "react";
import { animated, to, useSpring } from "@react-spring/web";
import { MotionConfig } from "motion/react";
import type { EdgeKind } from "../../primitives/edge/types";
import { useReducedMotion } from "../trial-legacy/hooks/useReducedMotion";
import "./EdgeTetherLabPage.css";

type ExpressesStyle = "dot" | "thin";
type CertaintyMode = "slider" | "forming";

const NODE_R = 46;
const STAGE_W = 640;
const STAGE_H = 360;
const LEFT = { x: 120, y: 180 };
const RIGHT = { x: 520, y: 180 };
const GAP_A = { x: 255, y: 180 };
const GAP_B = { x: 385, y: 180 };

function unit(ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax;
  const dy = by - ay;
  const len = Math.hypot(dx, dy) || 1;
  return { ux: dx / len, uy: dy / len, px: -dy / len, py: dx / len, len };
}

function attach(from: { x: number; y: number }, to: { x: number; y: number }) {
  const { ux, uy } = unit(from.x, from.y, to.x, to.y);
  return {
    sx: from.x + ux * NODE_R,
    sy: from.y + uy * NODE_R,
    tx: to.x - ux * NODE_R,
    ty: to.y - uy * NODE_R,
  };
}

function mid(sx: number, sy: number, tx: number, ty: number) {
  return { x: (sx + tx) / 2, y: (sy + ty) / 2 };
}

/** Slack displaces the control point perpendicular to the chord. */
function slackControl(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
  slack: number,
  phase: number,
) {
  const m = mid(sx, sy, tx, ty);
  const { px, py } = unit(sx, sy, tx, ty);
  const bow = slack * 42;
  const wobble = slack > 0.05 && slack < 0.95 ? Math.sin(phase) * slack * 7 : 0;
  return {
    x: m.x + px * (bow + wobble),
    y: m.y + py * (bow + wobble),
  };
}

function arrowHead(
  tx: number,
  ty: number,
  cx: number,
  cy: number,
) {
  const { ux, uy, px, py } = unit(cx, cy, tx, ty);
  const ah = 10;
  const baseX = tx - ux * ah;
  const baseY = ty - uy * ah;
  return `M ${tx} ${ty} L ${baseX + px * 5} ${baseY + py * 5} L ${baseX - px * 5} ${baseY - py * 5} Z`;
}

function containsParen(
  tx: number,
  ty: number,
  cx: number,
  cy: number,
) {
  const { ux, uy, px, py } = unit(cx, cy, tx, ty);
  const gap = 11;
  const bx = tx - ux * gap;
  const by = ty - uy * gap;
  const half = 9;
  const depth = 7;
  return {
    endX: bx - ux * 2,
    endY: by - uy * 2,
    paren: `M ${bx + px * half} ${by + py * half} Q ${bx - ux * depth} ${by - uy * depth} ${bx - px * half} ${by - py * half}`,
  };
}

export function EdgeTetherLabPage() {
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null);
  const reducedMotion = useReducedMotion(motionOverride);
  const [certainty, setCertainty] = useState(18);
  const [kind, setKind] = useState<EdgeKind>("LEADSTO");
  const [expressesStyle, setExpressesStyle] =
    useState<ExpressesStyle>("thin");
  const [mode, setMode] = useState<CertaintyMode>("slider");
  const [phase, setPhase] = useState(0);
  const [showMissing, setShowMissing] = useState(false);

  const slack = 1 - certainty / 100;
  const { sx, sy, tx, ty } = attach(LEFT, RIGHT);
  const taut = mid(sx, sy, tx, ty);
  const target = slackControl(sx, sy, tx, ty, slack, phase);

  const spring = useSpring({
    cx: reducedMotion ? (slack > 0.5 ? target.x : taut.x) : target.x,
    cy: reducedMotion ? (slack > 0.5 ? target.y : taut.y) : target.y,
    config: reducedMotion
      ? { duration: 0 }
      : { tension: 170 + (1 - slack) * 120, friction: 18 + slack * 10 },
  });

  // Mild phase for uncertain wobble (meaningful unsettled, not decoration)
  useEffect(() => {
    if (reducedMotion || slack < 0.08 || slack > 0.92 || mode === "forming") {
      return;
    }
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setPhase((p) => p + dt * 2.2);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reducedMotion, slack, mode]);

  const playForming = () => {
    setMode("forming");
    setCertainty(8);
    window.setTimeout(() => setCertainty(100), reducedMotion ? 40 : 120);
    window.setTimeout(() => setMode("slider"), reducedMotion ? 200 : 900);
  };

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <main className="tether-lab">
        <header className="tether-lab__chrome">
          <p className="tether-lab__eyebrow">Design lab</p>
          <h1 className="tether-lab__title">Edge tether</h1>
          <p className="tether-lab__lede">
            An edge is a quadratic tether. The control point carries certainty:
            taut = certain, slack = uncertain. Forming is slack springing to
            taut.
          </p>
          <nav className="tether-lab__nav" aria-label="Labs">
            <a href="#/explorations/trial">Trial</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/edges">Edge forms</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/orbiters">Orbiters</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/membrane">Membrane</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/connect">Connect</a>
          </nav>

          <div className="tether-lab__controls">
            <label className="tether-lab__range">
              <span>Certainty</span>
              <input
                type="range"
                min={0}
                max={100}
                value={certainty}
                onChange={(e) => {
                  setMode("slider");
                  setCertainty(Number(e.target.value));
                }}
              />
              <output>{certainty}</output>
            </label>

            <div className="tether-lab__choices" aria-label="Edge type">
              {(
                ["LEADSTO", "CONTAINS", "NEARTO", "EXPRESSES"] as EdgeKind[]
              ).map((k) => (
                <button
                  key={k}
                  type="button"
                  className={kind === k ? "is-active" : ""}
                  onClick={() => setKind(k)}
                >
                  {k}
                </button>
              ))}
            </div>

            {kind === "EXPRESSES" && (
              <div className="tether-lab__choices" aria-label="EXPRESSES style">
                <button
                  type="button"
                  className={expressesStyle === "thin" ? "is-active" : ""}
                  onClick={() => setExpressesStyle("thin")}
                >
                  Thin / light
                </button>
                <button
                  type="button"
                  className={expressesStyle === "dot" ? "is-active" : ""}
                  onClick={() => setExpressesStyle("dot")}
                >
                  Dotted
                </button>
              </div>
            )}

            <div className="tether-lab__choices">
              <button type="button" onClick={playForming}>
                Play forming
              </button>
              <button
                type="button"
                className={showMissing ? "is-active" : ""}
                onClick={() => setShowMissing((v) => !v)}
              >
                Missing-edge test
              </button>
            </div>

            <label className="tether-lab__toggle">
              <input
                type="checkbox"
                checked={reducedMotion}
                onChange={(e) => setMotionOverride(e.target.checked)}
              />
              Reduced motion
            </label>
          </div>
        </header>

        <section className="tether-lab__stage-wrap">
          {!showMissing ? (
            <div className="tether-lab__stage" style={{ width: STAGE_W, height: STAGE_H }}>
              <div
                className="tether-lab__node"
                style={{ left: LEFT.x - NODE_R, top: LEFT.y - NODE_R }}
              >
                Source
              </div>
              <div
                className="tether-lab__node"
                style={{ left: RIGHT.x - NODE_R, top: RIGHT.y - NODE_R }}
              >
                Target
              </div>

              <svg className="tether-lab__svg" width={STAGE_W} height={STAGE_H}>
                <animated.path
                  d={to([spring.cx, spring.cy], (cx, cy) => {
                    if (kind === "CONTAINS") {
                      const p = containsParen(tx, ty, cx, cy);
                      return `M ${sx} ${sy} Q ${cx} ${cy} ${p.endX} ${p.endY}`;
                    }
                    return `M ${sx} ${sy} Q ${cx} ${cy} ${tx} ${ty}`;
                  })}
                  fill="none"
                  stroke="var(--ink)"
                  strokeWidth={
                    kind === "EXPRESSES" && expressesStyle === "thin" ? 1.15 : 1.75
                  }
                  strokeOpacity={
                    kind === "EXPRESSES" && expressesStyle === "thin" ? 0.72 : 1
                  }
                  strokeDasharray={
                    kind === "EXPRESSES" && expressesStyle === "dot"
                      ? "0 6.5"
                      : undefined
                  }
                  strokeLinecap={
                    kind === "EXPRESSES" && expressesStyle === "dot"
                      ? "round"
                      : "square"
                  }
                />
                {kind === "LEADSTO" && (
                  <animated.path
                    d={to([spring.cx, spring.cy], (cx, cy) =>
                      arrowHead(tx, ty, cx, cy),
                    )}
                    fill="var(--ink)"
                  />
                )}
                {kind === "CONTAINS" && (
                  <animated.path
                    d={to([spring.cx, spring.cy], (cx, cy) =>
                      containsParen(tx, ty, cx, cy).paren,
                    )}
                    fill="none"
                    stroke="var(--ink)"
                    strokeWidth={1.75}
                    strokeLinecap="square"
                  />
                )}
                <animated.circle
                  cx={spring.cx}
                  cy={spring.cy}
                  r={3}
                  fill="var(--canvas)"
                  stroke="var(--ink)"
                  strokeWidth={1}
                  opacity={0.55}
                />
              </svg>
            </div>
          ) : (
            <div className="tether-lab__stage" style={{ width: STAGE_W, height: STAGE_H }}>
              <div
                className="tether-lab__node"
                style={{ left: GAP_A.x - NODE_R, top: GAP_A.y - NODE_R }}
              >
                Auth
              </div>
              <div
                className="tether-lab__node"
                style={{ left: GAP_B.x - NODE_R, top: GAP_B.y - NODE_R }}
              >
                Session
              </div>
              {/* No bridge drawn — the gap must read from proximity alone */}
              <p className="tether-lab__gap-caption">
                Close masses, field-taut space, no bridge — a relational gap.
              </p>
            </div>
          )}

          <p className="tether-lab__status" role="status">
            {showMissing
              ? "Missing-edge test: does the unbridged space read as absence of a relation?"
              : slack < 0.12
                ? "Taut — certain relation."
                : slack > 0.75
                  ? "Slack — uncertain / not yet real."
                  : mode === "forming"
                    ? "Forming — control point springing slack → taut."
                    : "Partly settled tether."}
          </p>
        </section>
      </main>
    </MotionConfig>
  );
}
