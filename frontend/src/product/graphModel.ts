/**
 * Turning a server map into canvas geometry — shared by every product surface
 * that draws a graph.
 *
 * These three pieces were duplicated verbatim in `GraphWorkspace` and
 * `ReviewWorkspace`, which is how the two pages ended up disagreeing about what
 * a proposal looks like: Graph could draw one, Review could not. A node placed
 * differently on two screens is a different claim about where it sits.
 */

import type { GraphMap } from "../api/graph";
import type { ProposalVM } from "../api/ledger";
import { GRAPH_DNA_GEOMETRY } from "../styles/graphDna";

export type Point = { x: number; y: number };

/**
 * Closest on-screen centre distance, as a multiple of drawn node diameter.
 * Mirrored from `graph_layout.contract.MIN_NODE_PITCH_RATIO` — keep in step.
 * 1.0 is tangency (a mat of discs); 1.6 is the “as arranged” floor with a
 * real gap that still admits filaments between nodes.
 */
const MIN_NODE_PITCH_RATIO = 1.6;

/**
 * Normalise server coordinates into display space.
 *
 * Server layouts are stable in relative space but different layout engines emit
 * very different coordinate units. A uniform display transform retains the
 * authored arrangement while keeping equal-size product matter legible.
 *
 * **Fitting to an extent is what made nodes overlap, and it could never not
 * have.** The target below is roughly `sqrt(n) * 170`, while the server
 * guarantees `layout_clearance` — 220 — between node centres. 170 is smaller
 * than 220, so even a flawlessly square-packed map was squeezed to 77% of the
 * pitch it needed. The floor stops that: “as arranged” (spacing = 1) is already
 * collision-safe for the *drawn* disc size, and the operator’s spacing control
 * only ever multiplies further room on top.
 *
 * The payload’s `min_display_scale` assumes the server’s `node_diameter`. When
 * Graph DNA paints a larger disc, the floor is rebased so “as arranged” still
 * means “does not crash nodes”, not “server’s old 62px math on 90px matter”.
 */
export function displayPositions(
  map: GraphMap,
  /**
   * Room multiplier on top of the anti-collision floor. 1 is “as arranged”
   * (the generous baseline). Values above 1 only add air; nothing here can
   * request a tighter map than the floor, because that is how collisions return.
   */
  spacing = 1,
): Map<string, Point> {
  if (!map.nodes.length) return new Map();
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  // A loop rather than `Math.min(...nodes)` — spreading a large map through the
  // argument list overflows the stack, and maps here are deliberately uncapped.
  for (const node of map.nodes) {
    if (node.x < minX) minX = node.x;
    if (node.x > maxX) maxX = node.x;
    if (node.y < minY) minY = node.y;
    if (node.y > maxY) maxY = node.y;
  }
  const width = Math.max(1, maxX - minX);
  const height = Math.max(1, maxY - minY);
  const targetExtent = Math.max(
    720,
    Math.min(2600, Math.sqrt(map.nodes.length) * 170),
  );
  const clearance = map.layout_clearance ?? 220;
  const drawnDiameter = GRAPH_DNA_GEOMETRY.nodeDiameter;
  const payloadFloor = map.min_display_scale ?? 0;
  const serverDiameter = map.node_diameter ?? 0;
  // Rebase the server floor when Graph DNA’s disc is not the diameter the
  // server used to compute it (the silent failure behind “as arranged still
  // collides after a diameter bump”).
  const rebasedPayloadFloor =
    serverDiameter > 0
      ? payloadFloor * (drawnDiameter / serverDiameter)
      : payloadFloor;
  const localFloor =
    clearance > 0
      ? (drawnDiameter * MIN_NODE_PITCH_RATIO) / clearance
      : 0;
  const floor = Math.max(rebasedPayloadFloor, localFloor);
  const scale =
    Math.max(floor, targetExtent / Math.max(width, height)) *
    Math.max(1, Math.min(2, spacing));
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  return new Map(
    map.nodes.map((node) => [
      node.id,
      { x: (node.x - centerX) * scale, y: (node.y - centerY) * scale },
    ]),
  );
}

/**
 * Place the nodes a proposal would add.
 *
 * A proposed node has no server coordinate — it is not in the graph yet — so it
 * is ringed around the committed nodes its edges attach to. That placement is a
 * statement about *what it would connect to*, which is the question a reviewer
 * is actually being asked, and it is why proposed nodes must never be dropped
 * for lacking a position.
 */
export function proposalPositions(
  map: GraphMap,
  proposal: ProposalVM,
  committedPositions: Map<string, Point>,
): Map<string, Point> {
  const existing = new Set(map.nodes.map((node) => node.id));
  const anchorIds = new Set<string>();
  for (const edge of proposal.edges) {
    if (existing.has(edge.source_id)) anchorIds.add(edge.source_id);
    if (existing.has(edge.target_id)) anchorIds.add(edge.target_id);
  }
  const anchors = [...anchorIds]
    .map((id) => committedPositions.get(id))
    .filter((position): position is Point => Boolean(position));
  const basis = anchors.length ? anchors : [...committedPositions.values()];
  const cx = basis.reduce((sum, p) => sum + p.x, 0) / Math.max(1, basis.length);
  const cy = basis.reduce((sum, p) => sum + p.y, 0) / Math.max(1, basis.length);
  const novel = proposal.nodes.filter((node) => !existing.has(node.id));
  return new Map(
    novel.map((node, index) => {
      const angle =
        -Math.PI / 2 + (index * Math.PI * 2) / Math.max(3, novel.length);
      const ring = 150 + Math.floor(index / 8) * 90;
      return [
        node.id,
        {
          x: Math.round(cx + Math.cos(angle) * ring),
          y: Math.round(cy + Math.sin(angle) * ring),
        },
      ];
    }),
  );
}

/**
 * Above this share of the map's edges, spokes stop being noise and start being
 * the graph, so they are drawn at full strength.
 *
 * Measured: on `rfc` the first tier is 59 of 415 edges (14%) and produces 154 of
 * the map's 168 crossings — textbook noise, worth holding back. On the 200-node
 * `tesco` corpus the same annotation covers 179 of 236 edges (76%), because that
 * graph genuinely *is* a star. Dimming three quarters of a map does not make it
 * calmer, it makes it empty.
 */
export const SPOKE_DIM_MAX_SHARE = 0.33;

/**
 * Which edges to draw quietly, keyed `source target`.
 *
 * Whether an edge is a spoke is a fact the server measured; whether that fact
 * should cost it contrast is a question about this picture, which is why the
 * threshold lives here and not in the layout.
 */
/**
 * The key a (source, target) pair is looked up under in `dimmableSpokes`.
 *
 * Exported so the caller cannot spell it differently from the producer. It
 * already had: this set was built with a space and read with a `\u0000`, so
 * `has()` never once returned true and spoke dimming was dead on every map that
 * had spokes. Nothing failed — the map just quietly drew its worst edges at full
 * weight. A shared function is the only version of this that cannot drift.
 *
 * `\u0000` rather than a space because node ids are server-supplied strings and
 * a space is a character they may legitimately contain; a NUL is not.
 */
export function spokeKey(source: string, target: string): string {
  return `${source}\u0000${target}`;
}

export function dimmableSpokes(map: GraphMap): Set<string> {
  const spokes = map.spokes ?? [];
  if (!spokes.length || !map.edges.length) return new Set();
  if (spokes.length / map.edges.length > SPOKE_DIM_MAX_SHARE) return new Set();
  return new Set(spokes.map(([source, target]) => spokeKey(source, target)));
}

/* Structural roles used to be projected here — `causal_nexus`,
   `inter_region_bridge`, `associative_hub` and the rest, ranked and printed as
   a chip on the node reader. They are gone.

   They were engine vocabulary wearing a product label. "causal nexus" told an
   operator nothing they could act on: it did not say what to read next, what to
   add to the graph, or why this node mattered to their question — and the
   underscore-to-space rename made it *look* like product copy while still
   requiring the engine's taxonomy to decode. Betweenness stays, because it is
   a number that sizes the node you can see.

   The engine still computes roles: `compute_structural_index` feeds them to the
   Graph Compass, which the Planner reads to orient itself. That is a real
   consumer and untouched. What ended here is the claim that a human reading a
   node wants to see them. */
