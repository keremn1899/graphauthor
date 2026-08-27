/**
 * Degree-derived abstraction model for the ambient canvas.
 *
 * Mirrors what the backend already computes, rather than inventing UI-only
 * semantics (see `design/ambient-canvas-lod-handoff.md` §3.1 and engine.py):
 *
 * - `centrality` here is engine.py's `centrality_score` — normalised *degree*
 *   (`total_degree / max_degree`), written onto the Concept at index time and
 *   returned by retrieval as `centrality`. It is a supported field, not a
 *   back-compat leftover.
 * - Landmarks follow `compute_compass`: `min(8, max(3, node_count // 5))`.
 *   The backend ranks them by betweenness when a full Brandes pass ran, and by
 *   degree under `SST_FAST_STRUCTURAL_INDEX`. It reports which via
 *   `importance_kind`, so **never assume betweenness** — read the field.
 *
 * Why degree and not betweenness for the abstraction dial: betweenness counts a
 * node only when it is an *internal* vertex of a directed shortest path, so any
 * pure source scores exactly 0. Containment roots and every `causal_origin` are
 * pure sources. In the real `credential-governance` index, `handbook_root` holds
 * 12 of 16 nodes and scores betweenness 0.0 — invisible to a betweenness-ranked
 * hierarchy. Degree finds it first.
 */

export type ImportanceKind = "degree" | "betweenness";

export interface MassNodeFacts {
  id: string;
  /** Undirected total degree — engine.py `StructuralFacts.total_degree`. */
  degree: number;
  /** `total_degree / max_degree`, 0…1. engine.py `centrality_score`. */
  centrality: number;
  isLandmark: boolean;
}

export interface CoarsenModel {
  /**
   * Cache key. Backend `graph_version` is `sha1(path | mtime_ns | n=count)`, an
   * equality check for drift — not a revision counter. Any change is a full
   * invalidate; never try to diff two versions.
   */
  graphVersion: string;
  importanceKind: ImportanceKind;
  nodeCount: number;
  facts: Map<string, MassNodeFacts>;
  /**
   * Strictly-higher-ranked neighbour a node folds into, or null if the node is
   * a local maximum. Rank is (degree desc, id asc) — a strict total order, so
   * absorber chains cannot cycle.
   */
  absorber: Map<string, string | null>;
  /** Node ids by rank: index 0 is the highest-degree node. */
  ranked: string[];
  /** Local maxima — always survive, so every chain terminates on a survivor. */
  roots: string[];
  /**
   * What a node would stand for if its whole absorber subtree folded into it —
   * its maximum footprint. Layout uses this to reserve space, so the coarse
   * view has room for grown survivors.
   */
  subtreeMass: Map<string, number>;
}

export interface LevelState {
  /** Requested survivor count (actual may exceed it — roots always survive). */
  level: number;
  survivors: string[];
  /** Survivor id → how many nodes it currently stands for (including itself). */
  mass: Map<string, number>;
  /** Absorbed id → the survivor it folded into. */
  absorbedInto: Map<string, string>;
}

export interface MassEdge {
  source: string;
  target: string;
}

/** True when `a` outranks `b` under (degree desc, id asc). */
function outranks(
  a: string,
  b: string,
  degree: Map<string, number>,
): boolean {
  const da = degree.get(a) ?? 0;
  const db = degree.get(b) ?? 0;
  if (da !== db) return da > db;
  return a < b;
}

export function buildCoarsenModel(
  nodeIds: string[],
  edges: MassEdge[],
  graphVersion: string,
  importanceKind: ImportanceKind = "degree",
): CoarsenModel {
  const degree = new Map<string, number>();
  const neighbours = new Map<string, Set<string>>();
  for (const id of nodeIds) {
    degree.set(id, 0);
    neighbours.set(id, new Set());
  }

  for (const edge of edges) {
    const { source, target } = edge;
    if (!degree.has(source) || !degree.has(target) || source === target) continue;
    // Undirected total: in + out, matching StructuralFacts.total_degree.
    degree.set(source, (degree.get(source) ?? 0) + 1);
    degree.set(target, (degree.get(target) ?? 0) + 1);
    neighbours.get(source)!.add(target);
    neighbours.get(target)!.add(source);
  }

  const maxDegree = Math.max(1, ...degree.values());
  const ranked = [...nodeIds].sort((a, b) => (outranks(a, b, degree) ? -1 : 1));

  // compute_compass: min(8, max(3, node_count // 5)), degree > 0 required.
  const landmarkCount = Math.min(
    8,
    Math.max(3, Math.floor(nodeIds.length / 5)),
  );
  const landmarks = new Set(
    ranked.filter((id) => (degree.get(id) ?? 0) > 0).slice(0, landmarkCount),
  );

  const facts = new Map<string, MassNodeFacts>();
  for (const id of nodeIds) {
    const d = degree.get(id) ?? 0;
    facts.set(id, {
      id,
      degree: d,
      centrality: d / maxDegree,
      isLandmark: landmarks.has(id),
    });
  }

  // Heavy-neighbour matching (the multilevel graph-coarsening move): each node
  // folds into its highest-ranked neighbour. No containment tree required, and
  // on a CONTAINS-heavy graph children land on their parent anyway, because the
  // parent carries the higher degree.
  const absorber = new Map<string, string | null>();
  const roots: string[] = [];
  for (const id of nodeIds) {
    let best: string | null = null;
    for (const nb of neighbours.get(id) ?? []) {
      if (!outranks(nb, id, degree)) continue;
      if (best === null || outranks(nb, best, degree)) best = nb;
    }
    absorber.set(id, best);
    if (best === null) roots.push(id);
  }

  // Absorbers always outrank their children, so walking lowest-rank-first
  // finalises a child before its parent reads it.
  const subtreeMass = new Map<string, number>();
  for (const id of ranked) subtreeMass.set(id, 1);
  for (let i = ranked.length - 1; i >= 0; i--) {
    const id = ranked[i];
    const parent = absorber.get(id);
    if (parent) {
      subtreeMass.set(
        parent,
        (subtreeMass.get(parent) ?? 1) + (subtreeMass.get(id) ?? 1),
      );
    }
  }

  return {
    graphVersion,
    importanceKind,
    nodeCount: nodeIds.length,
    facts,
    absorber,
    ranked,
    roots,
    subtreeMass,
  };
}

/**
 * Resolve the graph at an abstraction level.
 *
 * Survivors are the top `level` by rank *plus* every local maximum. Forcing
 * roots to survive is what guarantees each absorber chain terminates on a
 * survivor, so no node — and no mass — is ever dropped on the floor.
 */
export function resolveLevel(model: CoarsenModel, level: number): LevelState {
  const target = Math.max(1, Math.min(model.nodeCount, Math.round(level)));
  const survivorSet = new Set(model.ranked.slice(0, target));
  for (const root of model.roots) survivorSet.add(root);

  const mass = new Map<string, number>();
  for (const id of survivorSet) mass.set(id, 1);

  const absorbedInto = new Map<string, string>();
  for (const id of model.ranked) {
    if (survivorSet.has(id)) continue;
    let cursor: string | null = id;
    const seen = new Set<string>();
    while (cursor !== null && !survivorSet.has(cursor)) {
      if (seen.has(cursor)) {
        cursor = null;
        break;
      }
      seen.add(cursor);
      cursor = model.absorber.get(cursor) ?? null;
    }
    if (cursor === null) continue; // unreachable while roots always survive
    absorbedInto.set(id, cursor);
    mass.set(cursor, (mass.get(cursor) ?? 1) + 1);
  }

  return {
    level: target,
    survivors: model.ranked.filter((id) => survivorSet.has(id)),
    mass,
    absorbedInto,
  };
}

export interface ContinuousState {
  /** Effective mass per node — real-valued, continuous in `level`. */
  mass: Map<string, number>;
  /** 0…1 — how present a node is. Doubles as its opacity. */
  presence: Map<string, number>;
}

function childLists(model: CoarsenModel): Map<string, string[]> {
  const children = new Map<string, string[]>();
  for (const [id, parent] of model.absorber) {
    if (!parent) continue;
    const list = children.get(parent);
    if (list) list.push(id);
    else children.set(parent, [id]);
  }
  return children;
}

export interface ContinuousResolver {
  (level: number): ContinuousState;
}

export interface ContinuousOptions {
  /** Minimum ramp width in ranks, used at the abstract end. */
  minWindow?: number;
  /** Ramp width as a fraction of the current level. */
  relativeWindow?: number;
}

/**
 * Build a resolver that is continuous in `level` (a real number, not a count).
 *
 * Folding is discrete, so interpolating between two adjacent integer levels
 * only smooths a fold when the dial moves less than one level per input event.
 * A geometric dial does not: near full detail it skips ~10 levels per wheel
 * notch, and a heavy absorber then dumps its whole mass in one frame.
 *
 * Instead each node ramps out over a `window` of ranks around the level, and an
 * absorber's mass is the sum of its subtrees weighted by how absent each child
 * is. Nothing depends on input granularity.
 */
export function continuousResolver(
  model: CoarsenModel,
  { minWindow = 3, relativeWindow = 0.22 }: ContinuousOptions = {},
): ContinuousResolver {
  const subtree = model.subtreeMass;
  const children = childLists(model);
  const rank = new Map<string, number>();
  model.ranked.forEach((id, i) => rank.set(id, i));
  const roots = new Set(model.roots);

  return (level: number) => {
    // The window scales with the level because the dial is geometric: it moves
    // ~level·ln(range) ranks per unit input, so a fixed window smooths the
    // abstract end and does nothing at the detail end, where it moves fastest.
    const span = Math.max(minWindow, level * relativeWindow);
    const presence = new Map<string, number>();
    for (const id of model.ranked) {
      // Local maxima always survive — the same guarantee that keeps every
      // absorber chain terminating on a visible node.
      if (roots.has(id)) {
        presence.set(id, 1);
        continue;
      }
      const r = rank.get(id) ?? 0;
      presence.set(id, Math.max(0, Math.min(1, (level - r) / span)));
    }

    const mass = new Map<string, number>();
    for (const id of model.ranked) {
      let m = 1;
      for (const child of children.get(id) ?? []) {
        m += (1 - (presence.get(child) ?? 0)) * (subtree.get(child) ?? 1);
      }
      mass.set(id, m);
    }
    // Presence is monotone in rank and an absorber always outranks its child,
    // so a child can never be more present than its parent — no orphan can
    // surface out of a folded parent.
    return { mass, presence };
  };
}

/**
 * Where each node is drawn at the current presence.
 *
 * A survivor stays at its authored home. A folding node drifts toward its
 * absorber as it shrinks — `drift = 1 - presence` — so its subtree visibly
 * gathers into the node that now stands for it instead of evaporating in place.
 * The absorber may itself be folding into *its* absorber, so a child follows
 * the whole chain; resolving highest-rank-first means the absorber's display
 * position is final before a child reads it.
 */
export function displayPositions(
  model: CoarsenModel,
  presence: Map<string, number>,
  home: Map<string, readonly [number, number]>,
  ease = 1.8,
): Map<string, [number, number]> {
  const pos = new Map<string, [number, number]>();
  for (const id of model.ranked) {
    const h = home.get(id) ?? [0, 0];
    const parent = model.absorber.get(id);
    // Eased so travel happens while the node is still small: it emerges from
    // its absorber, arrives near home early, then grows into place. A linear
    // drift instead does its fastest sliding at half size, which reads as a
    // lurch (measured at 186 graph-px in a single wheel notch).
    const drift = Math.pow(1 - (presence.get(id) ?? 1), ease);
    if (!parent || drift <= 0) {
      pos.set(id, [h[0], h[1]]);
      continue;
    }
    const p = pos.get(parent) ?? [h[0], h[1]];
    pos.set(id, [
      h[0] + (p[0] - h[0]) * drift,
      h[1] + (p[1] - h[1]) * drift,
    ]);
  }
  return pos;
}

/** Graph-space diameter for a node standing in for `mass` nodes. */
export function massDiameter(
  mass: number,
  unitDiameter: number,
  isLandmark: boolean,
  landmarkBoost = 1.2,
): number {
  // Area ∝ mass keeps total ink constant: Σ mass is the node count at every
  // level, so the map never gets denser or emptier as you turn the dial.
  // Floors at 0, not 1, so a node folding away can shrink to nothing.
  const base = unitDiameter * Math.sqrt(Math.max(0, mass));
  return isLandmark ? base * landmarkBoost : base;
}
