import {
  Graph,
  type EdgeData,
  type GraphData,
  type IElementEvent,
  type NodeData,
} from "@antv/g6";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SelectionAntRing } from "../explorations/SelectionAntRing";
import {
  AMBIENT_LINKAGE_EDGE,
  BOND_LABEL_ALONG_PX,
  clearAmbientEdgeDisplay,
  clearAmbientEdgeDodge,
  ensureAmbientLinkageEdgeRegistered,
  refreshAmbientEdgeGeometry,
  updateAmbientEdgeDisplay,
  updateAmbientEdgeDodge,
} from "../explorations/lab/ambientLinkageEdge";
import {
  arrowSizeForKind,
  isDirectedKind,
  linkageEdgeKind,
} from "../explorations/g6/linkageEdge";
import {
  GRAPH_DNA_GEOMETRY,
  GRAPH_DNA_INTERACTION,
  mixHex,
  radixValue,
  resolveGraphDna,
  resolveGraphDnaFocus,
  resolveGraphDnaProvisional,
  type ResolvedGraphDna,
  type ResolvedGraphDnaFocus,
  type ThemeMode,
} from "../styles/graphDna";
import {
  createMotionPlan,
  createMotionPlans,
  MOTION_DURATION_MS,
  MOTION_SPINE,
  type MotionPlan,
} from "../styles/motion";
import { g6StateMotion } from "../styles/motionG6";
import { FONT_SANS_FAMILY } from "../styles/typography";
import { useGraphDnaRuntime } from "./graphDnaRuntime";
import "./ProductGraphCanvas.css";

export type ProductGraphMode = "ambient" | "focus" | "proposal" | "diff";

type HoverBundle = { out: Set<string>; inn: Set<string> };

type ProductGraphCanvasProps = {
  data: GraphData;
  /**
   * Identity of the asked map (catalogue id + lens). File-stem `graph_id` is
   * not unique across workbooks, so this is what counts as a replace.
   */
  mapKey?: string;
  mode?: ProductGraphMode;
  theme?: ThemeMode;
  /**
   * Draw this graph as unpublished: same room, less presence. A palette rather
   * than an opacity on the container, so focus and selection — which are drawn
   * over the resting look — keep their full strength.
   */
  provisional?: boolean;
  frameIds?: string[];
  /** Controlled selection (e.g. reader panel / link chips). */
  selectedId?: string | null;
  /**
   * A node the reader asked the camera to look at. Distinct from `selectedId`
   * because clicking the map already has the node under the pointer — only a
   * pick from the neighbour strip, an edge-label chip, Find, or anywhere else
   * off the disc should fly, and it should fly the same way a focus re-frame
   * does.
   */
  followId?: string | null;
  /**
   * A neighbour the reader is indicating without selecting. The bond(s)
   * between it and the inspected node go solid → dotted — emit on, absorb
   * off. Jumping the row clears this and the filament settles back.
   */
  previewId?: string | null;
  onSelect?: (nodeId: string | null) => void;
  /**
   * Pointer over a node (or the other end of a named chip). Used to warm the
   * body/sources cache so a click does not flash "Reading body…".
   */
  onHover?: (nodeId: string | null) => void;
  /** Hovering a named chip, same as hovering its neighbour in the reader. */
  onPreview?: (nodeId: string | null) => void;
  /**
   * Clicking a named chip. The neighbour is not under the pointer, so this
   * is a jump — inspect and fly — not a canvas select.
   */
  onJump?: (nodeId: string) => void;
  /**
   * Published whenever the set of hand-moved nodes changes, so a surface can
   * offer undo/redo/reset. `null` while the graph is not mounted.
   */
  onNudgesChange?: (state: NudgeState | null) => void;
  /** The map data loaded and G6 could not draw it — a place failure. */
  onRenderError?: (message: string | null) => void;
  /**
   * False while this canvas has no scene for the current layout (first paint,
   * or a graph/lens replace). True after that layout has been drawn. Focus
   * rewrites do not count — the nodes did not move.
   */
  onSceneReady?: (ready: boolean) => void;
};

/** A node moved by hand, and where the layout had put it. */
type Nudge = { id: string; from: Point; to: Point };

export type NudgeState = {
  /** How many nodes currently sit somewhere the layout did not put them. */
  count: number;
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
  /** Put every hand-moved node back where the arrangement placed it. */
  reset: () => void;
};

type Point = { x: number; y: number };

const defaultGeometry = GRAPH_DNA_GEOMETRY;
const defaultInteraction = GRAPH_DNA_INTERACTION;
/**
 * Canvas-element motion: still off, and now for a measured reason.
 *
 * This is G6 interpolating every element that differs on a data or state
 * change. On a 2000-node map that measured a **2.09 second block with no frame
 * painted** — not slow, stopped. It stays off until the transition stops
 * replacing the whole scene to express a change in a few dozen elements.
 *
 * It used to be the only flag, which meant the selection ring was held off by
 * a fact about the canvas that has nothing to do with it. See
 * `GRAPH_DNA_INTERACTION.selectionMotion`. */
const PRODUCT_GRAPH_MOTION_ENABLED = false;
const VIEWPORT_EDGE_SHED_THRESHOLD = 600;
/** Neighbour-row preview: solid → beads, quicker than a focus emit.
 *
 * 150/110ms are deliberate overrides of the emit/absorb spine, set through
 * `createMotionPlan`'s `durationMs` (the sanctioned one-off channel), not a
 * hand-copied bezier. The pair is the pointer's question-and-answer on a row
 * hover: it must complete inside the time a hover means anything, well under
 * the 280/190ms a *committed* change gets. Quicker, same intent, same curves.
 */
const PREVIEW_ON = createMotionPlan("emit", { durationMs: 150 });
const PREVIEW_OFF = createMotionPlan("absorb", { durationMs: 110 });
/** Selection dodge: local angular moves around the held disc.
 *
 * 220/160ms override the spine for the same reason, but the opposite way: a
 * dodge must not read as instant (it is geometry moving, which the eye needs
 * to track) yet must not linger like a commit. The margin over preview is the
 * difference between "this edge got out of the way" and "the graph changed".
 */
const DODGE_ON = createMotionPlan("emit", { durationMs: 220 });
const DODGE_OFF = createMotionPlan("absorb", { durationMs: 160 });
/** Air around the held disc, beyond the painted radius. */
const DISC_AIR = 10;
/** Air around a named chip's covering circle. */
const CHIP_AIR = 10;
const DODGE_MAX_EDGES = 64;
/** Minimum angle between fanned / kinked strokes, in radians. */
const FAN_MIN_ARC = 0.26;
/** How far a stroke may leave its layout angle, in radians. */
const FAN_MAX_DEFLECT = 0.55;
const FAN_SKIP = 0.03;

/** Round caps turn a collapsing dash into DNA beads. */
function previewLineDash(amount: number, gap: number): number[] {
  if (amount < 0.02) return [];
  return [(1 - amount) * gap * 8, amount * gap];
}

/**
 * A name exists iff the disc can hold readable type.
 *
 * Labels stay at the authored world size. They shrink with the camera, same
 * as the disc — type is not stepped up as you zoom out. The old gate withheld
 * every name the moment `labelSize × zoom` dropped below 5px, while the disc
 * was still ~40px, so a still-legible map went blank as one boolean.
 *
 * Names now drop only when the disc on screen can no longer hold a stack of
 * readable lines (`maxLines × 5px × lineHeight`). The cutoff means "this
 * disc is a letter", not "we gave up early". Sticky across a 1.25× band so a
 * wheel sitting on the line does not flash.
 *
 * Returning "" still skips shaping entirely. This widens the zoom band that
 * pays for text; it does not re-price a frame.
 *
 * **This is not the deferred LOD band disclosure.** Full map, uncapped, no
 * importance ranking. The only thing withheld is glyphs the disc cannot hold.
 */
const READABLE_LABEL_PX = 5;
/** Hysteresis on the disc-size cutoff, so a boundary zoom does not flash. */
const LABEL_HIDE_HYSTERESIS = 1.25;

function nodeLabelsVisible(
  zoom: number,
  disc: number,
  lineHeight: number,
  maxLines: number,
  currentlyShown: boolean,
): boolean {
  if (!(disc > 0) || maxLines < 1 || lineHeight <= 0) return false;
  const safeZoom = zoom > 0.01 ? zoom : 0.01;
  const hideBelow = maxLines * READABLE_LABEL_PX * lineHeight;
  const discScreen = disc * safeZoom;
  if (currentlyShown) return discScreen >= hideBelow;
  return discScreen >= hideBelow * LABEL_HIDE_HYSTERESIS;
}

function intensityOf(datum: NodeData | EdgeData) {
  const value = Number(datum.data?.intensity);
  return Number.isFinite(value) ? value : 0;
}

function isLit(datum: NodeData | EdgeData) {
  return intensityOf(datum) >= 1 || datum.data?.proposed === true;
}

function diffOf(datum: NodeData | EdgeData) {
  const value = String(datum.data?.diff ?? "unchanged");
  return value === "added" || value === "removed" || value === "touched"
    ? value
    : "unchanged";
}

function lensOf(datum: EdgeData) {
  const value = Number(datum.data?.lens);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

function bondOf(datum: EdgeData) {
  const value = Number(datum.data?._bond);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
}

/** Opacity a spoke keeps at rest, when the workbench has not overridden it. */
const SPOKE_REST_OPACITY = GRAPH_DNA_GEOMETRY.spokeRestOpacity;

/**
 * How much an edge should be held back for being a spoke: fully at rest, not at
 * all once it is lit or hovered.
 *
 * Spokes are the edges from a packed root to each of its branches, named by the
 * server because no arrangement can draw them well — a root with 59 children is
 * a star, and a star laid into a grid crosses whatever lies between. On `rfc`
 * that is 59 edges producing *every one* of the map's crossings. They also say
 * almost nothing: "these branches hang off the root" is the one thing an
 * operator can already see from the shape.
 *
 * So they are drawn quietly rather than hidden. Hiding them would be a lie
 * about what the graph asserts, and the moment someone actually asks about the
 * root — focuses it, or hovers it — its spokes are exactly what they want, so
 * the dimming lifts in proportion to how lit the edge is.
 */
function spokeDimOf(datum: EdgeData, rest = SPOKE_REST_OPACITY) {
  if (datum.data?.spoke !== true) return 1;
  const attention = Math.max(intensityOf(datum), bondOf(datum));
  return rest + (1 - rest) * attention;
}

/**
 * The opacity an edge sits at when nothing is touching it.
 *
 * Module-level because the hover layer patches opacity directly and has to be
 * able to put an edge *back*: computing rest in two places is how a spoke ends
 * up brighter after being hovered than it ever was before.
 *
 * Under an inverted field this is flat 1 and separation is carried by ink —
 * `focus.lit` against `focus.dimEdge` — rather than by opacity. Dimming an
 * already-dim edge on a near-black field does not make it quieter, it makes it
 * absent, and an absent edge is a claim the graph never made.
 */
function restingEdgeOpacity(
  datum: EdgeData,
  inverted: boolean,
  edgeOpacity: number,
  spokeRest = SPOKE_REST_OPACITY,
) {
  const base = inverted
    ? 1
    : Math.min(
        1,
        edgeOpacity +
          0.25 * lensOf(datum) +
          (1 - edgeOpacity) * bondOf(datum),
      );
  return spokeDimOf(datum, spokeRest) * base;
}

/**
 * How a filament is painted — one recipe, whether the edge is named because
 * the overlay lit it or because a node is held (hover or selection).
 *
 * These used to be two functions. Focus-lit chips mixed `lensLabel` onto a
 * mid-stroke knockout; the hover layer then invented a brighter fill, a
 * different stroke, a thicker line, and slid the chip onto the node. Selecting
 * a subject therefore did not look like highlighting one. The patch is not a
 * second language: it turns the same recipe on and off.
 */
type EdgeLook = {
  inverted: boolean;
  palette: ResolvedGraphDna;
  focus: ResolvedGraphDnaFocus;
  edgeWidth: number;
  edgeOpacity: number;
  edgeLabelOpacity: number;
  spokeRestOpacity: number;
};

function edgePaint(datum: EdgeData, look: EdgeLook, named: boolean) {
  const kind = linkageEdgeKind(datum);
  const directed = named && isDirectedKind(kind);
  const arrowSize = arrowSizeForKind(kind);
  const presence = named ? 1 : 0;
  const rest = look.inverted
    ? mixHex(
        named || isLit(datum) ? look.focus.lit : look.focus.dimEdge,
        look.focus.lit,
        lensOf(datum) * 0.82,
      )
    : look.palette.filament;
  const stroke = mixHex(
    rest,
    look.inverted ? look.focus.bondLabel : look.palette.filament,
    named && look.inverted ? 0 : bondOf(datum),
  );
  const labelFill = named
    ? look.inverted
      ? look.focus.lit
      : look.palette.bondLabel
    : mixHex(
        look.inverted ? look.focus.lensLabel : look.palette.lensLabel,
        look.inverted ? look.focus.lit : look.palette.bondLabel,
        bondOf(datum),
      );
  // Knockout, not a card: the chip has to be the field the filaments sit on,
  // or it reads as a plate. Construction raises that field a step; using a
  // separate chip token (or G6's white theme default) is how the plate appeared.
  const field = look.inverted ? look.focus.field : look.palette.canvas;
  return {
    stroke,
    lineWidth:
      look.edgeWidth +
      0.55 * lensOf(datum) +
      0.65 * (named ? 1 : bondOf(datum)),
    opacity: named
      ? 1
      : restingEdgeOpacity(
          datum,
          look.inverted,
          look.edgeOpacity,
          look.spokeRestOpacity,
        ),
    label: named,
    labelText: named ? String(datum.data?.label ?? "") : "",
    labelFill,
    labelBackground: named,
    labelBackgroundFill: field,
    labelBackgroundOpacity: named ? 1 : 0,
    labelOpacity: named ? look.edgeLabelOpacity : 0,
    endArrow: directed,
    endArrowType: "triangle" as const,
    endArrowSize: arrowSize,
    endArrowFill: look.inverted ? look.focus.lit : look.palette.filament,
    endArrowFillOpacity: presence,
    endArrowStrokeOpacity: presence,
    endArrowOffset: (arrowSize * presence) / 2 + presence,
  };
}

/** A node's current drawn position, or null if the graph no longer holds it. */
function positionOf(graph: Graph, nodeId: string): Point | null {
  try {
    const [x, y] = graph.getElementPosition(nodeId);
    return { x, y };
  } catch {
    return null;
  }
}

function moveTo(graph: Graph, nodeId: string, point: Point | null): void {
  if (!point) return;
  try {
    // Returns a promise; a rejection here means the element vanished mid-move,
    // which is the same non-event as the throw below.
    void graph.translateElementTo(nodeId, [point.x, point.y], false)
      .catch(() => {});
  } catch {
    // The node has left the graph — a commit removed it while it sat nudged.
    // Nothing to move, and nothing worth interrupting the operator over.
  }
}

/** Sub-pixel differences are not gestures; a click must not count as a drag. */
function moved(a: Point | null, b: Point | null): boolean {
  if (!a || !b) return false;
  return Math.abs(a.x - b.x) > 0.5 || Math.abs(a.y - b.y) > 0.5;
}

function emptyHoverBundle(): HoverBundle {
  return { out: new Set(), inn: new Set() };
}

/**
 * Pointer hover wins placement when the same bond belongs to more than one
 * source; later sources then contribute every other incident bond.
 *
 * Order matters: canvas pointer, then selection.
 */
function combineHoverBundles(
  primary: HoverBundle,
  ...others: HoverBundle[]
): HoverBundle {
  const combined = emptyHoverBundle();
  for (const id of primary.out) combined.out.add(id);
  for (const id of primary.inn) combined.inn.add(id);
  for (const other of others) {
    for (const id of other.out) {
      if (!combined.out.has(id) && !combined.inn.has(id)) combined.out.add(id);
    }
    for (const id of other.inn) {
      if (!combined.out.has(id) && !combined.inn.has(id)) combined.inn.add(id);
    }
  }
  return combined;
}

function hoverBundleFor(graph: Graph, nodeId: string): HoverBundle {
  const bundle = emptyHoverBundle();
  for (const edge of graph.getRelatedEdgesData(nodeId)) {
    const id = String(edge.id);
    if (String(edge.source) === nodeId) bundle.out.add(id);
    else bundle.inn.add(id);
  }
  return bundle;
}

/** The other end of a bond, given the disc that currently owns it. */
function otherEndpoint(
  graph: Graph,
  edgeId: string,
  heldId: string | null,
): string | null {
  if (!heldId || !edgeId) return null;
  const edge = graph.getEdgeData(edgeId);
  if (!edge) return null;
  const source = String(edge.source);
  const target = String(edge.target);
  if (source === heldId) return target;
  if (target === heldId) return source;
  return null;
}

/**
 * Which named chip, if any, sits under the pointer.
 *
 * Chips are placed `BOND_LABEL_ALONG_PX` along the filament from the disc
 * *surface*, not from the centre. A 90px disc puts that point well outside
 * the node; measuring from the centre put the hit inside it, so hover never
 * saw a chip.
 */
function chipAtPointer(
  graph: Graph,
  heldId: string | null,
  clientX: number,
  clientY: number,
  fontSize: number,
  nodeDiameter: number,
  liveChips?: Map<string, { dest: Point; amount: number }>,
): { edgeId: string; otherId: string } | null {
  if (!heldId) return null;
  const held = positionOf(graph, heldId);
  if (!held) return null;
  let world: [number, number];
  try {
    world = graph.getCanvasByClient([clientX, clientY]) as [number, number];
  } catch {
    return null;
  }
  const [wx, wy] = world;
  const zoom = Math.max(graph.getZoom() || 1, 0.05);
  const radius = nodeDiameter / 2;
  if (Math.hypot(wx - held.x, wy - held.y) < radius + 2) return null;

  let best: { dist: number; edgeId: string; otherId: string } | null = null;
  for (const edge of graph.getRelatedEdgesData(heldId)) {
    const other =
      String(edge.source) === heldId
        ? String(edge.target)
        : String(edge.source);
    const there = positionOf(graph, other);
    if (!there) continue;
    const dx = there.x - held.x;
    const dy = there.y - held.y;
    const span = Math.hypot(dx, dy);
    if (!(span > 1)) continue;
    const ux = dx / span;
    const uy = dy / span;
    const sx = held.x + ux * radius;
    const sy = held.y + uy * radius;
    const tx = there.x - ux * radius;
    const ty = there.y - uy * radius;
    const filament = Math.hypot(tx - sx, ty - sy);
    if (!(filament > 1)) continue;
    const along = Math.min(BOND_LABEL_ALONG_PX, filament * 0.45);
    let cx = sx + ((tx - sx) / filament) * along;
    let cy = sy + ((ty - sy) / filament) * along;
    const live = liveChips?.get(String(edge.id));
    if (live && live.amount > 0.02) {
      cx += (live.dest.x - cx) * live.amount;
      cy += (live.dest.y - cy) * live.amount;
    }
    const label = String(edge.data?.label ?? "");
    const halfW = Math.max(16 / zoom, label.length * fontSize * 0.38 + 10);
    const halfH = Math.max(14 / zoom, fontSize * 1.05 + 8);
    if (Math.abs(wx - cx) > halfW || Math.abs(wy - cy) > halfH) continue;
    const dist = Math.hypot(wx - cx, wy - cy);
    if (!best || dist < best.dist) {
      best = { dist, edgeId: String(edge.id), otherId: other };
    }
  }
  return best;
}

/** Pointer is between the disc rim and a little past the chips. */
function nearChipRing(
  graph: Graph,
  heldId: string | null,
  clientX: number,
  clientY: number,
  nodeDiameter: number,
): boolean {
  if (!heldId) return false;
  const held = positionOf(graph, heldId);
  if (!held) return false;
  let world: [number, number];
  try {
    world = graph.getCanvasByClient([clientX, clientY]) as [number, number];
  } catch {
    return false;
  }
  const dist = Math.hypot(world[0] - held.x, world[1] - held.y);
  const radius = nodeDiameter / 2;
  return dist > radius && dist < radius + BOND_LABEL_ALONG_PX + 28;
}

/** Edge ids that join two named discs. */
function linkingEdgeIds(graph: Graph, fromId: string, toId: string): string[] {
  if (!fromId || !toId || fromId === toId) return [];
  const ids: string[] = [];
  for (const edge of graph.getRelatedEdgesData(fromId)) {
    const other =
      String(edge.source) === fromId
        ? String(edge.target)
        : String(edge.source);
    if (other === toId) ids.push(String(edge.id));
  }
  return ids;
}

type DodgeTarget = {
  x: number;
  y: number;
  fanAngle?: number;
  fanAlong?: number;
  fanFromSource?: boolean;
  viaFrom?: Point;
  viaTo?: Point;
  /** Locked half-plane of the chord. Crossing kinks only. */
  side?: 1 | -1;
};
type Halo = { c: Point; r: number };
type FanWaypoint = {
  angle: number;
  along: number;
  fromSource: boolean;
  deflect: number;
};
/** Once a wrap picks a side, keep it — closest-point angle flips at the line. */
type KinkLock = { side: 1 | -1; deflect: number };

function fanChip(
  held: Point,
  radius: number,
  angle: number,
  along: number,
): Point {
  return {
    x: held.x + Math.cos(angle) * (radius + along),
    y: held.y + Math.sin(angle) * (radius + along),
  };
}

function wrapAngle(angle: number) {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

function chordSide(point: Point, a: Point, b: Point): 1 | -1 {
  const cross = (b.x - a.x) * (point.y - a.y) - (b.y - a.y) * (point.x - a.x);
  return cross >= 0 ? 1 : -1;
}

/**
 * Unit perpendicular of the chord pointing into the +1 half-plane.
 * The wrap sits on the opposite vector: from the disc toward that chord.
 */
function chordNormal(a: Point, b: Point): Point | null {
  const cx = b.x - a.x;
  const cy = b.y - a.y;
  const len = Math.hypot(cx, cy);
  if (!(len > 1)) return null;
  return { x: -cy / len, y: cx / len };
}

function lockedWrapAngle(s: Point, t: Point, side: 1 | -1): number | null {
  const n = chordNormal(s, t);
  if (!n) return null;
  return Math.atan2(-side * n.y, -side * n.x);
}

function nearestOccupied(
  angle: number,
  occupied: number[],
): { gap: number; near: number } {
  if (!occupied.length) return { gap: Number.POSITIVE_INFINITY, near: angle };
  let near = occupied[0];
  let gap = Math.abs(wrapAngle(angle - occupied[0]));
  for (let i = 1; i < occupied.length; i += 1) {
    const nextGap = Math.abs(wrapAngle(angle - occupied[i]));
    if (nextGap < gap) {
      gap = nextGap;
      near = occupied[i];
    }
  }
  return { gap, near };
}

/** Push an angle off the nearest claimed slot, then clamp to a local fan. */
function pushAngle(
  angle: number,
  occupied: number[],
  minDelta: number,
  maxDeflect: number,
): number {
  const { gap, near } = nearestOccupied(angle, occupied);
  if (gap >= minDelta) return angle;
  let side = wrapAngle(angle - near);
  if (Math.abs(side) < 1e-6) side = 1;
  else side = side > 0 ? 1 : -1;
  let delta = side * (minDelta - gap);
  delta = Math.max(-maxDeflect, Math.min(maxDeflect, delta));
  return angle + delta;
}

/**
 * Local angular spacing: keep circular order, push neighbours apart, then
 * clamp each spoke so a bundle fans in place rather than eating the circle.
 */
function spreadAngles(
  angles: number[],
  minDelta: number,
  maxDeflect: number,
): number[] {
  const count = angles.length;
  const result = angles.slice();
  if (count < 2) return result;
  const order = angles
    .map((angle, index) => ({ angle: wrapAngle(angle), index }))
    .sort((a, b) => a.angle - b.angle);
  const current = order.map((entry) => entry.angle);
  for (let iter = 0; iter < 12; iter += 1) {
    for (let i = 0; i < count; i += 1) {
      const next = (i + 1) % count;
      let gap = current[next] - current[i];
      if (next === 0) gap += Math.PI * 2;
      if (gap >= minDelta) continue;
      const need = (minDelta - gap) / 2;
      current[i] -= need;
      current[next] += need;
    }
    for (let i = 0; i < count; i += 1) {
      const original = order[i].angle;
      let delta = wrapAngle(current[i] - original);
      delta = Math.max(-maxDeflect, Math.min(maxDeflect, delta));
      current[i] = original + delta;
    }
  }
  for (let i = 0; i < count; i += 1) result[order[i].index] = current[i];
  return result;
}

function incidentFans(
  graph: Graph,
  heldId: string,
  nodeDiameter: number,
): Map<string, FanWaypoint> {
  const held = positionOf(graph, heldId);
  if (!held) return new Map();
  const radius = nodeDiameter / 2;
  const spokes: {
    id: string;
    angle: number;
    fromSource: boolean;
    along: number;
  }[] = [];
  for (const edge of graph.getRelatedEdgesData(heldId)) {
    const fromSource = String(edge.source) === heldId;
    const otherId = fromSource ? String(edge.target) : String(edge.source);
    const other = positionOf(graph, otherId);
    if (!other) continue;
    const dx = other.x - held.x;
    const dy = other.y - held.y;
    const span = Math.hypot(dx, dy);
    if (!(span > radius * 2 + 4)) continue;
    spokes.push({
      id: String(edge.id),
      angle: Math.atan2(dy, dx),
      fromSource,
      along: Math.min(BOND_LABEL_ALONG_PX, (span - radius * 2) * 0.45),
    });
  }
  if (!spokes.length) return new Map();
  const spread = spreadAngles(
    spokes.map((spoke) => spoke.angle),
    FAN_MIN_ARC,
    FAN_MAX_DEFLECT,
  );
  const out = new Map<string, FanWaypoint>();
  for (let i = 0; i < spokes.length; i += 1) {
    const spoke = spokes[i];
    const angle = spread[i];
    out.set(spoke.id, {
      angle,
      along: spoke.along,
      fromSource: spoke.fromSource,
      deflect: Math.abs(wrapAngle(angle - spoke.angle)),
    });
  }
  return out;
}

/** Disc-surface chord, matching the filament G6 actually draws. */
function filamentChord(
  graph: Graph,
  sourceId: string,
  targetId: string,
  radius: number,
): { s: Point; t: Point } | null {
  const a = positionOf(graph, sourceId);
  const b = positionOf(graph, targetId);
  if (!a || !b) return null;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  if (!(len > radius * 2 + 4)) return null;
  const ux = dx / len;
  const uy = dy / len;
  return {
    s: { x: a.x + ux * radius, y: a.y + uy * radius },
    t: { x: b.x - ux * radius, y: b.y - uy * radius },
  };
}

function closestPointOnSegment(
  point: Point,
  a: Point,
  b: Point,
): { point: Point; t: number; dist: number } {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared < 1e-8) {
    return {
      point: a,
      t: 0.5,
      dist: Math.hypot(point.x - a.x, point.y - a.y),
    };
  }
  const t = Math.max(
    0,
    Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared),
  );
  const closest = { x: a.x + t * dx, y: a.y + t * dy };
  return {
    point: closest,
    t,
    dist: Math.hypot(point.x - closest.x, point.y - closest.y),
  };
}

function chipHalo(
  held: Point,
  other: Point,
  radius: number,
  label: string,
  fontSize: number,
): Halo | null {
  const dx = other.x - held.x;
  const dy = other.y - held.y;
  const span = Math.hypot(dx, dy);
  if (!(span > 1)) return null;
  const ux = dx / span;
  const uy = dy / span;
  const sx = held.x + ux * radius;
  const sy = held.y + uy * radius;
  const tx = other.x - ux * radius;
  const ty = other.y - uy * radius;
  const filament = Math.hypot(tx - sx, ty - sy);
  if (!(filament > 1)) return null;
  const along = Math.min(BOND_LABEL_ALONG_PX, filament * 0.45);
  const halfW = Math.max(12, label.length * fontSize * 0.38 + 6);
  const halfH = fontSize * 0.7 + 6;
  return {
    c: {
      x: sx + ((tx - sx) / filament) * along,
      y: sy + ((ty - sy) / filament) * along,
    },
    r: Math.hypot(halfW, halfH) + CHIP_AIR,
  };
}

/**
 * Keep-out is the held disc and each named chip. Crossing filaments kink
 * around the disc on a locked side of the chord: the first frame picks
 * left or right; later frames keep that wrap. Using the closest-point
 * angle would flip the moment the centre crossed the line.
 */
function restKinks(
  graph: Graph,
  heldId: string,
  nodeDiameter: number,
  fontSize: number,
  fans: Map<string, FanWaypoint>,
  locks: Map<string, KinkLock>,
): Map<string, DodgeTarget> {
  const held = positionOf(graph, heldId);
  if (!held) return new Map();
  const radius = nodeDiameter / 2;
  const incident = new Set<string>();
  const occupied: number[] = [];
  const halos: Halo[] = [{ c: held, r: radius + DISC_AIR }];
  for (const edge of graph.getRelatedEdgesData(heldId)) {
    incident.add(String(edge.id));
    const fan = fans.get(String(edge.id));
    if (fan) {
      occupied.push(fan.angle);
      const label = String(edge.data?.label ?? "");
      const halfW = Math.max(12, label.length * fontSize * 0.38 + 6);
      const halfH = fontSize * 0.7 + 6;
      halos.push({
        c: fanChip(held, radius, fan.angle, fan.along),
        r: Math.hypot(halfW, halfH) + CHIP_AIR,
      });
      continue;
    }
    const otherId =
      String(edge.source) === heldId
        ? String(edge.target)
        : String(edge.source);
    const other = positionOf(graph, otherId);
    if (!other) continue;
    occupied.push(Math.atan2(other.y - held.y, other.x - held.x));
    const halo = chipHalo(
      held,
      other,
      radius,
      String(edge.data?.label ?? ""),
      fontSize,
    );
    if (halo) halos.push(halo);
  }

  const candidates: {
    id: string;
    penetration: number;
    from: Point;
    radius: number;
    angle: number;
    side: 1 | -1;
  }[] = [];
  for (const edge of graph.getEdgeData()) {
    const id = String(edge.id);
    if (incident.has(id) || isLit(edge)) continue;
    const chord = filamentChord(
      graph,
      String(edge.source),
      String(edge.target),
      radius,
    );
    if (!chord) continue;

    let penetration = 0;
    for (const halo of halos) {
      const hit = closestPointOnSegment(halo.c, chord.s, chord.t);
      if (hit.dist >= halo.r) continue;
      penetration = Math.max(penetration, halo.r - hit.dist);
    }
    if (penetration <= 0) continue;

    const toHeld = closestPointOnSegment(held, chord.s, chord.t);
    if (toHeld.t < 0.1 || toHeld.t > 0.9) continue;
    const lock = locks.get(id);
    const side = lock?.side ?? chordSide(held, chord.s, chord.t);
    const angle = lockedWrapAngle(chord.s, chord.t, side);
    if (angle == null) continue;
    candidates.push({
      id,
      penetration,
      from: toHeld.point,
      radius: Math.max(toHeld.dist, radius + DISC_AIR),
      angle,
      side,
    });
  }

  candidates.sort((a, b) => b.penetration - a.penetration);
  const chosen = candidates.slice(0, DODGE_MAX_EDGES);
  const out = new Map<string, DodgeTarget>();
  for (const candidate of chosen) {
    const lock = locks.get(candidate.id);
    const angle = lock
      ? candidate.angle + lock.deflect
      : pushAngle(
          candidate.angle,
          occupied,
          FAN_MIN_ARC,
          FAN_MAX_DEFLECT,
        );
    const deflect = wrapAngle(angle - candidate.angle);
    const radial = candidate.radius - Math.hypot(
      candidate.from.x - held.x,
      candidate.from.y - held.y,
    );
    if (!lock && Math.abs(deflect) < FAN_SKIP && radial < 2) continue;
    occupied.push(angle);
    if (!lock) locks.set(candidate.id, { side: candidate.side, deflect });
    out.set(candidate.id, {
      x: 0,
      y: 0,
      viaFrom: candidate.from,
      viaTo: {
        x: held.x + Math.cos(angle) * candidate.radius,
        y: held.y + Math.sin(angle) * candidate.radius,
      },
      side: candidate.side,
    });
  }
  return out;
}

function distanceToSegment(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
) {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared < 1e-8) return Math.hypot(px - ax, py - ay);
  const t = Math.max(
    0,
    Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared),
  );
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function closestPointRatio(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
) {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared < 1e-8) return 0.5;
  return Math.max(
    0,
    Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared),
  );
}

function lensFalloff(distance: number, radius: number) {
  if (distance >= radius) return 0;
  const t = 1 - distance / radius;
  return 0.5 - 0.5 * Math.cos(Math.PI * t);
}

/**
 * Do two data objects describe the same map — same nodes, same order?
 *
 * Positions are deliberately not compared. A layout that moved is a different
 * map, but so is one that kept every coordinate and swapped the graph out
 * underneath; the node roll is what identifies the thing being looked at, and
 * it is a comparison with no allocation, run once per update.
 */
function sameNodeIdentity(
  previous: GraphData | null | undefined,
  next: GraphData,
): boolean {
  const before = previous?.nodes;
  const after = next.nodes;
  if (!before || !after || before.length !== after.length) return false;
  for (let index = 0; index < before.length; index += 1) {
    if (before[index]?.id !== after[index]?.id) return false;
  }
  return true;
}

/**
 * The camera flight a graph currently has in the air, keyed by graph.
 *
 * A focus can be replaced before the last one has landed — search a node,
 * change your mind, search another — and two flights sharing one camera would
 * fight for it a frame at a time. The newer one cancels the older, which is
 * also what G6 does internally to its own viewport animations.
 */
const cameraFlights = new WeakMap<Graph, () => void>();

function cancelCameraFlight(graph: Graph) {
  const cancel = cameraFlights.get(graph);
  if (!cancel) return;
  cameraFlights.delete(graph);
  cancel();
}

/** Where the camera was looking, in canvas coordinates, and how close in. */
type CameraPose = { centre: [number, number]; zoom: number };

function readCamera(graph: Graph): CameraPose {
  const centre = graph.getViewportCenter();
  return { centre: [centre[0], centre[1]], zoom: graph.getZoom() };
}

/**
 * Put the camera somewhere, now, with no animation.
 *
 * Zoom first and then translate, measuring the translation against the scale
 * that is already applied: the same two steps a flight frame takes, for the
 * same reason. Predicting where a canvas point lands after a zoom means
 * duplicating G6's transform; asking it afterwards does not.
 */
function placeCamera(graph: Graph, pose: CameraPose) {
  void graph.zoomTo(pose.zoom, false).catch(() => {});
  if (graph.destroyed) return;
  const at = graph.getViewportByCanvas(pose.centre);
  const centre = graph.getCanvasCenter();
  void graph
    .translateBy([centre[0] - at[0], centre[1] - at[1]], false)
    .catch(() => {});
}

/**
 * Fly the camera to a canvas point and zoom, instead of cutting to it.
 *
 * Why by hand rather than `focusElement(ids, {duration})`: a focus is a *pan
 * and a zoom*, and G6 cannot animate both. Every viewport transform begins
 * with `cancelAnimation()`, so `focusElement` followed by `zoomTo` is not a
 * flight with two components — it is a flight interrupted by a second one, and
 * the pan is thrown away mid-air.
 *
 * So each frame sets the camera outright: zoom, then translate whatever canvas
 * point should be centred at this instant onto the centre of the view. Reading
 * the position back through `getViewportByCanvas` after the zoom is what keeps
 * the two composable — the translation is measured against the scale that is
 * already applied rather than predicted from it.
 *
 * Zoom is interpolated geometrically. Zoom is a ratio, so equal *steps* are
 * not equal changes: lerping 0.2 → 1.5 linearly spends most of the flight in
 * the last third of the journey and arrives like a slammed door.
 *
 * The caller lands the final state with the real thing (`focusElement` +
 * `zoomTo`), so where the camera comes to rest is exactly where it rested
 * before this function existed. Only the path there is new.
 */
async function flyCameraTo(
  graph: Graph,
  target: [number, number],
  targetZoom: number,
  plan: MotionPlan,
): Promise<void> {
  cancelCameraFlight(graph);

  const from = graph.getViewportCenter();
  const fromCanvas: [number, number] = [from[0], from[1]];
  const fromZoom = graph.getZoom();

  // Is there a journey at all? A focus that re-frames what is already framed
  // should not spend 320ms telling you nothing changed.
  const travelled = Math.hypot(
    (target[0] - fromCanvas[0]) * targetZoom,
    (target[1] - fromCanvas[1]) * targetZoom,
  );
  const zoomRatio = targetZoom / (fromZoom || targetZoom);
  if (travelled < 2 && Math.abs(Math.log(zoomRatio)) < 0.02) return;

  await new Promise<void>((resolve) => {
    let frame = 0;
    let cancelled = false;
    const started = performance.now();

    const cancel = () => {
      cancelled = true;
      if (frame) cancelAnimationFrame(frame);
      resolve();
    };
    cameraFlights.set(graph, cancel);

    const step = () => {
      frame = 0;
      if (cancelled || graph.destroyed) {
        resolve();
        return;
      }
      const elapsed = performance.now() - started;
      const progress = Math.min(1, elapsed / plan.durationMs);
      const eased = plan.easing.sample(progress);

      void graph.zoomTo(fromZoom * zoomRatio ** eased, false).catch(() => {});
      if (graph.destroyed) {
        resolve();
        return;
      }
      const want: [number, number] = [
        fromCanvas[0] + (target[0] - fromCanvas[0]) * eased,
        fromCanvas[1] + (target[1] - fromCanvas[1]) * eased,
      ];
      const at = graph.getViewportByCanvas(want);
      const centre = graph.getCanvasCenter();
      void graph
        .translateBy([centre[0] - at[0], centre[1] - at[1]], false)
        .catch(() => {});

      if (progress >= 1) {
        cameraFlights.delete(graph);
        resolve();
        return;
      }
      frame = requestAnimationFrame(step);
    };

    frame = requestAnimationFrame(step);
  });
}

async function frameElements(
  graph: Graph,
  ids: string[],
  /** Omitted for the first paint and for reduced motion: the camera cuts. */
  flight?: MotionPlan,
  /**
   * Where the camera was before the data change that led here.
   *
   * The graph's own `autoFit` runs on every data change with `animation:
   * false`, and focus is expressed *as* a data change — so by the time this
   * function is reached the camera has already been moved, and reading it here
   * gives the destination rather than the departure. That is why dropping a
   * focus used to cut: the fit had nowhere left to travel. It is also why an
   * inbound flight always began from the whole-map fit rather than from
   * wherever the operator had actually panned to.
   *
   * So the departure is captured before `setData` and handed down. Restoring
   * it costs no flicker as long as nothing has painted in between, which is
   * what keeps this on the near side of the first `await` after the draw.
   */
  from?: CameraPose,
) {
  const existing = ids.filter((id) => graph.getNodeData(id));
  // Letting go of a focus, or framing more of the map than a flight can
  // usefully describe. Both are one whole-map fit.
  if (!existing.length || existing.length > 40) {
    cancelCameraFlight(graph);
    if (flight && from) {
      // Fit instantly to learn where home *is* — `autoFit` has usually done
      // this already, but reading the camera is not the same as owning it, and
      // the >40 branch can be reached without a data change at all. Then put
      // the camera back where the operator left it and fly the distance.
      await graph.fitView(undefined, false);
      if (graph.destroyed) return;
      const home = readCamera(graph);
      placeCamera(graph, from);
      if (graph.destroyed) return;
      await flyCameraTo(graph, home.centre, home.zoom, flight);
      if (graph.destroyed) return;
    }
    await graph.fitView(undefined, false);
    return;
  }
  // Same restoration on the way in: without it every focus flight departs from
  // the whole-map fit `autoFit` just imposed, which is a journey the operator
  // did not take from a place they were not looking at.
  if (flight && from) placeCamera(graph, from);
  const bounds = existing.map((id) => graph.getElementRenderBounds(id));
  const minX = Math.min(...bounds.map((box) => box.min[0]));
  const minY = Math.min(...bounds.map((box) => box.min[1]));
  const maxX = Math.max(...bounds.map((box) => box.max[0]));
  const maxY = Math.max(...bounds.map((box) => box.max[1]));
  const [width, height] = graph.getSize();
  // 1.5 rather than 0.9. The ceiling is what stops a focused set from filling
  // the view it was framed into: asking for one node and its two neighbours got
  // the same distant camera as asking for forty, so the answer arrived at the
  // size of the thing you were trying to stop reading.
  const zoom = Math.max(
    0.15,
    Math.min(
      1.5,
      (width - 120) / Math.max(40, maxX - minX),
      (height - 120) / Math.max(40, maxY - minY),
    ),
  );
  if (flight) {
    await flyCameraTo(graph, [(minX + maxX) / 2, (minY + maxY) / 2], zoom, flight);
    if (graph.destroyed) return;
  } else {
    cancelCameraFlight(graph);
  }
  // The landing, and the whole of a cut. `focusElement` accounts for the
  // canvas padding the flight does not model, so this is also what stops a
  // 320ms approximation from being the last word on where the camera sits.
  await graph.focusElement(existing, { duration: 0 });
  if (!graph.destroyed) await graph.zoomTo(zoom, { duration: 0 });
}

/**
 * The approved Graph DNA without workbench controls or fixture assumptions.
 * Coordinates and semantic states are supplied by the product; this component
 * owns only rendering and interaction semantics.
 */
export function ProductGraphCanvas({
  data,
  mapKey = "",
  mode = "ambient",
  theme = "light",
  provisional = false,
  frameIds = [],
  selectedId: controlledSelectedId,
  followId = null,
  previewId = null,
  onSelect,
  onHover,
  onPreview,
  onJump,
  onNudgesChange,
  onRenderError,
  onSceneReady,
}: ProductGraphCanvasProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const onSelectRef = useRef(onSelect);
  const onHoverRef = useRef(onHover);
  const onPreviewRef = useRef(onPreview);
  const onJumpRef = useRef(onJump);
  const onNudgesChangeRef = useRef(onNudgesChange);
  const onRenderErrorRef = useRef(onRenderError);
  const onSceneReadyRef = useRef(onSceneReady);
  // Hand-moved nodes, and the undo/redo stacks over them.
  //
  // Deliberately *not* G6's `History` plugin, which records every data change
  // the graph sees. Most changes here are not the operator's doing — they are
  // the server's map arriving — and undoing one of those would show a graph
  // nobody asserted. G6's `beforeAddCommand` could filter them, but a drag also
  // emits many intermediate commands, and one undo per pixel is not an undo.
  // Recording the drag itself gives exactly one entry per gesture.
  const nudgesRef = useRef<Map<string, Point>>(new Map());
  const undoRef = useRef<Nudge[]>([]);
  const redoRef = useRef<Nudge[]>([]);
  // Held in a ref because the publisher closes over the mounted graph, and the
  // data effect — which has to clear the stacks when new coordinates arrive —
  // runs in a different scope.
  const publishNudgesRef = useRef<() => void>(() => {});
  const hoverActiveRef = useRef<HoverBundle>(emptyHoverBundle());
  const pointerHoverRef = useRef<HoverBundle>(emptyHoverBundle());
  const selectionHoverRef = useRef<HoverBundle>(emptyHoverBundle());
  const commitHoverRef = useRef<(next: HoverBundle) => void>(() => {});
  const previewWidthRef = useRef<(ids: Iterable<string>) => void>(() => {});
  const commitDodgeRef = useRef<(heldId: string | null) => void>(() => {});
  const previewIdRef = useRef(previewId);
  const dragMotionRef = useRef<"engage" | "release">("engage");
  const renderedDataRef = useRef<GraphData | null>(null);
  const renderedMapKeyRef = useRef("");
  const renderedNodeOptionsRef = useRef<unknown>(null);
  const renderedEdgeOptionsRef = useRef<unknown>(null);
  /** Content hash for DNA-driven paint, not callback identity. */
  const renderedStyleKeyRef = useRef("");
  const drawEpochRef = useRef(0);
  const renderedFrameKeyRef = useRef("");
  /**
   * Whether node names currently fit on their discs.
   *
   * Read inside `labelText` rather than baked into the style options. Starts
   * shown so the first paint of an ordinary graph is never label-less while
   * waiting for a zoom event that may not come; the fit handler corrects it
   * before that paint is visible on a large one.
   */
  const labelsShownRef = useRef(true);
  /** Disc and type metrics for the zoom check, without tearing the graph
   *  down when the DNA workbench moves a slider. */
  const labelSpecRef = useRef({
    disc: defaultGeometry.nodeDiameter,
    lineHeight: defaultGeometry.labelLineHeight,
    maxLines: defaultGeometry.labelMaxLines,
  });
  const largeGraphRef = useRef(
    (data.edges?.length ?? 0) >= VIEWPORT_EDGE_SHED_THRESHOLD,
  );
  largeGraphRef.current =
    (data.edges?.length ?? 0) >= VIEWPORT_EDGE_SHED_THRESHOLD;
  const [ready, setReady] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(
    controlledSelectedId ?? null,
  );
  const selectedIdRef = useRef<string | null>(selectedId);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  onSelectRef.current = onSelect;
  onHoverRef.current = onHover;
  onPreviewRef.current = onPreview;
  onJumpRef.current = onJump;
  onNudgesChangeRef.current = onNudgesChange;
  onRenderErrorRef.current = onRenderError;
  onSceneReadyRef.current = onSceneReady;
  selectedIdRef.current = selectedId;
  previewIdRef.current = previewId;

  const dnaRuntime = useGraphDnaRuntime();
  const geometry = useMemo(() => {
    if (!dnaRuntime) return defaultGeometry;
    const p = dnaRuntime.params;
    return {
      ...defaultGeometry,
      nodeDiameter: p.nodeDiameter,
      nodeLine: p.nodeLine,
      labelSize: p.labelSize,
      labelMaxWidth: p.labelMaxWidth,
      labelBaselineNudge: p.labelBaselineNudge,
      labelLineHeight: p.labelLineHeight,
      labelMaxLines: p.labelMaxLines,
      nodeFillOpacity: p.nodeFillOpacity,
      nodeLabelOpacity: p.nodeLabelOpacity,
      edgeWidth: p.edgeWidth,
      edgeOpacity: p.edgeOpacity,
      edgeLabelSize: p.edgeLabelSize,
      edgeLabelOpacity: p.edgeLabelOpacity,
      spokeRestOpacity: p.spokeRestOpacity,
      dottedGap: p.dottedGap,
    };
  }, [dnaRuntime]);
  // Kept current for the zoom check, which runs inside the render effect and
  // must not re-subscribe when the DNA workbench moves a slider.
  labelSpecRef.current = {
    disc: geometry.nodeDiameter,
    lineHeight: geometry.labelLineHeight,
    maxLines: geometry.labelMaxLines,
  };
  const interaction = useMemo(() => {
    if (!dnaRuntime) return defaultInteraction;
    const p = dnaRuntime.params;
    return {
      ...defaultInteraction,
      selectionMotion: p.selectionMotion,
      hoverRadius: p.hoverRadius,
      hoverResponse: p.hoverResponse,
      gravityStrength: p.gravityStrength,
      gravityTravel: p.gravityTravel,
      absorbPull: p.absorbPull,
      gripScale: p.gripScale,
      dragNodeRelief: p.dragNodeRelief,
      dragEdgeLoad: p.dragEdgeLoad,
      dragEdgePresence: p.dragEdgePresence,
      selectionSpeed: p.selectionSpeed,
      selectionClearance: p.selectionClearance,
      selectionDotGap: p.selectionDotGap,
      selectionLine: p.selectionLine,
    };
  }, [dnaRuntime]);
  /* The ring animates; the canvas does not. Two different costs, two gates. */
  const selectionMotion = interaction.selectionMotion !== false;

  const motion = useMemo(
    () =>
      createMotionPlans({
        gravity: interaction.gravityStrength,
        travel: interaction.gravityTravel,
        absorbPull: interaction.absorbPull,
      }),
    [interaction],
  );
  const labelFontFamily =
    dnaRuntime?.labelFontFamily ?? FONT_SANS_FAMILY;
  const labelFontWeight = dnaRuntime?.labelFontWeight ?? 400;

  const palette = useMemo(() => {
    // The workbench authors the *shipping* look. Provisional is a state a
    // graph is in, not a second look to tune, so it is not a knob and it wins
    // over the runtime override rather than being merged with it.
    if (provisional) return resolveGraphDnaProvisional(theme);
    if (!dnaRuntime) return resolveGraphDna(theme);
    return Object.fromEntries(
      Object.entries(dnaRuntime.params[theme]).map(([key, value]) => [
        key,
        radixValue(value),
      ]),
    ) as ReturnType<typeof resolveGraphDna>;
  }, [dnaRuntime, theme, provisional]);
  const focus = useMemo(() => {
    if (!dnaRuntime) return resolveGraphDnaFocus();
    return Object.fromEntries(
      Object.entries(dnaRuntime.params.focus).map(([key, value]) => [
        key,
        radixValue(value),
      ]),
    ) as ReturnType<typeof resolveGraphDnaFocus>;
  }, [dnaRuntime]);
  /**
   * Every state that is not the ambient map inverts the field.
   *
   * This is the Ledger focus language — the one authored on the Graph DNA
   * workbench and shown on its Ledger focus specimen — and `focus` is a member
   * of it, not an exception to it. It briefly was an exception: focus kept the
   * pale field and merely attenuated everything it had not lit, on the argument
   * that focus shows the same graph you were already reading. That produced a
   * *second* focus vocabulary for the same word, so a subject arriving from
   * Review and the identical subject arriving from Ask were
   * drawn in two different languages, and only one of them was the approved
   * one. One question, one answer: a lit subject on an inverted field.
   */
  const inverted = mode !== "ambient";
  const visualRef = useRef({
    focus,
    inverted,
    palette,
    edgeOpacity: geometry.edgeOpacity,
    edgeWidth: geometry.edgeWidth,
    edgeLabelOpacity: geometry.edgeLabelOpacity,
    edgeLabelSize: geometry.edgeLabelSize,
    nodeDiameter: geometry.nodeDiameter,
    spokeRestOpacity: geometry.spokeRestOpacity,
    dottedGap: geometry.dottedGap,
  });
  visualRef.current = {
    focus,
    inverted,
    palette,
    edgeOpacity: geometry.edgeOpacity,
    edgeWidth: geometry.edgeWidth,
    edgeLabelOpacity: geometry.edgeLabelOpacity,
    edgeLabelSize: geometry.edgeLabelSize,
    nodeDiameter: geometry.nodeDiameter,
    spokeRestOpacity: geometry.spokeRestOpacity,
    dottedGap: geometry.dottedGap,
  };
  const motionRef = useRef(motion);
  motionRef.current = motion;
  const interactionRef = useRef(interaction);
  interactionRef.current = interaction;

  /**
   * The camera's flight plan, or nothing when the camera should cut.
   *
   * `emit`, not `settle`. Settle is an under-damped spring and the doctrine
   * reserves it for released manipulation — measured on a real focus it put
   * the zoom 4% past its target and spent another 200ms coming back, which on
   * a map reads as the camera losing its footing. Emit is the escape impulse
   * gravity spends exactly at the destination: leaves at once, arrives at
   * rest, never passes the thing it was sent to.
   *
   * Reduced motion is asked here rather than inside the flight so the answer
   * is a *plan or no plan*: a 1ms flight is still a flight, and would still
   * put a frame of half-arrived camera on screen. Someone who has asked the
   * system for no motion gets the cut this function used to be.
   */
  const flightRef = useRef<MotionPlan | null>(null);
  flightRef.current = window.matchMedia("(prefers-reduced-motion: reduce)")
    .matches
    ? null
    : motion.emit;

  const nodeOptions = useCallback(() => {
    const nodeLineWidth = (datum: NodeData) =>
      inverted && diffOf(datum) !== "unchanged"
        ? geometry.nodeLine + 0.5
        : geometry.nodeLine;
    const dragMotion = dragMotionRef.current;
    return {
      type: "circle",
      style: {
        size: geometry.nodeDiameter,
        fill: (datum: NodeData) => {
          if (!inverted) return palette.node;
          const diff = diffOf(datum);
          if (diff === "added") return focus.lit;
          if (diff === "removed") return focus.field;
          return isLit(datum) ? focus.lit : focus.dimNode;
        },
        stroke: (datum: NodeData) => {
          if (!inverted) return palette.node;
          return diffOf(datum) !== "unchanged" || isLit(datum)
            ? focus.lit
            : focus.dimNode;
        },
        lineWidth: nodeLineWidth,
        lineDash: (datum: NodeData) =>
          inverted && diffOf(datum) === "removed"
            ? [0, geometry.dottedGap]
            : [],
        lineCap: "round" as const,
        halo: false,
        badge: false,
        // Withheld, not shrunk, when the disc cannot hold readable type — see
        // `nodeLabelsVisible`. Returning "" rather than setting opacity so the
        // renderer skips text shaping entirely: on a 2000-node map that is
        // 2000 strings it never has to lay out, which makes the first paint
        // cheaper rather than dearer.
        labelText: (datum: NodeData) =>
          labelsShownRef.current ? String(datum.data?.label ?? "") : "",
        labelFill: (datum: NodeData) => {
          if (!inverted) return palette.nodeLabel;
          const diff = diffOf(datum);
          if (diff === "added" || isLit(datum)) return focus.litLabel;
          if (diff === "removed" || diff === "touched") return focus.lit;
          return focus.dimLabel;
        },
        labelFontFamily,
        labelFontSize: geometry.labelSize,
        labelFontWeight: labelFontWeight as 400 | 500 | 600 | 700 | 800,
        labelLineHeight: geometry.labelSize * geometry.labelLineHeight,
        labelPlacement: "center" as const,
        // Optical, not geometric. Text centred on the circle's midline reads
        // high, because the mass a reader sees is cap-height and the box the
        // renderer centres includes the descender space below it.
        //
        // Must not ship an identity `labelTransform`: G6 places the label with
        // `transform: [['translate', x, y + labelOffsetY]]`, then merges the
        // rest of the label style on top. A second transform list *replaces*
        // that translate, so baseline nudge (and placement) never land.
        labelOffsetY: geometry.labelBaselineNudge,
        labelWordWrap: true,
        labelMaxWidth:
          geometry.nodeDiameter * (geometry.labelMaxWidth / 100),
        labelMaxLines: geometry.labelMaxLines,
        labelTextOverflow: "ellipsis",
        // Whether a node is part of the subject is said in ink (`lit` against
        // `dimNode`), so opacity is left to say only how present node matter is
        // on this map at all.
        opacity: geometry.nodeFillOpacity,
        labelOpacity: geometry.nodeLabelOpacity,
        cursor: "grab" as const,
      },
      state: {
        selected: { halo: false, haloStrokeOpacity: 0 },
        active: { halo: false, haloStrokeOpacity: 0 },
        dragLoad: {
          lineWidth: (datum: NodeData) =>
            Math.max(0.35, nodeLineWidth(datum) - interaction.dragNodeRelief),
        },
      },
      animation: PRODUCT_GRAPH_MOTION_ENABLED
        ? {
            enter: false as const,
            update: false as const,
            exit: false as const,
            show: false as const,
            hide: false as const,
            translate: false as const,
            state: [
              g6StateMotion(
                dragMotion === "engage" ? motion.hold : motion.settle,
                { fields: ["lineWidth"] },
              ),
            ],
          }
        : (false as const),
    };
  }, [focus, geometry, interaction, inverted, labelFontFamily, labelFontWeight, motion, palette]);

  const edgeOptions = useCallback(() => {
    // A named edge names itself. That is most of the value of asking to see a
    // node — "and what it touches, with the relations spelled out" — so it
    // survives focus no longer inverting the field. Hover and selection use
    // the same paint; they must not invent a second chip.
    const named = (datum: EdgeData) => inverted && isLit(datum);
    const look: EdgeLook = {
      inverted,
      palette,
      focus,
      edgeWidth: geometry.edgeWidth,
      edgeOpacity: geometry.edgeOpacity,
      edgeLabelOpacity: geometry.edgeLabelOpacity,
      spokeRestOpacity: geometry.spokeRestOpacity,
    };
    const dragMotion = dragMotionRef.current;
    return {
      type: AMBIENT_LINKAGE_EDGE,
      style: {
        edgeKind: (datum: EdgeData) => linkageEdgeKind(datum),
        // The stroke is not a target — discs stay reachable through
        // filaments. The edge *element* stays interactive so the picker can
        // walk into a named chip; AmbientLinkageEdge forces the key path to
        // `none`. Chip hover also hit-tests in canvas space, because a parent
        // `none` used to drop the label before the picker ever saw it.
        labelPointerEvents: "auto" as const,
        labelCursor: "pointer" as const,
        stroke: (datum: EdgeData) => edgePaint(datum, look, named(datum)).stroke,
        lineWidth: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).lineWidth,
        strokeOpacity: 1,
        opacity: (datum: EdgeData) => edgePaint(datum, look, named(datum)).opacity,
        lineDash: (datum: EdgeData) =>
          inverted && diffOf(datum) === "removed"
            ? [0, geometry.dottedGap]
            : [],
        lineCap: "round" as const,
        lineJoin: "round" as const,
        endArrow: (datum: EdgeData) => edgePaint(datum, look, named(datum)).endArrow,
        endArrowType: "triangle" as const,
        endArrowSize: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).endArrowSize,
        endArrowFill: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).endArrowFill,
        endArrowFillOpacity: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).endArrowFillOpacity,
        endArrowStrokeOpacity: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).endArrowStrokeOpacity,
        endArrowOffset: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).endArrowOffset,
        label: named,
        labelText: (datum: EdgeData) =>
          named(datum) ? String(datum.data?.label ?? "") : "",
        labelFontFamily: FONT_SANS_FAMILY,
        labelFontSize: geometry.edgeLabelSize,
        labelFill: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).labelFill,
        labelBackground: named,
        labelBackgroundFill: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).labelBackgroundFill,
        labelBackgroundOpacity: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).labelBackgroundOpacity,
        labelBackgroundLineWidth: 0,
        labelOpacity: (datum: EdgeData) =>
          edgePaint(datum, look, named(datum)).labelOpacity,
        labelPadding: [2, 3] as [number, number],
        labelAutoRotate: false,
        labelPlacement: 0.5,
        increasedLineWidthForHitTesting: 20,
      },
      state: {
        selected: { halo: false, haloStrokeOpacity: 0 },
        active: { halo: false, haloStrokeOpacity: 0 },
        dragLoad: {
          lineWidth: (datum: EdgeData) =>
            edgePaint(datum, look, named(datum)).lineWidth +
            interaction.dragEdgeLoad,
          opacity: (datum: EdgeData) =>
            Math.min(
              1,
              edgePaint(datum, look, named(datum)).opacity +
                interaction.dragEdgePresence,
            ),
        },
      },
      animation: PRODUCT_GRAPH_MOTION_ENABLED
        ? {
            enter: false as const,
            update: false as const,
            exit: false as const,
            show: false as const,
            hide: false as const,
            translate: false as const,
            state: [
              {
                fields: ["lineWidth", "opacity"],
                duration:
                  dragMotion === "engage"
                    ? MOTION_DURATION_MS.hold
                    : motion.settle.durationMs,
                easing:
                  dragMotion === "engage"
                    ? MOTION_SPINE.hold.g6
                    : motion.settle.easing.g6,
              },
            ],
          }
        : (false as const),
    };
  }, [focus, geometry, interaction, inverted, motion, palette]);

  // Always call the *current* factories from lifetime handlers (drag, etc.);
  // mount effect closes once, so it must not pin the DNA snapshot from first paint.
  const nodeOptionsRef = useRef(nodeOptions);
  const edgeOptionsRef = useRef(edgeOptions);
  nodeOptionsRef.current = nodeOptions;
  edgeOptionsRef.current = edgeOptions;

  /**
   * Value-level key for what the graph must paint. Callback identity alone is a
   * weak contract: a deps hole or memoised factory can leave knobs looking live
   * in the workbench while G6 still holds the previous mapper.
   */
  const styleKey = useMemo(
    () =>
      [
        theme,
        mode,
        inverted ? "1" : "0",
        labelFontFamily,
        String(labelFontWeight),
        JSON.stringify(geometry),
        JSON.stringify({
          dragNodeRelief: interaction.dragNodeRelief,
          dragEdgeLoad: interaction.dragEdgeLoad,
          dragEdgePresence: interaction.dragEdgePresence,
        }),
        JSON.stringify(palette),
        JSON.stringify(focus),
      ].join("|"),
    [
      focus,
      geometry,
      interaction.dragEdgeLoad,
      interaction.dragEdgePresence,
      interaction.dragNodeRelief,
      inverted,
      labelFontFamily,
      labelFontWeight,
      mode,
      palette,
      theme,
    ],
  );

  useEffect(() => {
    const container = stageRef.current;
    if (!container) return;
    ensureAmbientLinkageEdgeRegistered();
    setReady(false);
    onSceneReadyRef.current?.(false);
    hoverActiveRef.current = emptyHoverBundle();
    pointerHoverRef.current = emptyHoverBundle();
    selectionHoverRef.current = emptyHoverBundle();

    const graph = new Graph({
      container,
      data,
      // Transparent on purpose. G6's `setOptions({ background })` stores the
      // colour but never pushes it to the clear colour (updateCanvas only
      // handles renderer/cursor/size), so an opaque field painted at mount
      // stuck through every theme and focus flip. The live field is the CSS
      // `--matter-canvas` inherited from the shell — stamped inline here it
      // beat the shell's token transition and the disc slammed while chrome
      // tweened. The canvas clears to transparent so that token shows through.
      background: "transparent",
      animation: PRODUCT_GRAPH_MOTION_ENABLED,
      autoFit: {
        type: "view",
        options: { when: "always", direction: "both" },
        animation: false,
      },
      padding: [68, 86, 70, 86],
      node: nodeOptions(),
      edge: edgeOptions() as never,
      behaviors: [
        "drag-canvas",
        // Wheel and trackpad. Bare `"zoom-canvas"` is wheel-only, which is why
        // the map could be panned by touch but never pinched.
        "zoom-canvas",
        {
          // Pinch, as a second instance rather than an option on the first.
          //
          // G6's `zoom-canvas` picks *one* path: `bindEvents` checks whether
          // `trigger` contains PINCH and binds pinch **or** wheel, never both.
          // So a single behaviour cannot serve a laptop and a tablet, and the
          // default drops the tablet. Two instances, each bound to its own
          // gesture, is the only way to have the map answer to both.
          //
          // It is registered and then disabled, which reads like a mistake and
          // is the point. Two separate jobs are hiding in this one behaviour:
          //
          //  - *Noticing* a pinch. `PinchHandler` is a singleton that only
          //    exists while something binds `pinch`, and `drag-canvas` reads
          //    its static `isPinching` to know not to pan while two fingers
          //    are down. Unregister this and the map slides away underneath a
          //    zoom. That job is G6's and it does it well.
          //
          //  - Deciding what a pinch *means*. That job it does badly, and the
          //    product now does it instead — see `usePinchZoom` below for the
          //    measured reason. `enable` is only consulted inside `zoom()`, so
          //    a false here silences the zoom and leaves the noticing intact.
          type: "zoom-canvas",
          key: "zoom-canvas-pinch",
          trigger: ["pinch"] as unknown as string[],
          enable: () => false,
        },
        {
          type: "drag-element",
          // Product nodes are not combo containers. G6's default `move`
          // effect refreshes combo data on every pointer event, which is pure
          // bookkeeping here and makes the held object trail the pointer.
          dropEffect: "none",
          // Hold is a direct constraint. Product motion belongs to engage and
          // release states, never between the pointer and the dragged node.
          animation: false,
        },
        {
          type: "optimize-viewport-transform",
          // Above the detail budget, pan/zoom keeps nodes but temporarily sheds
          // filaments. Regional LOD will eventually replace this concession
          // with authored mass fields rather than asking the renderer to move
          // every detailed edge while the viewport itself is moving.
          enable: () => largeGraphRef.current,
          debounce: 80,
        },
      ],
    });
    graphRef.current = graph;
    renderedDataRef.current = data;
    renderedMapKeyRef.current = mapKey;
    renderedNodeOptionsRef.current = nodeOptions;
    renderedEdgeOptionsRef.current = edgeOptions;
    renderedStyleKeyRef.current = styleKey;
    renderedFrameKeyRef.current = frameIds.join("\u0000");
    // Panel drags reflow the CSS grid every pointermove (and fire this
    // observer each frame). G6 setSize is expensive on large graphs — hold
    // the canvas size until html.is-panel-resizing clears, then apply once.
    let resizeFrame = 0;
    let pendingSize: { width: number; height: number } | null = null;
    const applyPendingSize = () => {
      if (resizeFrame) cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = 0;
        const next = pendingSize;
        pendingSize = null;
        if (!next || graph.destroyed) return;
        graph.setSize(next.width, next.height);
      });
    };
    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry || graph.destroyed) return;
      const width = Math.round(entry.contentRect.width);
      const height = Math.round(entry.contentRect.height);
      if (width < 1 || height < 1) return;
      pendingSize = { width, height };
      if (
        document.documentElement.classList.contains("is-panel-resizing")
      ) {
        return;
      }
      applyPendingSize();
    });
    resizeObserver.observe(container);

    const panelResizeClassObserver = new MutationObserver(() => {
      if (
        document.documentElement.classList.contains("is-panel-resizing") ||
        !pendingSize
      ) {
        return;
      }
      applyPendingSize();
    });
    panelResizeClassObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    let leaveTimer = 0;
    let hoverFrame = 0;
    let pendingHover: HoverBundle | null = null;
    let suppressedSelection: { id: string; until: number } | null = null;
    let dragLoadIds = new Set<string>();
    let nodeDragActive = false;
    let dragOrigin: { id: string; at: Point | null } | null = null;
    let pointerNodeId: string | null = null;
    let absorbCanvasClick = false;
    let ignoreCanvasUntil = 0;
    let chipHover: { edgeId: string; otherId: string } | null = null;
    let chipPointer: { otherId: string; x: number; y: number } | null = null;
    let previewFrame = 0;
    const hoverPaint = new Map<
      string,
      { active: boolean; style: Record<string, unknown> }
    >();
    const previewAmount = new Map<string, number>();
    const previewAnims = new Map<
      string,
      { from: number; to: number; started: number; plan: MotionPlan }
    >();
    const previewHeld = new Set<string>();
    const previewPainted = new Set<string>();

    const reducedPreview = () =>
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const applyPreviewDash = () => {
      if (graph.destroyed) return;
      const ids = new Set([
        ...previewAmount.keys(),
        ...previewAnims.keys(),
        ...previewHeld,
        ...previewPainted,
      ]);
      if (chipHover) ids.add(chipHover.edgeId);
      if (!ids.size) return;
      const visual = visualRef.current;
      const gap = visual.dottedGap;
      const nextPainted = new Set<string>();
      const patches = [...ids].flatMap((id) => {
        const edge = graph.getEdgeData(id);
        if (!edge) return [];
        const amount = previewAmount.get(id) ?? 0;
        const held = hoverPaint.get(id);
        const named =
          Boolean(held?.active) ||
          (visual.inverted && isLit(edge));
        const paint = held?.style
          ? { ...held.style }
          : { ...edgePaint(edge, visual, named) };
        if (amount < 0.02 && !held) {
          return [{ id, active: false, style: {} }];
        }
        if (amount >= 0.02) nextPainted.add(id);
        return [
          {
            id,
            active: Boolean(held?.active) || amount >= 0.02 || named,
            style: {
              ...paint,
              lineDash: previewLineDash(amount, gap),
            },
          },
        ];
      });
      previewPainted.clear();
      for (const id of nextPainted) previewPainted.add(id);
      updateAmbientEdgeDisplay(graph, patches);
    };

    const tickPreview = (now: number) => {
      previewFrame = 0;
      let running = false;
      for (const [id, anim] of previewAnims) {
        const u = anim.plan.sample(now - anim.started);
        const value = anim.from + (anim.to - anim.from) * u;
        if (now - anim.started >= anim.plan.durationMs) {
          previewAmount.set(id, anim.to);
          previewAnims.delete(id);
          if (anim.to < 0.02) previewAmount.delete(id);
        } else {
          previewAmount.set(id, value);
          running = true;
        }
      }
      applyPreviewDash();
      if (running && !graph.destroyed) {
        previewFrame = requestAnimationFrame(tickPreview);
      }
    };

    const aimPreview = (id: string, to: number) => {
      const from = previewAmount.get(id) ?? 0;
      if (Math.abs(from - to) < 0.02 && !previewAnims.has(id)) {
        previewAmount.set(id, to);
        if (to < 0.02) previewAmount.delete(id);
        return;
      }
      if (reducedPreview()) {
        previewAnims.delete(id);
        if (to < 0.02) previewAmount.delete(id);
        else previewAmount.set(id, to);
        return;
      }
      previewAnims.set(id, {
        from,
        to,
        started: performance.now(),
        plan: to > from ? PREVIEW_ON : PREVIEW_OFF,
      });
    };

    previewWidthRef.current = (ids) => {
      const next = new Set(ids);
      for (const id of next) {
        previewHeld.add(id);
        aimPreview(id, 1);
      }
      for (const id of [...previewHeld]) {
        if (!next.has(id)) {
          previewHeld.delete(id);
          aimPreview(id, 0);
        }
      }
      if (reducedPreview()) {
        applyPreviewDash();
        return;
      }
      if (!previewFrame && previewAnims.size) {
        previewFrame = requestAnimationFrame(tickPreview);
      }
    };

    let dodgeFrame = 0;
    let dodgeDragFrame = 0;
    const dodgeAmount = new Map<string, number>();
    const dodgeAnims = new Map<
      string,
      { from: number; to: number; started: number; plan: MotionPlan }
    >();
    const dodgeHeld = new Set<string>();
    const dodgeTarget = new Map<string, DodgeTarget>();

    const applyDodge = () => {
      if (graph.destroyed) return;
      const ids = new Set([
        ...dodgeAmount.keys(),
        ...dodgeAnims.keys(),
        ...dodgeHeld,
        ...dodgeTarget.keys(),
      ]);
      if (!ids.size) return;
      const patches = [...ids].map((id) => {
        const amount = dodgeAmount.get(id) ?? 0;
        const target = dodgeTarget.get(id) ?? { x: 0, y: 0 };
        if (amount < 0.02 && !dodgeHeld.has(id)) {
          dodgeAmount.delete(id);
          dodgeTarget.delete(id);
        }
        return {
          id,
          x: target.x,
          y: target.y,
          amount,
          fanAngle: target.fanAngle,
          fanAlong: target.fanAlong,
          fanFromSource: target.fanFromSource,
          viaFromX: target.viaFrom?.x,
          viaFromY: target.viaFrom?.y,
          viaToX: target.viaTo?.x,
          viaToY: target.viaTo?.y,
        };
      });
      updateAmbientEdgeDodge(graph, patches);
    };

    const snapDodgeOff = () => {
      if (dodgeFrame) {
        cancelAnimationFrame(dodgeFrame);
        dodgeFrame = 0;
      }
      dodgeAnims.clear();
      dodgeHeld.clear();
      dodgeAmount.clear();
      dodgeTarget.clear();
      clearAmbientEdgeDodge(graph);
    };

    const tickDodge = (now: number) => {
      dodgeFrame = 0;
      let running = false;
      for (const [id, anim] of dodgeAnims) {
        const u = anim.plan.sample(now - anim.started);
        const value = anim.from + (anim.to - anim.from) * u;
        if (now - anim.started >= anim.plan.durationMs) {
          dodgeAmount.set(id, anim.to);
          dodgeAnims.delete(id);
          if (anim.to < 0.02) dodgeAmount.delete(id);
        } else {
          dodgeAmount.set(id, value);
          running = true;
        }
      }
      applyDodge();
      if (running && !graph.destroyed) {
        dodgeFrame = requestAnimationFrame(tickDodge);
      }
    };

    const aimDodge = (id: string, to: number) => {
      const from = dodgeAmount.get(id) ?? 0;
      if (Math.abs(from - to) < 0.02 && !dodgeAnims.has(id)) {
        dodgeAmount.set(id, to);
        if (to < 0.02) dodgeAmount.delete(id);
        return;
      }
      if (reducedPreview()) {
        dodgeAnims.delete(id);
        if (to < 0.02) dodgeAmount.delete(id);
        else dodgeAmount.set(id, to);
        return;
      }
      dodgeAnims.set(id, {
        from,
        to,
        started: performance.now(),
        plan: to > from ? DODGE_ON : DODGE_OFF,
      });
    };

    const kinkSideLock = new Map<string, KinkLock>();
    let kinkLockHeld: string | null = null;

    const commitDodge = (heldId: string | null) => {
      if (graph.destroyed) return;
      // Wraps are a rest pose. A moving disc would re-solve them every
      // frame; kill them outright until the pointer lets go.
      if (nodeDragActive) {
        snapDodgeOff();
        return;
      }
      if (heldId !== kinkLockHeld) {
        kinkSideLock.clear();
        kinkLockHeld = heldId;
      }
      const next = new Map<string, DodgeTarget>();
      let kinks = new Map<string, DodgeTarget>();
      if (heldId && graph.getNodeData(heldId)) {
        const fans = incidentFans(graph, heldId, visualRef.current.nodeDiameter);
        kinks = restKinks(
          graph,
          heldId,
          visualRef.current.nodeDiameter,
          visualRef.current.edgeLabelSize,
          fans,
          kinkSideLock,
        );
        for (const [id, fan] of fans) {
          if (fan.deflect < FAN_SKIP) continue;
          next.set(id, {
            x: 0,
            y: 0,
            fanAngle: fan.angle,
            fanAlong: fan.along,
            fanFromSource: fan.fromSource,
          });
        }
        for (const [id, kink] of kinks) next.set(id, kink);
      }
      dodgeHeld.clear();
      for (const [id, target] of next) {
        dodgeHeld.add(id);
        dodgeTarget.set(id, target);
        aimDodge(id, 1);
      }
      for (const id of [...dodgeTarget.keys()]) {
        if (!next.has(id)) aimDodge(id, 0);
      }
      for (const id of [...kinkSideLock.keys()]) {
        if (kinks.has(id)) continue;
        if ((dodgeAmount.get(id) ?? 0) > 0.02 || dodgeAnims.has(id)) continue;
        kinkSideLock.delete(id);
      }
      applyDodge();
      if (reducedPreview()) return;
      if (!dodgeFrame && dodgeAnims.size) {
        dodgeFrame = requestAnimationFrame(tickDodge);
      }
    };
    commitDodgeRef.current = commitDodge;

    // What the parent was last told. Republishing an identical state is not
    // free: the parent stores it, so an unchanged publish is still a re-render,
    // and a re-render that reaches back into this effect is a loop. Only a real
    // change in what the operator can *do* is worth waking anyone for.
    let publishedSignature = "";

    const publishNudges: () => void = () => {
      const signature = [
        nudgesRef.current.size,
        undoRef.current.length > 0,
        redoRef.current.length > 0,
      ].join("/");
      if (signature === publishedSignature) return;
      publishedSignature = signature;
      onNudgesChangeRef.current?.({
        count: nudgesRef.current.size,
        canUndo: undoRef.current.length > 0,
        canRedo: redoRef.current.length > 0,
        undo: () => {
          const entry = undoRef.current.pop();
          if (!entry) return;
          moveTo(graph, entry.id, entry.from);
          redoRef.current.push(entry);
          // Back at its layout position, a node is no longer moved by hand —
          // otherwise "reset" would stay lit with nothing left to reset.
          const home = nudgesRef.current.get(entry.id);
          if (home && !moved(home, entry.from)) nudgesRef.current.delete(entry.id);
          publishNudges();
          commitDodgeRef.current(selectedIdRef.current);
        },
        redo: () => {
          const entry = redoRef.current.pop();
          if (!entry) return;
          moveTo(graph, entry.id, entry.to);
          undoRef.current.push(entry);
          if (!nudgesRef.current.has(entry.id)) {
            nudgesRef.current.set(entry.id, entry.from);
          }
          publishNudges();
          commitDodgeRef.current(selectedIdRef.current);
        },
        reset: () => {
          for (const [id, home] of nudgesRef.current) moveTo(graph, id, home);
          nudgesRef.current.clear();
          undoRef.current = [];
          redoRef.current = [];
          publishNudges();
          commitDodgeRef.current(selectedIdRef.current);
        },
      });
    };

    const setDragLoad = (
      nodeId: string,
      active: boolean,
      phase: "engage" | "release",
    ) => {
      const ids = active
        ? new Set([
            nodeId,
            ...graph
              .getRelatedEdgesData(nodeId)
              .map((edge) => String(edge.id)),
          ])
        : dragLoadIds;
      if (!ids.size || graph.destroyed) return;
      dragLoadIds = active ? ids : new Set();
      dragMotionRef.current = phase;
      graph.setNode(nodeOptionsRef.current());
      graph.setEdge(edgeOptionsRef.current() as never);
      const states: Record<string, string[]> = {};
      for (const id of ids) {
        const current = graph.getElementState(id);
        states[id] = active
          ? [...current.filter((state) => state !== "dragLoad"), "dragLoad"]
          : current.filter((state) => state !== "dragLoad");
      }
      void graph
        .setElementState(states, PRODUCT_GRAPH_MOTION_ENABLED)
        .catch(() => {});
    };

    const commitHover = (next: HoverBundle) => {
      if (graph.destroyed) return;
      const previous = hoverActiveRef.current;
      const ids = new Set([
        ...previous.out,
        ...previous.inn,
        ...next.out,
        ...next.inn,
      ]);
      const patches = [...ids].flatMap((id) => {
        const edge = graph.getEdgeData(id);
        if (!edge) return [];
        const out = next.out.has(id);
        const inn = next.inn.has(id);
        const entering = out || inn;
        const visual = visualRef.current;
        // Named because it is evidence, or named because a node is held —
        // leaving hover must not strip an overlay-lit chip. Placement is the
        // same either way: a fixed distance from the held node, as in ambient.
        const named = entering || (visual.inverted && isLit(edge));
        const paint = edgePaint(edge, visual, named);
        const directBondSide: "source" | "target" | "" = entering
          ? inn
            ? "target"
            : "source"
          : "";
        return [
          {
            id,
            active: entering || named,
            style: {
              ...paint,
              directBondSide,
            },
          },
        ];
      });
      hoverActiveRef.current = next;
      hoverPaint.clear();
      for (const patch of patches) {
        hoverPaint.set(patch.id, {
          active: patch.active,
          style: patch.style as Record<string, unknown>,
        });
      }
      updateAmbientEdgeDisplay(graph, patches);
      applyPreviewDash();
    };
    commitHoverRef.current = commitHover;

    const publishCombinedHover = () => {
      commitHover(
        combineHoverBundles(
          pointerHoverRef.current,
          selectionHoverRef.current,
        ),
      );
    };

    const scheduleHover = (next: HoverBundle) => {
      pendingHover = next;
      if (hoverFrame) return;
      hoverFrame = requestAnimationFrame(() => {
        hoverFrame = 0;
        pointerHoverRef.current = pendingHover ?? emptyHoverBundle();
        publishCombinedHover();
        pendingHover = null;
      });
    };

    const heldNodeId = () => pointerNodeId || selectedIdRef.current;

    const indicateChip = (
      hit: { edgeId: string; otherId: string } | null,
    ) => {
      const same =
        (hit?.edgeId ?? null) === (chipHover?.edgeId ?? null) &&
        (hit?.otherId ?? null) === (chipHover?.otherId ?? null);
      if (same) return;
      chipHover = hit;
      container.style.cursor = hit ? "pointer" : "";
      if (hit) {
        if (leaveTimer) window.clearTimeout(leaveTimer);
        leaveTimer = 0;
        const held = heldNodeId();
        if (held) previewWidthRef.current(linkingEdgeIds(graph, held, hit.otherId));
        if (selectedIdRef.current) onPreviewRef.current?.(hit.otherId);
        applyPreviewDash();
        return;
      }
      if (selectedIdRef.current) onPreviewRef.current?.(null);
      previewWidthRef.current([]);
      applyPreviewDash();
    };

    const jumpTo = (other: string) => {
      if (!graph.getNodeData(other)) return;
      absorbCanvasClick = true;
      indicateChip(null);
      selectedIdRef.current = other;
      selectionHoverRef.current = hoverBundleFor(graph, other);
      pointerNodeId = other;
      publishCombinedHover();
      commitDodge(other);
      setSelectedId(other);
      if (onJumpRef.current) onJumpRef.current(other);
      else onSelectRef.current?.(other);
    };

    const chipHit = (clientX: number, clientY: number) => {
      const visual = visualRef.current;
      const heldId = heldNodeId();
      const held = heldId ? positionOf(graph, heldId) : null;
      const radius = visual.nodeDiameter / 2;
      const liveChips = new Map<string, { dest: Point; amount: number }>();
      if (held) {
        for (const [id, target] of dodgeTarget) {
          if (typeof target.fanAngle !== "number") continue;
          liveChips.set(id, {
            dest: fanChip(
              held,
              radius,
              target.fanAngle,
              target.fanAlong ?? BOND_LABEL_ALONG_PX,
            ),
            amount: dodgeAmount.get(id) ?? 0,
          });
        }
      }
      return chipAtPointer(
        graph,
        heldId,
        clientX,
        clientY,
        visual.edgeLabelSize,
        visual.nodeDiameter,
        liveChips,
      );
    };

    const onEnter = (event: IElementEvent) => {
      if (nodeDragActive) return;
      if (leaveTimer) window.clearTimeout(leaveTimer);
      const id = String(event.target?.id ?? "");
      if (!id) {
        pointerNodeId = null;
        scheduleHover(emptyHoverBundle());
        return;
      }
      pointerNodeId = id;
      indicateChip(null);
      scheduleHover(hoverBundleFor(graph, id));
      onHoverRef.current?.(id);
    };
    const onLeave = () => {
      if (nodeDragActive) return;
      leaveTimer = window.setTimeout(() => {
        pointerNodeId = null;
        scheduleHover(emptyHoverBundle());
        onHoverRef.current?.(null);
      }, 60);
    };
    const onChipEnter = (event: IElementEvent) => {
      if (nodeDragActive) return;
      const other = otherEndpoint(
        graph,
        String(event.target?.id ?? ""),
        heldNodeId(),
      );
      if (!other) return;
      indicateChip({
        edgeId: String(event.target?.id ?? ""),
        otherId: other,
      });
      onHoverRef.current?.(other);
    };
    const onChipLeave = () => {
      if (nodeDragActive) return;
      indicateChip(null);
      leaveTimer = window.setTimeout(() => {
        pointerNodeId = null;
        scheduleHover(emptyHoverBundle());
      }, 60);
    };
    const onChipClick = (event: IElementEvent) => {
      const other = otherEndpoint(
        graph,
        String(event.target?.id ?? ""),
        heldNodeId(),
      );
      if (!other) return;
      jumpTo(other);
    };
    const onStagePointerMove = (event: PointerEvent) => {
      if (nodeDragActive || event.buttons !== 0) return;
      const hit = chipHit(event.clientX, event.clientY);
      if (hit) {
        indicateChip(hit);
        return;
      }
      if (chipHover) indicateChip(null);
      const held = heldNodeId();
      if (
        held &&
        nearChipRing(
          graph,
          held,
          event.clientX,
          event.clientY,
          visualRef.current.nodeDiameter,
        )
      ) {
        if (leaveTimer) window.clearTimeout(leaveTimer);
        leaveTimer = 0;
        return;
      }
      if (pointerNodeId && !leaveTimer) {
        leaveTimer = window.setTimeout(() => {
          pointerNodeId = null;
          scheduleHover(emptyHoverBundle());
        }, 60);
      }
    };
    const onStagePointerDown = (event: PointerEvent) => {
      const hit = chipHit(event.clientX, event.clientY);
      if (!hit) {
        chipPointer = null;
        return;
      }
      chipPointer = { otherId: hit.otherId, x: event.clientX, y: event.clientY };
      absorbCanvasClick = true;
    };
    const onStagePointerUp = (event: PointerEvent) => {
      if (!chipPointer) return;
      const movedPx = Math.hypot(
        event.clientX - chipPointer.x,
        event.clientY - chipPointer.y,
      );
      const other = chipPointer.otherId;
      chipPointer = null;
      if (movedPx > 6) return;
      jumpTo(other);
    };
    const onClick = (event: IElementEvent) => {
      const id = String(event.target?.id ?? "");
      if (!id) return;
      if (
        suppressedSelection?.id === id &&
        performance.now() < suppressedSelection.until
      ) {
        return;
      }
      selectedIdRef.current = id;
      selectionHoverRef.current = hoverBundleFor(graph, id);
      publishCombinedHover();
      commitDodge(id);
      setSelectedId(id);
      onSelectRef.current?.(id);
    };
    const onCanvasClick = () => {
      if (absorbCanvasClick) {
        absorbCanvasClick = false;
        return;
      }
      if (performance.now() < ignoreCanvasUntil) return;
      selectedIdRef.current = null;
      selectionHoverRef.current = emptyHoverBundle();
      publishCombinedHover();
      commitDodge(null);
      setSelectedId(null);
      onSelectRef.current?.(null);
    };
    const onDragStart = (event: IElementEvent) => {
      const id = String(event.target?.id ?? "");
      if (!id) return;
      // Where it was *before* this gesture — the layout's position the first
      // time, or wherever the last drag left it.
      dragOrigin = { id, at: positionOf(graph, id) };
      nodeDragActive = true;
      suppressedSelection = { id, until: Number.POSITIVE_INFINITY };
      pointerHoverRef.current = hoverBundleFor(graph, id);
      publishCombinedHover();
      setDraggingId(id);
      commitDodge(null);
      if (PRODUCT_GRAPH_MOTION_ENABLED) setDragLoad(id, true, "engage");
    };
    const onDrag = (event: IElementEvent) => {
      const dragged = String(event.target?.id ?? "");
      if (!nodeDragActive) {
        nodeDragActive = true;
        snapDodgeOff();
      } else if (dodgeHeld.size || dodgeTarget.size || dodgeAmount.size) {
        snapDodgeOff();
      }
      if (dodgeDragFrame) return;
      dodgeDragFrame = requestAnimationFrame(() => {
        dodgeDragFrame = 0;
        if (graph.destroyed) return;
        const ids = new Set<string>();
        if (dragged && graph.getNodeData(dragged)) {
          for (const edge of graph.getRelatedEdgesData(dragged)) {
            ids.add(String(edge.id));
          }
        }
        refreshAmbientEdgeGeometry(graph, ids);
      });
    };
    const onDragEnd = (event: IElementEvent) => {
      const id = String(event.target?.id ?? "");
      nodeDragActive = false;
      if (id) {
        suppressedSelection = { id, until: performance.now() + 240 };
        ignoreCanvasUntil = performance.now() + 240;
        if (PRODUCT_GRAPH_MOTION_ENABLED) setDragLoad(id, false, "release");
        const origin = dragOrigin?.id === id ? dragOrigin.at : null;
        const landed = positionOf(graph, id);
        // A click that moves nothing is not a nudge, and must not fill the
        // undo stack with entries that appear to do nothing when replayed.
        if (origin && landed && moved(origin, landed)) {
          if (!nudgesRef.current.has(id)) nudgesRef.current.set(id, origin);
          undoRef.current.push({ id, from: origin, to: landed });
          redoRef.current = [];
          publishNudges();
        }
      }
      dragOrigin = null;
      setDraggingId(null);
      if (dodgeDragFrame) {
        cancelAnimationFrame(dodgeDragFrame);
        dodgeDragFrame = 0;
      }
      commitDodge(selectedIdRef.current);
      const ids = new Set<string>(dodgeHeld);
      if (id && graph.getNodeData(id)) {
        for (const edge of graph.getRelatedEdgesData(id)) {
          ids.add(String(edge.id));
        }
      }
      refreshAmbientEdgeGeometry(graph, ids);
    };
    const onPointerUp = () => {
      if (nodeDragActive) return;
      setDraggingId(null);
    };

    graph.on("node:pointerenter", onEnter);
    graph.on("node:pointerleave", onLeave);
    graph.on("node:click", onClick);
    graph.on("edge:pointerenter", onChipEnter);
    graph.on("edge:pointerleave", onChipLeave);
    graph.on("edge:click", onChipClick);
    graph.on("canvas:click", onCanvasClick);
    graph.on("node:dragstart", onDragStart);
    graph.on("node:drag", onDrag);
    graph.on("node:dragend", onDragEnd);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    container.addEventListener("pointermove", onStagePointerMove);
    container.addEventListener("pointerdown", onStagePointerDown, true);
    container.addEventListener("pointerup", onStagePointerUp, true);

    /**
     * Re-fit names after the camera moves.
     *
     * Only a *crossing* costs anything: the layout is compared first and the
     * redraw is skipped on every zoom tick that stays in the same step, which
     * is nearly all of them. Coalesced through one frame so a wheel gesture
     * that sweeps a step redraws once at rest rather than on each of its
     * forty events.
     */
    let readabilityFrame = 0;
    const syncLabelReadability = () => {
      if (readabilityFrame || graph.destroyed) return;
      readabilityFrame = requestAnimationFrame(() => {
        readabilityFrame = 0;
        if (graph.destroyed) return;
        const zoom = graph.getZoom() || 1;
        const spec = labelSpecRef.current;
        const shown = nodeLabelsVisible(
          zoom,
          spec.disc,
          spec.lineHeight,
          spec.maxLines,
          labelsShownRef.current,
        );
        if (shown === labelsShownRef.current) return;
        labelsShownRef.current = shown;
        // `draw()` alone is not enough: G6 holds the computed style per
        // element, so the `labelText` mapper is not consulted again and the
        // labels stay exactly as they were. Re-seating the node spec is what
        // invalidates it — the same two-step every other restyle in this file
        // uses. A bare draw here looked right, changed nothing, and would have
        // shipped as a fix.
        graph.setNode(nodeOptionsRef.current());
        void graph.draw().catch(() => {});
      });
    };
    graph.on("aftertransform", syncLabelReadability);
    graph.on("afterrender", syncLabelReadability);

    publishNudgesRef.current = publishNudges;
    publishNudges();
    graph
      .render()
      .then(async () => {
        if (graph.destroyed) return;
        setReady(true);
        onSceneReadyRef.current?.(true);
        await frameElements(graph, frameIds);
        // The camera is not final when `frameElements` resolves — `autoFit`
        // runs on its own schedule and the first fit lands after this. Asking
        // once here read the pre-fit zoom, decided the labels were unreadable,
        // and nothing fired afterwards to correct it: the 30-node default
        // graph sat at 8.7px, comfortably legible, with every label withheld.
        //
        // So the answer is re-asked across the settling window rather than
        // taken from one sample. All but one of these are free — the check
        // returns early unless the verdict actually changed.
        syncLabelReadability();
        for (const delay of [120, 400, 900]) {
          window.setTimeout(() => {
            if (!graph.destroyed) syncLabelReadability();
          }, delay);
        }
        onRenderErrorRef.current?.(null);
      })
      .catch((error) => {
        if (!graph.destroyed) {
          console.error("[product-graph] render failed", error);
          onRenderErrorRef.current?.("The map could not be drawn.");
        }
      });

    return () => {
      resizeObserver.disconnect();
      panelResizeClassObserver.disconnect();
      if (resizeFrame) cancelAnimationFrame(resizeFrame);
      if (leaveTimer) window.clearTimeout(leaveTimer);
      if (hoverFrame) cancelAnimationFrame(hoverFrame);
      if (previewFrame) cancelAnimationFrame(previewFrame);
      if (dodgeFrame) cancelAnimationFrame(dodgeFrame);
      if (dodgeDragFrame) cancelAnimationFrame(dodgeDragFrame);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
      container.removeEventListener("pointermove", onStagePointerMove);
      container.removeEventListener("pointerdown", onStagePointerDown, true);
      container.removeEventListener("pointerup", onStagePointerUp, true);
      container.style.cursor = "";
      cancelCameraFlight(graph);
      graph.destroy();
      graphRef.current = null;
      // The stacks name positions in a graph that no longer exists.
      nudgesRef.current.clear();
      undoRef.current = [];
      redoRef.current = [];
      onNudgesChangeRef.current?.(null);
      commitHoverRef.current = () => {};
      previewWidthRef.current = () => {};
      commitDodgeRef.current = () => {};
      pointerHoverRef.current = emptyHoverBundle();
      selectionHoverRef.current = emptyHoverBundle();
      renderedDataRef.current = null;
      renderedMapKeyRef.current = "";
      renderedNodeOptionsRef.current = null;
      renderedEdgeOptionsRef.current = null;
      renderedStyleKeyRef.current = "";
      renderedFrameKeyRef.current = "";
      setReady(false);
      onSceneReadyRef.current?.(false);
    };
    // The renderer lives for the component lifetime. The next effect applies
    // graph/model changes incrementally without destroying the canvas.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const graph = graphRef.current;
    if (!ready || !graph || graph.destroyed) return;

    const dataChanged = renderedDataRef.current !== data;
    const mapReplaced = Boolean(mapKey) && mapKey !== renderedMapKeyRef.current;
    // Whether the *map* changed, as opposed to the data object.
    //
    // These are not the same question, and assuming they were is how the first
    // attempt at a flying camera never flew. Focus is expressed by rewriting
    // per-node fields, so every focus arrives as a new `data` object —
    // `dataChanged` is true for exactly the case the camera most needs to fly
    // through. What decides whether a flight is honest is whether the nodes
    // beneath it are the same nodes in the same places, which is to say
    // whether the layout being crossed is the one already on screen.
    const sameMap =
      !mapReplaced &&
      (!dataChanged || sameNodeIdentity(renderedDataRef.current, data));
    const styleChanged = renderedStyleKeyRef.current !== styleKey;
    const nextFrameKey = frameIds.join("\u0000");
    const frameChanged = renderedFrameKeyRef.current !== nextFrameKey;
    if (!dataChanged && !styleChanged && !frameChanged && !mapReplaced) {
      return;
    }

    // Read before anything touches the graph. `setData` and the draw that
    // follows it hand the camera to `autoFit`, so this is the last moment the
    // question "where was the operator looking?" has the operator's answer.
    const departure = readCamera(graph);

    if (!sameMap) onSceneReadyRef.current?.(false);

    if (dataChanged) {
      commitHoverRef.current(emptyHoverBundle());
      pointerHoverRef.current = emptyHoverBundle();
      selectionHoverRef.current = emptyHoverBundle();
      previewWidthRef.current([]);
      if (!sameMap) clearAmbientEdgeDodge(graph);
      graph.setData(data);
      renderedDataRef.current = data;
      renderedMapKeyRef.current = mapKey;
      // New coordinates arrived, so the recorded "where the layout put it"
      // positions are about a map that no longer exists. Keeping them would
      // make Reset move nodes to where they used to be.
      nudgesRef.current.clear();
      undoRef.current = [];
      redoRef.current = [];
      publishNudgesRef.current();
    }
    if (styleChanged) {
      // Hover presentation is painted onto edge instances outside G6's mapper.
      // Clear it so resting DNA (width, opacity, stroke) is not held under a
      // stale transient while setEdge only updates base style.
      clearAmbientEdgeDisplay(graph);
      graph.setNode(nodeOptionsRef.current());
      graph.setEdge(edgeOptionsRef.current() as never);
      renderedNodeOptionsRef.current = nodeOptionsRef.current;
      renderedEdgeOptionsRef.current = edgeOptionsRef.current;
      renderedStyleKeyRef.current = styleKey;
    }
    renderedFrameKeyRef.current = nextFrameKey;
    renderedMapKeyRef.current = mapKey;

    const epoch = ++drawEpochRef.current;
    const update = async () => {
      if (dataChanged || styleChanged) {
        await graph.draw().catch(() => {});
        if (graph.destroyed || epoch !== drawEpochRef.current) return;
        if (dataChanged) {
          const selected = selectedIdRef.current;
          if (selected && graph.getNodeData(selected)) {
            selectionHoverRef.current = hoverBundleFor(graph, selected);
            commitHoverRef.current(
              combineHoverBundles(
                pointerHoverRef.current,
                selectionHoverRef.current,
              ),
            );
          } else if (selected) {
            selectedIdRef.current = null;
            setSelectedId(null);
          }
          const preview = previewIdRef.current;
          const inspected = selectedIdRef.current;
          if (
            preview &&
            inspected &&
            preview !== inspected &&
            graph.getNodeData(preview)
          ) {
            previewWidthRef.current(linkingEdgeIds(graph, inspected, preview));
          }
          commitDodgeRef.current(inspected);
        } else {
          commitHoverRef.current(hoverActiveRef.current);
          commitDodgeRef.current(selectedIdRef.current);
        }
      }
      if ((dataChanged || frameChanged) && !graph.destroyed && epoch === drawEpochRef.current) {
        // The camera flies to a focus and cuts to a new graph. A flight says
        // "the subject you were looking at is over there" — which is true when
        // the focus moved across a map that stayed still, and false when the
        // map itself was replaced. Flying across a layout the operator has
        // never seen is motion that describes a journey nobody took.
        await frameElements(
          graph,
          frameIds,
          sameMap ? (flightRef.current ?? undefined) : undefined,
          departure,
        );
      }
      if (!graph.destroyed && epoch === drawEpochRef.current) {
        onSceneReadyRef.current?.(true);
      }
    };
    void update();
  }, [data, frameIds, mapKey, ready, styleKey]);

  /**
   * Pinch to zoom, as direct manipulation.
   *
   * G6's pinch is not the browser's. There is no native pinch event on a
   * canvas — Safari's `gesturechange` is the only one and it is Safari's alone
   * — so G6 synthesises the gesture from pointer events in `utils/pinch.ts`,
   * and the product used it until this was measured. What it computes is:
   *
   *     scale  = (currentDistance / startDistance - 1) * 5     (PinchHandler)
   *     factor = 1 + scale * sensitivity / 100                 (ZoomCanvas)
   *     zoom   = currentZoom * factor                          (applied per move)
   *
   * Two things are wrong with that, and they partly cancel, which is why it
   * half-worked and felt strange rather than broken.
   *
   * **It is a velocity control wearing the costume of a position control.**
   * The factor multiplies the *current* zoom on every `pointermove`, while the
   * ratio it is derived from is measured against the distance at gesture
   * start. So the total zoom is the product of every frame's factor, and how
   * far your fingers ended up apart is not what decides it — how many move
   * events fired on the way does. The same gesture performed slowly zooms
   * further than performed quickly, and a 120Hz screen is not the same product
   * as a 60Hz one. Pinch out and back to exactly where you started, and the
   * map does not come back.
   *
   * **The gain is 5%.** `(ratio - 1) * 5 / 100` means doubling the distance
   * between your fingers asks for a 5% zoom. That is the damping that stops
   * the accumulation above from exploding — two errors keeping each other
   * roughly plausible.
   *
   * The fix is not a sensitivity number, because no constant repairs a control
   * whose gain depends on event rate. It is to state the thing a pinch
   * actually means: the two points under your fingers stay under your fingers.
   * Zoom is `zoomAtGestureStart × (distance / startDistance)`, and the canvas
   * point beneath the midpoint is pinned there — which is also two-finger pan,
   * for free, because pinning a moving anchor *is* panning.
   */
  useEffect(() => {
    const graph = graphRef.current;
    const element = stageRef.current;
    if (!ready || !graph || graph.destroyed || !element) return;

    const touches = new Map<number, { x: number; y: number }>();
    let gesture: {
      distance: number;
      zoom: number;
      /** The canvas point under the fingers' midpoint when the pinch began. */
      anchor: [number, number];
    } | null = null;

    const spread = () => {
      const [a, b] = [...touches.values()];
      return {
        distance: Math.hypot(a.x - b.x, a.y - b.y),
        midpoint: [(a.x + b.x) / 2, (a.y + b.y) / 2] as [number, number],
      };
    };

    const begin = () => {
      if (touches.size !== 2 || graph.destroyed) return;
      const { distance, midpoint } = spread();
      // Two fingers landing on the same spot is not a scale anyone asked for.
      if (distance < 24) return;
      const anchor = graph.getCanvasByClient(midpoint);
      gesture = {
        distance,
        zoom: graph.getZoom(),
        anchor: [anchor[0], anchor[1]],
      };
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType !== "touch") return;
      touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (touches.size === 2) begin();
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType !== "touch") return;
      if (!touches.has(event.pointerId)) return;
      touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (!gesture || touches.size !== 2 || graph.destroyed) return;

      const { distance, midpoint } = spread();
      const range = graph.getZoomRange() ?? [0.01, 10];
      const zoom = Math.min(
        range[1],
        Math.max(range[0], gesture.zoom * (distance / gesture.distance)),
      );
      void graph.zoomTo(zoom, false).catch(() => {});
      if (graph.destroyed) return;

      // Put the anchor back under the fingers. Asked *after* the zoom, for the
      // same reason the flight asks after its own: where a canvas point lands
      // is G6's arithmetic to do, not this file's to duplicate. A difference
      // of two client points is a difference of two viewport points — the two
      // spaces share a scale and differ only in origin — so this delta is
      // valid in the space `translateBy` wants.
      const at = graph.getClientByCanvas(gesture.anchor);
      void graph
        .translateBy([midpoint[0] - at[0], midpoint[1] - at[1]], false)
        .catch(() => {});
    };

    const onPointerEnd = (event: PointerEvent) => {
      if (event.pointerType !== "touch") return;
      touches.delete(event.pointerId);
      if (touches.size < 2) gesture = null;
      // Lifting one of three fingers leaves two, and the gesture they describe
      // is a new one: re-reading the baseline here is what stops the map
      // jumping by whatever the departed finger contributed.
      if (touches.size === 2) begin();
    };

    element.addEventListener("pointerdown", onPointerDown, { passive: true });
    // Moves are taken from the window: a finger that slides off the canvas is
    // still part of the gesture, and losing it mid-pinch strands `gesture`
    // with a stale baseline.
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerup", onPointerEnd, { passive: true });
    window.addEventListener("pointercancel", onPointerEnd, { passive: true });

    return () => {
      element.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerEnd);
      window.removeEventListener("pointercancel", onPointerEnd);
      touches.clear();
      gesture = null;
    };
  }, [ready]);

  useEffect(() => {
    const graph = graphRef.current;
    const element = stageRef.current;
    if (!ready || !graph || graph.destroyed || !element) return;
    // The proximity lens is continuous pointer-driven rendering. Suspend it
    // with product motion so this baseline has no hidden per-frame graph work.
    if (!PRODUCT_GRAPH_MOTION_ENABLED) return;
    let previousLens = new Map<string, number>();
    let previousPlacement = new Map<string, number>();
    let pending: { x: number; y: number } | null = null;
    let drawing = false;
    let frame = 0;

    const commit = (
      nextLens: Map<string, number>,
      nextPlacement: Map<string, number>,
    ) => {
      const updates: Array<{ id: string; data: Record<string, unknown> }> = [];
      const seen = new Set<string>();
      for (const [id, lens] of nextLens) {
        seen.add(id);
        const placement = nextPlacement.get(id) ?? 0.5;
        if (
          Math.abs((previousLens.get(id) ?? 0) - lens) < 0.004 &&
          Math.abs((previousPlacement.get(id) ?? 0.5) - placement) < 0.008
        ) {
          continue;
        }
        const edge = graph.getEdgeData(id);
        if (!edge) continue;
        updates.push({ id, data: { ...edge.data, lens, _lp: placement } });
      }
      for (const id of previousLens.keys()) {
        if (seen.has(id)) continue;
        const edge = graph.getEdgeData(id);
        if (!edge) continue;
        updates.push({
          id,
          data: {
            ...edge.data,
            lens: 0,
            _lp: bondOf(edge) > 0.008 ? edge.data?._lp : 0.5,
          },
        });
      }
      previousLens = nextLens;
      previousPlacement = nextPlacement;
      if (!updates.length) return false;
      graph.updateEdgeData(updates);
      return true;
    };

    const run = async () => {
      frame = 0;
      const point = pending;
      pending = null;
      if (!point || graph.destroyed) return;
      const [cx, cy] = graph.getCanvasByClient([point.x, point.y]);
      const radius =
        interactionRef.current.hoverRadius / Math.max(0.05, graph.getZoom() || 1);
      const nextLens = new Map<string, number>();
      const nextPlacement = new Map<string, number>();
      for (const edge of graph.getEdgeData()) {
        if (isLit(edge)) continue;
        try {
          const source = graph.getElementPosition(String(edge.source));
          const target = graph.getElementPosition(String(edge.target));
          const distance = distanceToSegment(
            cx,
            cy,
            source[0],
            source[1],
            target[0],
            target[1],
          );
          const strength = lensFalloff(distance, radius);
          if (strength <= 0.008) continue;
          const id = String(edge.id);
          nextLens.set(id, strength);
          nextPlacement.set(
            id,
            closestPointRatio(
              cx,
              cy,
              source[0],
              source[1],
              target[0],
              target[1],
            ),
          );
        } catch {
          // An element can disappear while a different graph is opening.
        }
      }
      if (commit(nextLens, nextPlacement)) {
        drawing = true;
        await graph.draw().catch(() => {});
        drawing = false;
      }
      if (pending && !frame) frame = requestAnimationFrame(() => void run());
    };

    const onMove = (event: PointerEvent) => {
      if (event.buttons !== 0) {
        pending = null;
        if (previousLens.size && commit(new Map(), new Map())) {
          void graph.draw().catch(() => {});
        }
        return;
      }
      pending = { x: event.clientX, y: event.clientY };
      if (!drawing && !frame) frame = requestAnimationFrame(() => void run());
    };
    const clear = () => {
      pending = null;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      if (commit(new Map(), new Map())) void graph.draw().catch(() => {});
    };

    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerleave", clear);
    element.addEventListener("pointercancel", clear);
    return () => {
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerleave", clear);
      element.removeEventListener("pointercancel", clear);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ready]);

  useEffect(() => {
    if (selectedId && !data.nodes?.some((node) => node.id === selectedId)) {
      selectedIdRef.current = null;
      selectionHoverRef.current = emptyHoverBundle();
      commitHoverRef.current(
        combineHoverBundles(
          pointerHoverRef.current,
          selectionHoverRef.current,
        ),
      );
      commitDodgeRef.current(null);
      setSelectedId(null);
    }
  }, [data.nodes, selectedId]);

  // Keep canvas selection ring / incident edges in sync when the parent
  // drives selection (reader link chips, panel close, URL focus later).
  useEffect(() => {
    if (controlledSelectedId === undefined) return;
    if (controlledSelectedId === selectedIdRef.current) return;
    const graph = graphRef.current;
    selectedIdRef.current = controlledSelectedId;
    setSelectedId(controlledSelectedId);
    if (!ready || !graph || graph.destroyed) return;
    if (controlledSelectedId && graph.getNodeData(controlledSelectedId)) {
      selectionHoverRef.current = hoverBundleFor(graph, controlledSelectedId);
    } else {
      selectionHoverRef.current = emptyHoverBundle();
    }
    commitHoverRef.current(
      combineHoverBundles(
        pointerHoverRef.current,
        selectionHoverRef.current,
      ),
    );
    commitDodgeRef.current(controlledSelectedId);
  }, [controlledSelectedId, ready]);

  // A neighbour row names the bond(s) that join it to the inspected disc.
  // Solid → dotted — emit on, absorb off. Jumping the row clears this.
  // Canvas pointerleave must not wipe it; it is not pointer hover.
  useEffect(() => {
    const graph = graphRef.current;
    if (!ready || !graph || graph.destroyed) {
      previewWidthRef.current([]);
      return;
    }
    const inspected = selectedIdRef.current;
    if (
      previewId &&
      inspected &&
      previewId !== inspected &&
      graph.getNodeData(previewId)
    ) {
      previewWidthRef.current(linkingEdgeIds(graph, inspected, previewId));
      return;
    }
    previewWidthRef.current([]);
  }, [previewId, ready]);

  // Fly to a node the reader named, the same flight a focus uses when its
  // framed set changes. `selectedId` is not enough: a canvas click already
  // selected the node, and framing it would zoom a thing the operator is
  // looking at.
  useEffect(() => {
    if (!followId) return;
    const graph = graphRef.current;
    if (!ready || !graph || graph.destroyed) return;
    if (!graph.getNodeData(followId)) return;
    void frameElements(
      graph,
      [followId],
      flightRef.current ?? undefined,
    );
  }, [followId, ready]);

  return (
    <div
      className={`product-graph-canvas${inverted ? " is-inverted" : ""}`}
    >
      <div className="product-graph-canvas__stage" ref={stageRef} />
      <SelectionAntRing
        graph={ready ? graphRef.current : null}
        nodeId={selectedId}
        nodeDiameter={geometry.nodeDiameter}
        speed={selectionMotion ? interaction.selectionSpeed : 0}
        clearance={interaction.selectionClearance}
        dotGap={interaction.selectionDotGap}
        lineWidth={interaction.selectionLine}
        color={inverted ? focus.lit : palette.node}
        dragging={Boolean(selectedId && draggingId)}
        motion={motion}
        heldScale={interaction.gripScale}
        gravityTravel={interaction.gravityTravel}
        animated={selectionMotion}
        withdrawOnDrag
      />
    </div>
  );
}
