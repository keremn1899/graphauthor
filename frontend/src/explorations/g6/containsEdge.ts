import {
  ExtensionCategory,
  Line,
  register,
  type BaseEdgeStyleProps,
} from "@antv/g6";
import type { PathArray } from "@antv/util";
import { containsGeometry } from "../../primitives/edge/edgeGeometry";

export const CONTAINS_EDGE = "contains-edge";

/**
 * Native G6 edge extension for the Field's parent ─────⊂ child language.
 *
 * The key shape is one managed G6 Path with two subpaths: the straight stem
 * and the open enclosure curve. G6 still owns rendering, state, hit-testing,
 * animation and per-frame updates while layouts or dragged nodes move.
 */
class ContainsEdge extends Line {
  protected getKeyPath(
    attributes: Required<BaseEdgeStyleProps>,
  ): PathArray {
    const [sourcePoint, targetPoint] = this.getEndpoints(attributes);
    const targetCenter = this.targetNode.getCenter();
    const targetRadius = Math.hypot(
      targetPoint[0] - targetCenter[0],
      targetPoint[1] - targetCenter[1],
    );
    const geometry = containsGeometry({
      sx: sourcePoint[0],
      sy: sourcePoint[1],
      tx: targetPoint[0],
      ty: targetPoint[1],
      targetRadius,
      targetCenter: { x: targetCenter[0], y: targetCenter[1] },
    });
    const { c1, c2, out1, out2, ctrl } = geometry.contacts;

    return [
      ["M", sourcePoint[0], sourcePoint[1]],
      ["L", ctrl.x, ctrl.y],
      ["M", c1.x, c1.y],
      ["C", out1.x, out1.y, out2.x, out2.y, c2.x, c2.y],
    ];
  }
}

let registered = false;

export function ensureContainsEdgeRegistered() {
  if (registered) return;
  register(ExtensionCategory.EDGE, CONTAINS_EDGE, ContainsEdge);
  registered = true;
}
