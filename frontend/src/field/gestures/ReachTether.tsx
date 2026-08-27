import { animated, to, useSpring } from "@react-spring/web";

type ReachTetherProps = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  /** Signed bow: 0 taut … ±1 max slack (negative flips to the other side). */
  slack: number;
  reducedMotion: boolean;
  /** Skip spring — stick control point to target immediately (e.g. while dragging). */
  immediate?: boolean;
  /** Called once after spring settles near the current target (used to lock firm edges). */
  onRest?: () => void;
};

/** Geometric control-point tether for the connect gesture. */
export function ReachTether({
  x1,
  y1,
  x2,
  y2,
  slack,
  reducedMotion,
  immediate = false,
  onRest,
}: ReachTetherProps) {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const px = -dy / len;
  const py = dx / len;
  const absSlack = Math.min(1, Math.abs(slack));
  const bow = slack * 36;
  const targetCx = mx + px * bow;
  const targetCy = my + py * bow;

  const spring = useSpring({
    cx: targetCx,
    cy: targetCy,
    immediate: immediate || reducedMotion,
    config: reducedMotion
      ? { duration: 0 }
      : {
          tension: 170 + (1 - absSlack) * 120,
          friction: absSlack > 0.35 ? 14 : 20,
        },
    onRest: () => {
      onRest?.();
    },
  });

  // Flow-space path — parent should be ViewportPortal (transformed with the view).
  return (
    <svg
      className="field-reach-tether"
      width={1}
      height={1}
      style={{ overflow: "visible", pointerEvents: "none" }}
    >
      <animated.path
        d={to(
          [spring.cx, spring.cy],
          (cx, cy) => {
            // Near-chord control ≈ straight — draw L so lock matches firm edge exactly
            if (Math.hypot(cx - mx, cy - my) < 0.45) {
              return `M ${x1} ${y1} L ${x2} ${y2}`;
            }
            return `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
          },
        )}
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.75}
        strokeLinecap="square"
        opacity={1}
      />
    </svg>
  );
}
