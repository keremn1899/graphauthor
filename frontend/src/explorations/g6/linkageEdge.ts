import {
  ExtensionCategory,
  Line,
  register,
  type BaseEdgeStyleProps,
  type EdgeData,
} from "@antv/g6";
import type { PathArray } from "@antv/util";
import {
  lensVisualKindOf,
  type LensVisualEdgeKind,
} from "./lensEdgeOptions";

export const LINKAGE_EDGE = "linkage-edge";

type LinkageEdgeStyle = BaseEdgeStyleProps & {
  edgeKind?: LensVisualEdgeKind;
};

/** Linkage filament — always drawn as a plain straight line. */
class LinkageEdge extends Line {
  protected getKeyPath(attributes: Required<LinkageEdgeStyle>): PathArray {
    const [sourcePoint, targetPoint] = this.getEndpoints(attributes);
    return [
      ["M", sourcePoint[0], sourcePoint[1]],
      ["L", targetPoint[0], targetPoint[1]],
    ];
  }
}

let registered = false;

export function ensureLinkageEdgeRegistered() {
  if (registered) return;
  register(ExtensionCategory.EDGE, LINKAGE_EDGE, LinkageEdge);
  registered = true;
}

/** Resolve kind for style mappers. */
export function linkageEdgeKind(datum: EdgeData): LensVisualEdgeKind {
  return lensVisualKindOf(datum);
}

/** Every canonical edge is directed except NEARTO, which is symmetric. */
export function isDirectedKind(kind: LensVisualEdgeKind) {
  return kind !== "nearto";
}

/**
 * Full arrow size for a directed kind.
 */
export function arrowSizeForKind(kind: LensVisualEdgeKind) {
  if (kind === "contains") return 8.5;
  if (kind === "leadsto") return 8;
  return 8;
}
