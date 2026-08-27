import {
  ExtensionCategory,
  Line,
  register,
  type BaseEdgeStyleProps,
  type EdgeData,
  type Graph,
} from "@antv/g6";
import type { PathArray } from "@antv/util";

/**
 * Ambient linkage edge — same straight filament as linkage-edge, but label
 * placement reads live lens fields from edge data:
 *   `_lp`  — 0…1 along the stroke (closest point to the cursor, on the edge)
 *
 * Node-hover bond labels use a fixed pixel distance from the hovered
 * endpoint (not a % of edge length), so short and long bonds sit alike.
 * Focus-lit edges use that same distance: a named chip is a named chip.
 *
 * Writing placement via style.update is unreliable; baking `_lp` into
 * getLabelStyle makes the chip track the pointer along the filament.
 */
export const AMBIENT_LINKAGE_EDGE = "ambient-linkage-edge";

/** Bond chip sits this many px along the stroke from the hovered node. */
export const BOND_LABEL_ALONG_PX = 44;

type AmbientEdgeStyle = BaseEdgeStyleProps & {
  edgeKind?: string;
  directBondSide?: "source" | "target" | "";
};

export type AmbientEdgeDodge = {
  amount: number;
  x: number;
  y: number;
  /** Spread angle around the held disc, not a frozen world point. */
  fanAngle?: number;
  fanAlong?: number;
  fanFromSource?: boolean;
  viaFromX?: number;
  viaFromY?: number;
  viaToX?: number;
  viaToY?: number;
};

function mix(from: number, to: number, amount: number) {
  return from + (to - from) * amount;
}

function pointAlong(
  from: [number, number],
  to: [number, number],
): [number, number] {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const len = Math.hypot(dx, dy);
  if (!(len > 1)) return from;
  const along = Math.min(BOND_LABEL_ALONG_PX, len * 0.45);
  const u = along / len;
  return [from[0] + dx * u, from[1] + dy * u];
}

function hasFan(dodge: AmbientEdgeDodge) {
  return typeof dodge.fanAngle === "number" && typeof dodge.fanAlong === "number";
}

function hasVia(dodge: AmbientEdgeDodge) {
  return dodge.viaToX != null && dodge.viaToY != null;
}

function fanVertices(
  source: [number, number],
  target: [number, number],
  dodge: AmbientEdgeDodge,
  origin: { x: number; y: number; radius: number },
): {
  src: [number, number];
  chip: [number, number];
  tgt: [number, number];
} {
  const amount = dodge.amount;
  const fromSource = dodge.fanFromSource === true;
  const held = fromSource ? source : target;
  const far = fromSource ? target : source;
  const ux = Math.cos(dodge.fanAngle ?? 0);
  const uy = Math.sin(dodge.fanAngle ?? 0);
  const along = dodge.fanAlong ?? BOND_LABEL_ALONG_PX;
  const p0Target: [number, number] = [
    origin.x + ux * origin.radius,
    origin.y + uy * origin.radius,
  ];
  const chipTarget: [number, number] = [
    origin.x + ux * (origin.radius + along),
    origin.y + uy * (origin.radius + along),
  ];
  const p0: [number, number] = [
    mix(held[0], p0Target[0], amount),
    mix(held[1], p0Target[1], amount),
  ];
  const straight = pointAlong(held, far);
  const chip: [number, number] = [
    mix(straight[0], chipTarget[0], amount),
    mix(straight[1], chipTarget[1], amount),
  ];
  return fromSource
    ? { src: p0, chip, tgt: target }
    : { src: source, chip, tgt: p0 };
}

function sameTransientValue(a: unknown, b: unknown) {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((value, i) => value === b[i]);
  }
  return false;
}

export type AmbientEdgeDisplayPatch = {
  id: string;
  active: boolean;
  style: Partial<AmbientEdgeStyle>;
};

/**
 * Render instances, indexed without retaining destroyed graphs. Product hover
 * uses this renderer boundary instead of `graph.updateEdgeData() + draw()`:
 * only incident edges are touched and G6 does not recompute every mapper.
 */
const renderedEdges = new WeakMap<Graph, Map<string, AmbientLinkageEdge>>();

function clampUnit(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : 0;
}

function bondLabelPlacement(
  sourcePoint: [number, number],
  targetPoint: [number, number],
  nearSource: boolean,
): number {
  const dx = targetPoint[0] - sourcePoint[0];
  const dy = targetPoint[1] - sourcePoint[1];
  const len = Math.hypot(dx, dy);
  if (!(len > 1)) return 0.5;
  // Cap so we never cross the midpoint on short edges.
  const along = Math.min(BOND_LABEL_ALONG_PX, len * 0.45);
  const ratio = along / len;
  return nearSource ? ratio : 1 - ratio;
}

class AmbientLinkageEdge extends Line {
  private baseAttributes: Partial<AmbientEdgeStyle> = {};
  private transientAttributes: Partial<AmbientEdgeStyle> = {};
  private dodge: AmbientEdgeDodge | null = null;

  constructor(options: ConstructorParameters<typeof Line>[0]) {
    super(options);
    this.baseAttributes = { ...this.attributes };
    const graph = this.context.graph;
    const id = String((this as unknown as { id: string }).id);
    const edges = renderedEdges.get(graph) ?? new Map<string, AmbientLinkageEdge>();
    edges.set(id, this);
    renderedEdges.set(graph, edges);
  }

  public destroy() {
    const graph = this.context.graph;
    const id = String((this as unknown as { id: string }).id);
    renderedEdges.get(graph)?.delete(id);
    super.destroy();
  }

  /**
   * G6 geometry updates and transient hover presentation render together.
   *
   * Base attrs always take the latest G6 computed style (DNA restyles, moves),
   * then the hover transient layer is reapplied on top. Merging only into an
   * ever-growing base without re-seating resting keys let a DNA width/opacity
   * change stay invisible while a prior transient—or a stale base merge—
   * still painted the filament.
   */
  public update(attr: Partial<AmbientEdgeStyle> = {}) {
    this.baseAttributes = { ...this.baseAttributes, ...attr };
    // Super still merges into element.attributes; pass an explicit stack so
    // resting DNA wins over any keys that only exist in a cleared transient.
    super.update({
      ...this.attributes,
      ...this.baseAttributes,
      ...this.transientAttributes,
    });
  }

  public setTransientStyle(style: Partial<AmbientEdgeStyle> | null) {
    this.transientAttributes = style ?? {};
    super.update({
      ...this.attributes,
      ...this.baseAttributes,
      ...this.transientAttributes,
    });
  }

  public hasTransientStyle(style: Partial<AmbientEdgeStyle>) {
    const current = this.transientAttributes as Record<string, unknown>;
    const next = style as Record<string, unknown>;
    const keys = new Set([...Object.keys(current), ...Object.keys(next)]);
    return [...keys].every((key) => sameTransientValue(current[key], next[key]));
  }

  public hasDodge(next: AmbientEdgeDodge | null) {
    if (!this.dodge && !next) return true;
    if (!this.dodge || !next) return false;
    const thisFan = typeof this.dodge.fanAngle === "number";
    const nextFan = typeof next.fanAngle === "number";
    if (thisFan !== nextFan) return false;
    const sameFan =
      !thisFan ||
      (Math.abs((this.dodge.fanAngle ?? 0) - (next.fanAngle ?? 0)) < 0.01 &&
        Math.abs((this.dodge.fanAlong ?? 0) - (next.fanAlong ?? 0)) < 0.15 &&
        this.dodge.fanFromSource === next.fanFromSource);
    const thisVia = this.dodge.viaToX != null;
    const nextVia = next.viaToX != null;
    if (thisVia !== nextVia) return false;
    const sameVia =
      !thisVia ||
      (Math.abs((this.dodge.viaFromX ?? 0) - (next.viaFromX ?? 0)) < 0.15 &&
        Math.abs((this.dodge.viaFromY ?? 0) - (next.viaFromY ?? 0)) < 0.15 &&
        Math.abs((this.dodge.viaToX ?? 0) - (next.viaToX ?? 0)) < 0.15 &&
        Math.abs((this.dodge.viaToY ?? 0) - (next.viaToY ?? 0)) < 0.15);
    return (
      sameFan &&
      sameVia &&
      Math.abs(this.dodge.x - next.x) < 0.15 &&
      Math.abs(this.dodge.y - next.y) < 0.15 &&
      Math.abs(this.dodge.amount - next.amount) < 0.012
    );
  }

  /**
   * Selection dodge: independent of hover paint so clearing a bond does
   * not snap a crossing — or a fanned spoke — back to the chord.
   */
  public setDodge(next: AmbientEdgeDodge | null) {
    const dodge = next && next.amount > 0.01 ? next : null;
    if (this.hasDodge(dodge)) return;
    this.dodge = dodge;
    this.resyncGeometry();
  }

  /**
   * Re-read live endpoints into the current dodge. A relative fan is cheap to
   * keep; G6 moving a node does not by itself ask a custom path to follow.
   */
  public resyncGeometry() {
    super.update({
      ...this.attributes,
      ...this.baseAttributes,
      ...this.transientAttributes,
    });
  }

  private fanOrigin(
    dodge: AmbientEdgeDodge,
    sourcePoint: [number, number],
    targetPoint: [number, number],
  ): { x: number; y: number; radius: number } | null {
    try {
      const graph = this.context.graph;
      const id = String((this as unknown as { id: string }).id);
      const edge = graph?.getEdgeData(id);
      if (!edge) return null;
      const heldId =
        dodge.fanFromSource === true ? String(edge.source) : String(edge.target);
      const [x, y] = graph.getElementPosition(heldId);
      const held = dodge.fanFromSource === true ? sourcePoint : targetPoint;
      const radius = Math.hypot(held[0] - x, held[1] - y);
      return { x, y, radius: radius > 1 ? radius : 12 };
    } catch {
      return null;
    }
  }

  protected getKeyPath(attributes: Required<AmbientEdgeStyle>): PathArray {
    const [sourcePoint, targetPoint] = this.getEndpoints(attributes);
    const dodge = this.dodge;
    if (!dodge || dodge.amount < 0.01) {
      return [
        ["M", sourcePoint[0], sourcePoint[1]],
        ["L", targetPoint[0], targetPoint[1]],
      ];
    }
    if (hasFan(dodge)) {
      const origin = this.fanOrigin(
        dodge,
        sourcePoint as [number, number],
        targetPoint as [number, number],
      );
      if (!origin) {
        return [
          ["M", sourcePoint[0], sourcePoint[1]],
          ["L", targetPoint[0], targetPoint[1]],
        ];
      }
      const { src, chip, tgt } = fanVertices(
        sourcePoint as [number, number],
        targetPoint as [number, number],
        dodge,
        origin,
      );
      return [
        ["M", src[0], src[1]],
        ["L", chip[0], chip[1]],
        ["L", tgt[0], tgt[1]],
      ];
    }
    if (hasVia(dodge)) {
      return [
        ["M", sourcePoint[0], sourcePoint[1]],
        [
          "L",
          mix(dodge.viaFromX ?? sourcePoint[0], dodge.viaToX ?? sourcePoint[0], dodge.amount),
          mix(dodge.viaFromY ?? sourcePoint[1], dodge.viaToY ?? sourcePoint[1], dodge.amount),
        ],
        ["L", targetPoint[0], targetPoint[1]],
      ];
    }
    return [
      ["M", sourcePoint[0], sourcePoint[1]],
      ["L", targetPoint[0], targetPoint[1]],
    ];
  }

  protected getKeyStyle(attributes: Required<AmbientEdgeStyle>) {
    const style = super.getKeyStyle(attributes);
    return {
      ...style,
      // The edge element itself must stay interactive so the picker will
      // walk into the label. The stroke is the thing that must not steal
      // the pointer from discs.
      pointerEvents: "none" as const,
    };
  }

  protected getLabelStyle(attributes: Required<AmbientEdgeStyle>) {
    const style = super.getLabelStyle(this.placedLabelAttributes(attributes));
    if (!style) return false;
    // Filaments stay `pointerEvents: none` so discs remain reachable through
    // them. A named chip is a second neighbour control — hover previews, click
    // jumps — so it has to receive the pointer the stroke refuses.
    return {
      ...style,
      pointerEvents: "auto" as const,
      cursor: "pointer" as const,
    };
  }

  private placedLabelAttributes(attributes: Required<AmbientEdgeStyle>) {
    const graph = (
      this as unknown as {
        context?: {
          graph?: {
            getEdgeData: (id: string) => EdgeData;
            getElementState?: (id: string) => string[];
          };
        };
      }
    ).context?.graph;
    const id = String((this as unknown as { id: string }).id);
    try {
      const edge = graph?.getEdgeData(id);
      if (this.dodge && hasFan(this.dodge) && this.dodge.amount > 0.01) {
        const [sourcePoint, targetPoint] = this.getEndpoints(attributes);
        const origin = this.fanOrigin(
          this.dodge,
          sourcePoint as [number, number],
          targetPoint as [number, number],
        );
        if (!origin) return attributes;
        const { src, chip, tgt } = fanVertices(
          sourcePoint as [number, number],
          targetPoint as [number, number],
          this.dodge,
          origin,
        );
        const first = Math.hypot(chip[0] - src[0], chip[1] - src[1]);
        const second = Math.hypot(tgt[0] - chip[0], tgt[1] - chip[1]);
        const total = first + second;
        return {
          ...attributes,
          labelPlacement: total > 1 ? first / total : 0.5,
          labelOffsetX: 0,
          labelOffsetY: 0,
        };
      }
      if (attributes.directBondSide) {
        const [sourcePoint, targetPoint] = this.getEndpoints(attributes);
        return {
          ...attributes,
          labelPlacement: bondLabelPlacement(
            sourcePoint as [number, number],
            targetPoint as [number, number],
            attributes.directBondSide === "source",
          ),
          labelOffsetX: 0,
          labelOffsetY: 0,
        };
      }
      const bond = clampUnit(edge?.data?._bond);
      // Existing Ambient Canvas consumers still express the completed bond
      // through out/inn states. The workbench adds `_bond` only to make the
      // journey into that state continuous.
      const states = graph?.getElementState?.(id) ?? [];
      const isOut = states.includes("out");
      const isInn = states.includes("inn");
      if (bond > 0.001 || isOut || isInn) {
        const [sourcePoint, targetPoint] = this.getEndpoints(attributes);
        const nearSource =
          bond > 0.001 ? edge?.data?._bondSide !== "target" : isOut;
        const targetPlacement = bondLabelPlacement(
          sourcePoint as [number, number],
          targetPoint as [number, number],
          nearSource,
        );
        const lensPlacement = Number(edge?.data?._lp);
        const fromPlacement = Number.isFinite(lensPlacement)
          ? Math.max(0, Math.min(1, lensPlacement))
          : targetPlacement;
        const progress = bond > 0.001 ? bond : 1;
        return {
          ...attributes,
          labelPlacement:
            fromPlacement + (targetPlacement - fromPlacement) * progress,
          labelOffsetX: 0,
          labelOffsetY: 0,
        };
      }
      // Named chips sit a fixed distance from an endpoint — hover sets
      // `directBondSide`; overlay-lit edges without a held node sit that
      // far from the source, never mid-stroke and never on the cursor lens.
      const intensity = Number(edge?.data?.intensity);
      if (Number.isFinite(intensity) && intensity >= 1) {
        const [sourcePoint, targetPoint] = this.getEndpoints(attributes);
        return {
          ...attributes,
          labelPlacement: bondLabelPlacement(
            sourcePoint as [number, number],
            targetPoint as [number, number],
            true,
          ),
          labelOffsetX: 0,
          labelOffsetY: 0,
        };
      }
      const lens = Number(edge?.data?.lens);
      if (!(lens > 0.008)) return attributes;
      const lp = Number(edge?.data?._lp);
      if (!Number.isFinite(lp)) return attributes;
      return {
        ...attributes,
        labelPlacement: Math.max(0, Math.min(1, lp)),
        labelOffsetX: 0,
        labelOffsetY: 0,
      };
    } catch {
      return attributes;
    }
  }
}

/**
 * Apply sparse display-only changes to rendered edge instances.
 *
 * Deliberately does not mutate graph data: label/arrow visibility is transient
 * pointer presentation, not graph state. Primitive comparisons avoid even an
 * incident-edge render when G6 has already retained the requested display.
 */
export function updateAmbientEdgeDisplay(
  graph: Graph,
  patches: AmbientEdgeDisplayPatch[],
) {
  const edges = renderedEdges.get(graph);
  if (!edges) return 0;
  let updated = 0;
  for (const patch of patches) {
    const edge = edges.get(patch.id);
    if (!edge || edge.destroyed) continue;
    const next = patch.active ? patch.style : {};
    if (edge.hasTransientStyle(next)) continue;
    edge.setTransientStyle(patch.active ? patch.style : null);
    updated += 1;
  }
  return updated;
}

/**
 * Drop every transient hover override so a DNA restyle can set resting stroke /
 * width / opacity without the last hover presentation winning. Re-commit hover
 * after `setNode`/`setEdge`/`draw` if something is still under the pointer.
 */
export function clearAmbientEdgeDisplay(graph: Graph) {
  const edges = renderedEdges.get(graph);
  if (!edges) return 0;
  let cleared = 0;
  for (const edge of edges.values()) {
    if (edge.destroyed) continue;
    if (edge.hasTransientStyle({})) continue;
    edge.setTransientStyle(null);
    cleared += 1;
  }
  return cleared;
}

export type AmbientEdgeDodgePatch = {
  id: string;
  x: number;
  y: number;
  amount: number;
  fanAngle?: number;
  fanAlong?: number;
  fanFromSource?: boolean;
  viaFromX?: number;
  viaFromY?: number;
  viaToX?: number;
  viaToY?: number;
};

/** Fan the held node's spokes, and kink crossing filaments around that same disc. */
export function updateAmbientEdgeDodge(
  graph: Graph,
  patches: AmbientEdgeDodgePatch[],
) {
  const edges = renderedEdges.get(graph);
  if (!edges) return 0;
  let updated = 0;
  for (const patch of patches) {
    const edge = edges.get(patch.id);
    if (!edge || edge.destroyed) continue;
    const next =
      patch.amount > 0.01
        ? {
            x: patch.x,
            y: patch.y,
            amount: patch.amount,
            fanAngle: patch.fanAngle,
            fanAlong: patch.fanAlong,
            fanFromSource: patch.fanFromSource,
            viaFromX: patch.viaFromX,
            viaFromY: patch.viaFromY,
            viaToX: patch.viaToX,
            viaToY: patch.viaToY,
          }
        : null;
    if (edge.hasDodge(next)) continue;
    edge.setDodge(next);
    updated += 1;
  }
  return updated;
}

export function clearAmbientEdgeDodge(graph: Graph) {
  const edges = renderedEdges.get(graph);
  if (!edges) return 0;
  let cleared = 0;
  for (const edge of edges.values()) {
    if (edge.destroyed) continue;
    if (edge.hasDodge(null)) continue;
    edge.setDodge(null);
    cleared += 1;
  }
  return cleared;
}

/** Ask custom filaments to re-read live endpoints without changing dodge. */
export function refreshAmbientEdgeGeometry(
  graph: Graph,
  ids: Iterable<string>,
) {
  const edges = renderedEdges.get(graph);
  if (!edges) return 0;
  let updated = 0;
  for (const id of ids) {
    const edge = edges.get(id);
    if (!edge || edge.destroyed) continue;
    edge.resyncGeometry();
    updated += 1;
  }
  return updated;
}

let registered = false;

export function ensureAmbientLinkageEdgeRegistered() {
  if (registered) return;
  register(ExtensionCategory.EDGE, AMBIENT_LINKAGE_EDGE, AmbientLinkageEdge);
  registered = true;
}
