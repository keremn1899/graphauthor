/**
 * Shared SVG markers / path builders for typed edges.
 * Iterate designs on the Edge Lab page; trial graph consumes the same builders.
 */

export type EdgeEndpoints = {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
};

function unit(sx: number, sy: number, tx: number, ty: number) {
  const dx = tx - sx;
  const dy = ty - sy;
  const len = Math.hypot(dx, dy) || 1;
  return { ux: dx / len, uy: dy / len, len, px: -dy / len, py: dx / len };
}

function polar(
  cx: number,
  cy: number,
  r: number,
  angle: number,
): { x: number; y: number } {
  return { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r };
}

export type ContainsGeometryOpts = EdgeEndpoints & {
  /** Child node radius — (tx,ty) lies on this circumference facing the parent. */
  targetRadius?: number;
  /** True child center in flow coords (preferred over reconstructing from tx). */
  targetCenter?: { x: number; y: number };
};

/**
 * CONTAINS: parent --------c child
 *
 * One smooth "c" (⊂) stroke, tips touching the child rim:
 * - Each tip's tangent is radial (⊥ to the circumference) — a single cubic
 *   Bezier from tip1 to tip2, not a straight stub + separate arc.
 * - The belly of the c bulges out toward the parent, opening toward the child.
 * No arrowhead.
 */
export function containsGeometry({
  sx,
  sy,
  tx,
  ty,
  targetRadius = 44,
  targetCenter,
}: ContainsGeometryOpts) {
  const { ux, uy } = unit(sx, sy, tx, ty);
  const R = Math.max(targetRadius, 8);

  const cx = targetCenter?.x ?? tx + ux * R;
  const cy = targetCenter?.y ?? ty + uy * R;

  // Attach angle from child center toward parent
  const theta = Math.atan2(ty - cy, tx - cx);

  // Mouth width of the c — keep compact
  const halfAngle = (12 * Math.PI) / 180;
  const a1 = theta + halfAngle;
  const a2 = theta - halfAngle;

  // Tips sit on the rim
  const tipR = R - 0.5;
  const tip1 = polar(cx, cy, tipR, a1);
  const tip2 = polar(cx, cy, tipR, a2);

  // Bezier control handles: leave each tip along its OWN radial (perpendicular
  // to the circle) so the curve meets the rim at a right angle.
  const handle = R * 0.22;
  const h1 = polar(cx, cy, tipR + handle, a1);
  const h2 = polar(cx, cy, tipR + handle, a2);

  const parenPath = `M ${tip1.x} ${tip1.y} C ${h1.x} ${h1.y} ${h2.x} ${h2.y} ${tip2.x} ${tip2.y}`;

  // Exact cubic midpoint B(0.5) = belly of the c. Stem ends here with a butt
  // cap (set in the edge renderer) so ink meets the curve without overshoot.
  const backX =
    0.125 * tip1.x + 0.375 * h1.x + 0.375 * h2.x + 0.125 * tip2.x;
  const backY =
    0.125 * tip1.y + 0.375 * h1.y + 0.375 * h2.y + 0.125 * tip2.y;
  const linePath = `M ${sx},${sy} L ${backX},${backY}`;

  return {
    linePath,
    parenPath,
    contacts: {
      c1: tip1,
      c2: tip2,
      out1: h1,
      out2: h2,
      ctrl: { x: backX, y: backY },
      cx,
      cy,
    },
  };
}

/** LEADSTO: solid line; arrowhead supplied via SVG marker at target. */
export function leadstoGeometry({ sx, sy, tx, ty }: EdgeEndpoints) {
  return { linePath: `M ${sx},${sy} L ${tx},${ty}` };
}

/** EXPRESSES: dotted relation (round caps + zero-length dash → beads). */
export function expressesGeometry({ sx, sy, tx, ty }: EdgeEndpoints) {
  return { linePath: `M ${sx},${sy} L ${tx},${ty}`, dash: "0 6.5" };
}

/** NEARTO: plain undirected solid line. */
export function neartoGeometry({ sx, sy, tx, ty }: EdgeEndpoints) {
  return { linePath: `M ${sx},${sy} L ${tx},${ty}` };
}
