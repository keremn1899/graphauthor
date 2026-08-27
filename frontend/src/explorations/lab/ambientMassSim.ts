/**
 * Live force simulation for the ambient mass canvas.
 *
 * Physics character matches Canvas linkage's **Glide Loose**
 * (`FORCE_PRESETS["glide-loose"]`): link-only, no many-body charge, soft decay.
 * LOD-specific extras on top:
 *
 * - Collide radius is each node's **subtree footprint** — constant across the
 *   dial so grown survivors have reserved room (linkage uses a fixed NODE_SIZE).
 * - A custom homing force pulls a folding node toward its absorber.
 *
 * No `forceCenter` — same as linkage (`center: false`). The sim owns x/y;
 * the dial owns size/presence.
 */

import {
  forceCollide,
  forceLink,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { FORCE_PRESETS, SETTLE_ALPHA } from "../g6/forcePresets";

export interface MassSimNode extends SimulationNodeDatum {
  id: string;
}

type MassSimLink = SimulationLinkDatum<MassSimNode>;

export interface MassSimHandle {
  /** Push new fold state; the homing force follows it. */
  setPresence: (
    presenceById: Map<string, number>,
    opts?: { reheat?: boolean },
  ) => void;
  dragMove: (id: string, x: number, y: number) => void;
  dragEnd: (id: string) => void;
  positions: () => Map<string, [number, number]>;
  /** Centroid at sim creation — useful for framing, not a live force. */
  anchor: () => [number, number];
  /** Current simulation temperature; ~0 means settled. */
  alpha: () => number;
  stop: () => void;
}

export interface MassSimConfig {
  nodes: { id: string; x: number; y: number }[];
  edges: { source: string; target: string }[];
  /** node id → its absorber's id (or null for a local maximum). */
  absorber: Map<string, string | null>;
  /** node id → collide diameter: the node's full subtree footprint. */
  footprint: Map<string, number>;
  /** Override Glide Loose link distance (default 260). */
  linkDistance?: number;
  collidePad: number;
  onTick: (positions: Map<string, [number, number]>) => void;
}

const GLIDE = FORCE_PRESETS["glide-loose"].layout;
const GLIDE_LINK =
  GLIDE.link === false || GLIDE.link == null
    ? { distance: 260, strength: 0.07, iterations: 1 }
    : GLIDE.link;
const GLIDE_COLLIDE =
  GLIDE.collide === false || GLIDE.collide == null
    ? { strength: 1, iterations: 3 }
    : GLIDE.collide;

/** How hard a fully-folded node is pulled toward its absorber. */
const HOMING_STRENGTH = 0.9;

function numOpt(
  value: number | ((...args: never[]) => number) | undefined,
  fallback: number,
) {
  return typeof value === "number" ? value : fallback;
}

export function createMassSim(config: MassSimConfig): MassSimHandle {
  const { nodes, edges, absorber, footprint, collidePad, onTick } = config;

  const linkDistance = config.linkDistance ?? numOpt(GLIDE_LINK.distance, 260);
  const linkStrength = numOpt(GLIDE_LINK.strength, 0.07);
  const linkIterations = numOpt(GLIDE_LINK.iterations, 1);
  const collideStrength = numOpt(GLIDE_COLLIDE.strength, 1);
  const collideIterations = numOpt(GLIDE_COLLIDE.iterations, 3);

  const simNodes: MassSimNode[] = nodes.map((n) => ({
    id: n.id,
    x: n.x,
    y: n.y,
  }));
  const byId = new Map(simNodes.map((n) => [n.id, n]));

  const cx =
    simNodes.reduce((s, n) => s + (n.x ?? 0), 0) / Math.max(1, simNodes.length);
  const cy =
    simNodes.reduce((s, n) => s + (n.y ?? 0), 0) / Math.max(1, simNodes.length);

  let presenceById = new Map<string, number>();

  const radiusOf = (node: MassSimNode) =>
    (footprint.get(node.id) ?? 20) / 2 + collidePad;

  const homing = (alpha: number) => {
    for (const node of simNodes) {
      const parentId = absorber.get(node.id);
      if (!parentId) continue;
      const parent = byId.get(parentId);
      if (!parent) continue;
      const folded = 1 - (presenceById.get(node.id) ?? 1);
      if (folded <= 0) continue;
      const k = folded * HOMING_STRENGTH * alpha;
      node.vx = (node.vx ?? 0) + ((parent.x ?? 0) - (node.x ?? 0)) * k;
      node.vy = (node.vy ?? 0) + ((parent.y ?? 0) - (node.y ?? 0)) * k;
    }
  };

  const simLinks: MassSimLink[] = edges
    .filter((e) => byId.has(e.source) && byId.has(e.target))
    .map((e) => ({ source: e.source, target: e.target }));

  const sim: Simulation<MassSimNode, MassSimLink> = forceSimulation(simNodes)
    .force(
      "link",
      forceLink<MassSimNode, MassSimLink>(simLinks)
        .id((d) => d.id)
        .distance(linkDistance)
        .strength(linkStrength)
        .iterations(linkIterations),
    )
    .force(
      "collide",
      forceCollide<MassSimNode>()
        .radius(radiusOf)
        .strength(collideStrength)
        .iterations(collideIterations),
    )
    .force("home", homing)
    // Glide Loose: center false — no ambient many-body either.
    .velocityDecay(GLIDE.velocityDecay ?? 0.48)
    .alphaDecay(GLIDE.alphaDecay ?? 0.035);

  const emit = () => {
    const map = new Map<string, [number, number]>();
    for (const n of simNodes) map.set(n.id, [n.x ?? 0, n.y ?? 0]);
    onTick(map);
  };
  sim.on("tick", emit);

  return {
    setPresence(nextPresence, opts) {
      presenceById = nextPresence;
      if (opts?.reheat === false) return;
      sim.alpha(Math.max(sim.alpha(), SETTLE_ALPHA)).restart();
    },
    dragMove(id, x, y) {
      const node = byId.get(id);
      if (!node) return;
      node.fx = x;
      node.fy = y;
      node.x = x;
      node.y = y;
      if (sim.alpha() < 0.1) sim.alpha(0.3).restart();
    },
    dragEnd(id) {
      const node = byId.get(id);
      if (!node) return;
      node.fx = null;
      node.fy = null;
      sim.alpha(Math.max(sim.alpha(), 0.2)).restart();
    },
    positions() {
      const map = new Map<string, [number, number]>();
      for (const n of simNodes) map.set(n.id, [n.x ?? 0, n.y ?? 0]);
      return map;
    },
    anchor() {
      return [cx, cy];
    },
    alpha() {
      return sim.alpha();
    },
    stop() {
      sim.on("tick", null);
      sim.stop();
    },
  };
}
