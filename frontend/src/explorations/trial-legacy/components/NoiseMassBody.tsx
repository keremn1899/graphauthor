import { useEffect, useRef } from "react";
import {
  membraneParamsFor,
  membraneStatus,
} from "../../lab/membrane/membraneDefaults";
import { noiseMembranePath } from "../../lab/membrane/noiseMembrane";
import { useReducedMotion } from "../hooks/useReducedMotion";

type NoiseMassBodyProps = {
  nodeId: string;
  certainty: number;
  radius: number;
  /** Extra pad around the SVG so spikes aren't clipped */
  pad?: number;
  reducedMotion?: boolean;
};

/**
 * Noise-living mass silhouette for provisional / unresolved certainty.
 * Settled nodes should not mount this.
 */
export function NoiseMassBody({
  nodeId,
  certainty,
  radius,
  pad = 10,
  reducedMotion: reducedMotionProp,
}: NoiseMassBodyProps) {
  const pathRef = useRef<SVGPathElement | null>(null);
  const timeRef = useRef(0);
  const hookReduced = useReducedMotion(null);
  const reducedMotion = reducedMotionProp ?? hookReduced;

  const status = membraneStatus(certainty);
  const size = radius * 2 + pad * 2;

  useEffect(() => {
    if (status === "settled") return;
    const path = pathRef.current;
    if (!path) return;

    const params = membraneParamsFor(certainty, radius, nodeId);
    if (!params) return;

    const paint = (time: number) => {
      path.setAttribute(
        "d",
        noiseMembranePath(radius, radius, radius, time, params),
      );
    };

    if (reducedMotion) {
      paint(params.seed * 12.7);
      return;
    }

    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      timeRef.current += params.step * dt;
      paint(timeRef.current);
      raf = requestAnimationFrame(tick);
    };
    paint(timeRef.current);
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [certainty, radius, nodeId, reducedMotion, status]);

  if (status === "settled") return null;

  return (
    <svg
      className="mass-node__noise"
      width={size}
      height={size}
      viewBox={`${-pad} ${-pad} ${size} ${size}`}
      aria-hidden
    >
      <path
        ref={pathRef}
        className={`mass-node__noise-path mass-node__noise-path--${status}`}
        fill="var(--node-fill)"
        stroke="none"
      />
    </svg>
  );
}
