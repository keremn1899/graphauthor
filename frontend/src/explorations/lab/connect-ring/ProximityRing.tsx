import { motion } from "motion/react";
import { NODE_R, RING_R, annulusClipPath } from "./constants";
import "./ProximityRing.css";

type ProximityRingProps = {
  /** Stage-space center of the node */
  cx: number;
  cy: number;
  active: boolean;
  /** Interactive hit doughnut (only while armed as source) */
  hitEnabled?: boolean;
  onAnnulusPointerDown?: (e: React.PointerEvent) => void;
  reducedMotion?: boolean;
  /** Skip fade/scale (e.g. while dragging a connection). */
  instant?: boolean;
};

/**
 * Dashed grey proximity ring (Note Prototype), centered on a geometric disc.
 * Hit zone = annulus between RING_R and NODE_R.
 */
export function ProximityRing({
  cx,
  cy,
  active,
  hitEnabled = false,
  onAnnulusPointerDown,
  reducedMotion = false,
  instant = false,
}: ProximityRingProps) {
  const box = RING_R * 2;
  const snap = reducedMotion || instant;

  return (
    <div
      className="proximity-ring"
      style={{
        left: cx - RING_R,
        top: cy - RING_R,
        width: box,
        height: box,
      }}
    >
      <svg
        className="proximity-ring__svg"
        width={box}
        height={box}
        viewBox={`0 0 ${box} ${box}`}
        aria-hidden
      >
        <motion.circle
          cx={RING_R}
          cy={RING_R}
          r={RING_R}
          className="proximity-ring__circle"
          initial={false}
          animate={{
            opacity: active ? 1 : 0,
            scale: active ? 1 : 0.9,
          }}
          transition={
            snap ? { duration: 0 } : { duration: 0.2, ease: "easeOut" }
          }
          style={{ transformOrigin: `${RING_R}px ${RING_R}px` }}
        />
        {/* Punch through to node border — line attaches there, not the ring */}
        <circle
          cx={RING_R}
          cy={RING_R}
          r={NODE_R}
          fill="var(--canvas)"
          stroke="none"
          pointerEvents="none"
        />
      </svg>

      {hitEnabled && (
        <div
          className="proximity-ring__hit"
          style={{ clipPath: annulusClipPath() }}
          onPointerDown={onAnnulusPointerDown}
          onContextMenu={(e) => e.preventDefault()}
        />
      )}
    </div>
  );
}
