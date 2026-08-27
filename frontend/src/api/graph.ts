/**
 * `/graph` — the read-only map plane.
 *
 * The ambient canvas browses the knowledge graph; it is a database read, not an
 * MCP call. Coordinates arrive from the server (decided 2026-07-27: layout is
 * server-persisted so the map is a stable place, not something each client
 * re-derives). The map payload is skeletal; node bodies load on demand via
 * `fetchNode` → `GET /graph/node`.
 *
 * Backend authority: `graph_read.py`, `mcp_server/graph_http.py`.
 */

import { getJson, postJson } from "./client";
import { readApiConfig } from "./config";

/* `GraphRole` and `MapNode.roles` were removed. The engine still computes
   structural roles and still hands them to the Graph Compass — that consumer is
   real and untouched — but the map read no longer carries them to a client,
   because no client could do anything with "causal_nexus" except print it. */

export type MapNode = {
  id: string;
  label: string;
  /** User-format kind declared by graph.md (paper, topic, claim, ...). */
  kind?: string;
  semantic_anchor: string;
  centrality_score: number;
  is_metanode: boolean;
  linked_graph_id: string;
  token_count: number;
  /**
   * Atom ids this node was built from.
   *
   * The only signal that carries grain. Payload length does not: measured on
   * a real constructed graph, every node's text is 12-88 characters (p50 24),
   * while nodes-per-unit runs 1 to 19 and units-per-node 1 to 21. A node
   * synthesised from twenty passages and one read straight off a sentence
   * look identical without this.
   *
   * Empty on hand-authored graphs and on graphs built before the column.
   */
  source_unit_ids?: string[];
  /**
   * Betweenness, or `null` when the server skipped Brandes on a large cold
   * graph. `null` means UNMEASURED — it is not zero, and must not be used for
   * sizing as though the node were peripheral.
   */
  betweenness: number | null;
  x: number;
  y: number;
  /** Root of this node's spine tree — its region. */
  region_id?: string;
  /** Depth within the region (canonical) or causal layer (causal lens). */
  depth?: number;
  /**
   * The packed first-tier branch this node sits under, where there is one.
   *
   * `region_id` cannot answer this: under a universal corpus root it is that
   * same root for every node in the graph, which is precisely the case where
   * the question matters. Empty when the graph has no packed branches.
   */
  branch_id?: string;
  /**
   * Size band, decided server-side so the client never reconciles
   * `centrality_score` against a nullable `betweenness`. `null` means we could
   * not tell, and must render as a neutral size — never the smallest, which
   * would say "peripheral" about a node nobody measured.
   */
  tier?: "landmark" | "hub" | "leaf" | null;
};

export type LayoutMetrics = {
  crossings: number;
  crossings_sampled: boolean;
  overlap: number;
  aspect: number;
  ink: number;
  nodes: number;
  edges: number;
  delta: number | null;
};

export type MapEdge = {
  source: string;
  target: string;
  type: "LEADSTO" | "CONTAINS" | "EXPRESSES" | "NEARTO";
  label: string;
};

export type GraphMap = {
  graph_id: string;
  graph_version: string;
  /**
   * Identity of the graph's *shape*, and the layout cache key. Unlike
   * `graph_version` (file size + mtime) this only moves when nodes or edges
   * move, which is why the map holds still across cosmetic writes.
   */
  topology_version?: string;
  /** Arrangement this payload was laid out with. */
  lens?: string;
  available_lenses?: string[];
  node_count: number;
  edge_count: number;
  /** `full` = betweenness measured · `fast` = skipped · `none` = unavailable. */
  structural_mode: "full" | "fast" | "none";
  /** Mean node movement since the previous arrangement; null if none to compare. */
  layout_delta?: number | null;
  layout_metrics?: LayoutMetrics;
  /** Isolated material, placed in its own band. Output, not noise. */
  gutter?: string[];
  /**
   * Edges from a packed root to each of its branches, as `[source, target]`.
   *
   * Named by the server because no arrangement can draw them well: a root with
   * 59 branches is a star, and a star into a grid crosses whatever it crosses —
   * on `rfc` these are 59 edges accounting for every one of its crossings. They
   * are structure the operator already knows ("everything hangs off the root"),
   * so they are drawn quietly rather than allowed to dominate the picture.
   */
  spokes?: Array<[string, string]>;
  /** Graph units the layout guarantees between any two node centres. */
  layout_clearance?: number;
  /** Width a node is drawn at, in the same units. */
  node_diameter?: number;
  /**
   * Scaling the map below this crowds nodes. Computed server-side for
   * `node_diameter` × pitch ratio over `layout_clearance`. The client rebases
   * it when Graph DNA draws a different disc size so “as arranged” stays safe.
   */
  min_display_scale?: number;
  nodes: MapNode[];
  edges: MapEdge[];
};

export type GraphSummary = {
  id: string;
  label: string;
  is_current: boolean;
  source: "current" | "published" | "construction" | "example" | "opened";
  /**
   * Which surface this graph belongs on, as opposed to where it was found.
   *
   * `construction` — a construction produced it and nobody has said it is
   * ready. `published` — a person has. `""` — not on this axis at all: a
   * bundled example has nothing to review and no one to publish it, and
   * calling that "unpublished" would file it in a queue it can never leave.
   *
   * Distinct from `source` on purpose. `source` reports how the graph was
   * discovered, and the graph this server currently holds is discovered as
   * `current` wherever it lives — so a list filtered on `source` drops a
   * construction at the exact moment someone opens it.
   */
  state: "construction" | "published" | "";
  workspace_name: string;
  size_bytes: number;
  modified: number;
  /** `null` when the graph could not be opened — it still exists, so it is listed. */
  node_count: number | null;
  edge_count: number | null;
  read_error: string;
};

export type DiscoverEvidenceNode = {
  id: string;
  label: string;
  semantic_anchor?: string;
  anchor_preview?: string;
  origin?: string;
};

/**
 * The focus plane. Focus is an **addition** to the ambient map, never a
 * replacement: an overlay carries node ids, edge references and a role for
 * each, and has no way to express a position. Nothing rendered from an overlay
 * may move a node — that is enforced by the shape, not by discipline.
 *
 * `lit` — the answer stood on this. `frontier` — used, and adjacent to material
 * the answer did not use. Frontier is still evidence: the canvas lights both
 * roles at full intensity. The word names a boundary, not a dimming.
 * `added` / `removed` / `touched` — change review.
 * `ghost` — present in a past version, absent now.
 *
 * Backend: `graph_overlay.py`.
 */
export type OverlayRole =
  | "lit"
  | "frontier"
  | "added"
  | "removed"
  | "touched"
  | "ghost";

export type OverlayGap = {
  type: string;
  names: string;
  context: string;
  suggestion: string;
  /** Present only when the gap named a node that actually exists. */
  anchor?: string;
  anchor_is_evidence?: boolean;
};

export type GraphOverlay = {
  kind: "evidence" | "diff" | "history";
  nodes: Record<string, OverlayRole>;
  /** Keyed `source→target:TYPE`. */
  edges: Record<string, OverlayRole>;
  gaps?: OverlayGap[];
  /**
   * Gaps that named nothing on the map. Listed rather than attached to a
   * plausible neighbour — an invented anchor would fabricate an explanation of
   * why an answer failed.
   */
  unanchored_gaps?: OverlayGap[];
  counts?: Record<string, number>;
};

export function isLiveMode(): boolean {
  return readApiConfig().mode === "live";
}

/* ------------------------------------------------------------------ caches

   Opening a node is the highest-frequency read in the product. It fired two
   uncached requests per click (`/graph/node` and `/graph/sources`) and blanked
   to "Reading body…" every time. These caches end that.

   `topology_version` is the honest invalidation key: it moves only when nodes
   or edges move, which is exactly when a cached node body or map could be
   stale. A cosmetic write (a rename, a nudge) does not move it, so the cache
   survives the writes that did not change anything it holds.

   The map is shared across surfaces for the same reason: Graph and Review both
   read the whole map, and navigating between them refetched it in full.
*/

type NodeContent = { body?: GraphNodeBody; sources?: NodeSources };
const nodeContentCache = new Map<string, NodeContent>();
const mapCache = new Map<string, GraphMap>();
const bodyInflight = new Map<string, Promise<GraphNodeBody>>();
const sourcesInflight = new Map<string, Promise<NodeSources>>();

/** The cache key carries the topology, so a structural write is a miss. */
function nodeContentKey(graphId: string, nodeId: string, topology: string) {
  return `${graphId} ${nodeId} ${topology}`;
}

/** Forget node bodies + maps. Called on `watch:"graph"` invalidation. */
export function invalidateGraphContent() {
  nodeContentCache.clear();
  mapCache.clear();
  bodyInflight.clear();
  sourcesInflight.clear();
}

/**
 * The cached node body + sources, or `null` on a cold miss. Keyed on topology,
 * so an entry written before a structural write is never returned after it.
 */
export function readNodeContent(
  graphId: string,
  nodeId: string,
  topology: string,
): NodeContent | null {
  return nodeContentCache.get(nodeContentKey(graphId, nodeId, topology)) ?? null;
}

/** Warm the cache for a node — used on hover so opening it is instant. */
export function prefetchNodeContent(
  nodeId: string,
  graphId: string,
  topology: string,
) {
  if (!nodeId || !topology) return;
  latestTopology.set(graphId, topology);
  const existing = readNodeContent(graphId, nodeId, topology);
  if (existing?.body && existing?.sources) return;
  if (!existing?.body) void fetchNode(nodeId, graphId).catch(() => undefined);
  if (!existing?.sources) {
    void fetchNodeSources(nodeId, graphId).catch(() => undefined);
  }
}

/** Store one half of a node's content under its topology key. */
function writeNodeContent(
  graphId: string,
  nodeId: string,
  topology: string,
  patch: Partial<NodeContent>,
) {
  if (!topology) return;
  const key = nodeContentKey(graphId, nodeId, topology);
  const entry = nodeContentCache.get(key) ?? {};
  nodeContentCache.set(key, { ...entry, ...patch });
}

const GRAPH_LIST_TTL_MS = 2_000;
let graphListCache: { expiresAt: number; rows: GraphSummary[] } | null = null;
let graphListRequest: Promise<GraphSummary[]> | null = null;

function invalidateGraphList() {
  graphListCache = null;
}

function observeAbort<T>(promise: Promise<T>, signal?: AbortSignal) {
  if (!signal) return promise;
  if (signal.aborted) {
    return Promise.reject(new DOMException("Aborted", "AbortError"));
  }
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => {
      signal.removeEventListener("abort", abort);
    });
  });
}

export function listGraphs(signal?: AbortSignal) {
  if (graphListCache && graphListCache.expiresAt > performance.now()) {
    return observeAbort(Promise.resolve(graphListCache.rows), signal);
  }
  if (!graphListRequest) {
    graphListRequest = getJson<{ graphs: GraphSummary[] }>("/graph/graphs")
      .then((response) => {
        graphListCache = {
          expiresAt: performance.now() + GRAPH_LIST_TTL_MS,
          rows: response.graphs,
        };
        return response.graphs;
      })
      .finally(() => {
        graphListRequest = null;
      });
  }
  return observeAbort(graphListRequest, signal);
}

export type GraphBrowseEntry = {
  name: string;
  path: string;
  size_bytes?: number;
  modified?: number;
};

export type GraphBrowse = {
  path: string;
  /** Empty at the filesystem root. */
  parent: string;
  directories: GraphBrowseEntry[];
  graphs: GraphBrowseEntry[];
};

/**
 * List one directory on the host.
 *
 * The host has to do this: a native file dialog gives JavaScript a `File` and
 * never a path, so a browser cannot tell the server where a graph is even when
 * both are on the same machine. Omit `path` to start beside the open graph.
 */
export function browseGraphs(path = "", signal?: AbortSignal) {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  return getJson<GraphBrowse>(`/graph/browse${query}`, signal);
}

export function openGraph(path: string, signal?: AbortSignal) {
  return postJson<{
    graph: GraphSummary;
    workspace: { name: string; directory: string };
  }>("/graph/open", { path }, signal).then((result) => {
    invalidateGraphList();
    return result;
  });
}

export function activateGraph(graphId: string, signal?: AbortSignal) {
  return postJson<{
    graph: GraphSummary;
    workspace: { name: string; directory: string };
  }>("/graph/activate", { graph_id: graphId }, signal).then((result) => {
    invalidateGraphList();
    return result;
  });
}

/**
 * Mark a construction ready, or withdraw it for another cut.
 *
 * The only write on the graph plane, and it writes no graph. It has no MCP
 * equivalent deliberately: an agent that could mark its own output ready
 * would be ratifying its own work.
 */
export function publishGraph(
  graphId: string,
  published: boolean,
  signal?: AbortSignal,
) {
  return postJson<{ graph_id: string; state: GraphSummary["state"] }>(
    "/graph/publish",
    { graph_id: graphId, published },
    signal,
  ).then((result) => {
    invalidateGraphList();
    return result;
  });
}

/**
 * Omit `graphId` for the graph this server is pointed at.
 *
 * `lens` names a server-computed arrangement (`canonical`, `causal`,
 * `membership`). The browser never lays out; it asks for an arrangement and
 * renders the coordinates it gets back. An unknown *or inapplicable* lens
 * falls back to canonical server-side rather than erroring, so a stale
 * bookmark cannot cost the operator their map — or dump it into a tray.
 */
export function fetchMap(
  graphId?: string,
  signal?: AbortSignal,
  lens?: string,
) {
  const params = new URLSearchParams();
  if (graphId) params.set("graph", graphId);
  if (lens) params.set("lens", lens);
  const q = params.toString();
  const url = `/graph/map${q ? `?${q}` : ""}`;
  return getJson<GraphMap>(url, signal).then((map) => {
    // Shared across surfaces: Graph ↔ Review stops refetching the whole map.
    // The key carries the topology so a structural write misses rather than
    // answering with the map that write replaced. The map's own topology also
    // becomes the key bare node fetches cache under.
    if (map.topology_version) {
      const cacheId = graphId || map.graph_id;
      latestTopology.set(cacheId, map.topology_version);
      mapCache.set(
        `${cacheId}\0${map.lens ?? lens ?? ""}\0${map.topology_version}`,
        map,
      );
    }
    return map;
  });
}

/** The cached map for a graph+lens at a topology, or `null` on a miss. */
export function readCachedMap(
  graphId: string,
  lens: string | undefined,
  topology: string,
): GraphMap | null {
  return mapCache.get(`${graphId} ${lens ?? ""} ${topology}`) ?? null;
}

/**
 * fetchMap that serves the shared cache first.
 *
 * Graph and Review both read the whole map; navigating between them used to
 * refetch it in full. The latest map for a graph (any lens, any topology) is a
 * warm start that lets the surface paint immediately, and the background
 * revalidation in `useResource` replaces it with the authoritative read a
 * moment later — and re-keys it if the topology moved.
 */
export function fetchMapCached(
  graphId: string | undefined,
  signal?: AbortSignal,
  lens?: string,
): Promise<GraphMap> {
  for (const [key, map] of mapCache.entries()) {
    const [cachedId, cachedLens] = key.split("\0");
    const matchesGraph = graphId ? cachedId === graphId : true;
    const matchesLens = graphId
      ? cachedLens === (lens ?? "")
      : lens === undefined || cachedLens === lens;
    if (matchesGraph && matchesLens) {
      return observeAbort(Promise.resolve(map), signal);
    }
  }
  return fetchMap(graphId, signal, lens);
}

/**
 * Late body page-in for the node reader. Map rows stay skeletal (no
 * `text_content`); this is the separate read the projection intentionally
 * deferred.
 */
export type GraphNodeBody = {
  id: string;
  label: string;
  kind?: string;
  semantic_anchor: string;
  text_content: string;
  centrality_score: number;
  is_metanode: boolean;
  linked_graph_id: string;
  token_count: number;
  /** Atom ids this node was built from. Empty on hand-authored graphs. */
  source_unit_ids?: string[];
};

/** One source passage, as the sidecar beside the graph recorded it. */
export type SourceUnit = {
  atom_id: string;
  excerpt: string;
  locator: string;
  heading_path: string[];
  start: number;
  end: number;
  /** The excerpt was cut. Say so; a silent cut reads as the whole passage. */
  truncated: boolean;
};

/**
 * What a node was built from.
 *
 * `available: false` is not an error and not an empty result — it is a graph
 * that cannot resolve its own source ids, which is every graph built before
 * sidecars existed. The reader must say that rather than implying the node
 * came from nowhere.
 */
export type NodeSources = {
  available: boolean;
  reason?: string;
  node_id?: string;
  cited_unit_ids?: string[];
  units: SourceUnit[];
  /** Cited by the node, absent from the sidecar. Named, never silently dropped. */
  unresolved_unit_ids?: string[];
};

export type CoverageUnit = {
  unit_id: string;
  locator: string;
  heading_path: string[];
  excerpt: string;
  node_ids: string[];
  produced: boolean;
};

/** Every source unit in document order, and whether it produced a node. */
export type SourceCoverage = {
  available: boolean;
  reason?: string;
  source_fingerprint?: string;
  unit_count?: number;
  produced_count?: number;
  units: CoverageUnit[];
};

/** The latest topology seen per graph, so bare fetchNode/fetchNodeSources can
 *  cache under the same key the reader looks up with. */
const latestTopology = new Map<string, string>();

function flightKey(graphId: string | undefined, nodeId: string) {
  return `${graphId ?? ""}:${nodeId}`;
}

function rememberTopology(graphId: string | undefined): string | undefined {
  return graphId ? latestTopology.get(graphId) : undefined;
}

export function fetchNodeSources(
  nodeId: string,
  graphId?: string,
  signal?: AbortSignal,
) {
  const topology = rememberTopology(graphId);
  if (graphId && topology) {
    const cached = readNodeContent(graphId, nodeId, topology)?.sources;
    if (cached) return observeAbort(Promise.resolve(cached), signal);
  }
  const key = flightKey(graphId, nodeId);
  let request = sourcesInflight.get(key);
  if (!request) {
    const params = new URLSearchParams({ id: nodeId });
    if (graphId) params.set("graph", graphId);
    request = getJson<NodeSources>(
      `/graph/sources?${params.toString()}`,
    ).then((sources) => {
      const at = rememberTopology(graphId);
      if (graphId && at) writeNodeContent(graphId, nodeId, at, { sources });
      return sources;
    });
    sourcesInflight.set(key, request);
    void request.finally(() => {
      if (sourcesInflight.get(key) === request) sourcesInflight.delete(key);
    });
  }
  return observeAbort(request, signal);
}

export function fetchSourceCoverage(graphId?: string, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (graphId) params.set("graph", graphId);
  const query = params.toString();
  return getJson<SourceCoverage>(
    `/graph/sources${query ? `?${query}` : ""}`,
    signal,
  );
}

export function fetchNode(
  nodeId: string,
  graphId?: string,
  signal?: AbortSignal,
) {
  const topology = rememberTopology(graphId);
  if (graphId && topology) {
    const cached = readNodeContent(graphId, nodeId, topology)?.body;
    if (cached) return observeAbort(Promise.resolve(cached), signal);
  }
  const key = flightKey(graphId, nodeId);
  let request = bodyInflight.get(key);
  if (!request) {
    const params = new URLSearchParams({ id: nodeId });
    if (graphId) params.set("graph", graphId);
    request = getJson<GraphNodeBody>(`/graph/node?${params.toString()}`).then(
      (body) => {
        const at = rememberTopology(graphId);
        if (graphId && at) writeNodeContent(graphId, nodeId, at, { body });
        return body;
      },
    );
    bodyInflight.set(key, request);
    void request.finally(() => {
      if (bodyInflight.get(key) === request) bodyInflight.delete(key);
    });
  }
  return observeAbort(request, signal);
}

/*
 * `discoverGraph` used to live here: POST /graph/discover, one Ask turn.
 *
 * Removed 2026-08-25 with the Ask panel. Ask runs the server-side interpreter
 * this architecture spent the host-agent merge removing -- four retrieval ops
 * and one claim sentence, decided on the server. The product's answer path is
 * an agent composing traversal programs over MCP, where the interpretation is
 * the agent's and the server only executes. A chat box in the map was the
 * weaker predecessor of that, and it is not served over MCP at all.
 *
 * The backend route and `mcp_server/ask.py` are untouched.
 */

export type GraphOrientation = {
  graph_id: string;
  graph_version: string;
  contract_version: string;
  capabilities: string[];
  posture: Record<string, unknown>;
  grain: Record<string, unknown>;
  retrieval: Record<string, unknown>;
  graph_contract?: GraphContractSummary;
  compass_ref: string;
  context_view: "capabilities" | "graph_card" | "full_map";
  [key: string]: unknown;
};

export type TraversalParameterSpec = {
  type: string;
  kinds?: string[];
  required?: boolean;
  [key: string]: unknown;
};

export type TraversalSummary = {
  version: number;
  purpose?: string;
  parameters: Record<string, TraversalParameterSpec>;
  step_count: number;
  limits?: Record<string, number>;
  empty_means?: string;
};

export type GraphContractSummary = {
  available: boolean;
  outcome: string;
  format_id?: string;
  format_version?: number;
  fingerprint?: string;
  review_mode?: string;
  grain_excerpt?: string;
  node_kinds?: string[];
  orientation?: {
    instructions?: string;
    pinned_nodes?: string[];
    default_traversal?: string;
  };
  error?: string;
  required_traversals?: Array<{
    recipe: string;
    when_kinds?: string[];
    parameter?: string;
  }>;
  traversals?: Record<string, TraversalSummary>;
};

export type TraversalEvidenceNode = {
  id: string;
  label: string;
  kind?: string;
  origin?: string;
  /**
   * This row is part of the recipe's declared answer, not context around it.
   *
   * A packet carries both: `collect` decides what comes back, `answers`
   * decides which of it was asked for. Measured on the narrative demo, a
   * five-node packet carried four answer rows and one seed — drawing those
   * alike says the seed was part of the finding.
   */
  is_answer?: boolean;
  entered_via?: {
    variable: string;
    tool: string;
    phase: string;
    step: number;
  };
};

export type TraversalOperation = {
  phase: string;
  tool: string;
  assign_to: string;
  result_count: number;
  elapsed_ms: number;
  requested_count?: number;
  resolve_miss_count?: number;
};

export type NamedTraversalResult = {
  kind: string;
  outcome: "FOUND" | "EMPTY" | "EXACT_MISS" | "INVALID_RECIPE" | string;
  graph_version: string;
  recipe?: {
    name: string;
    version: number;
    fingerprint: string;
    format_fingerprint: string;
    parameters: Record<string, unknown>;
  };
  evidence?: {
    node_records?: TraversalEvidenceNode[];
    edge_records?: Array<Record<string, unknown>>;
    path_records?: Array<Record<string, unknown>>;
  };
  execution_receipt?: {
    operations?: TraversalOperation[];
    graph_version?: string;
    packet_node_count?: number;
    packet_edge_count?: number;
    elapsed_ms?: number;
    result_fingerprint?: string;
    contingency_triggered?: boolean;
    [key: string]: unknown;
  };
  /** Ids of the variables the recipe declared as its answer. Absent when it
   *  declared none, which is not the same as an empty answer. */
  answer_node_ids?: string[];
  overlay?: GraphOverlay;
  membership?: Record<string, string[]>;
  why_entered?: Record<
    string,
    { variable: string; tool: string; phase: string; step: number }
  >;
  errors?: unknown[];
};

export function runNamedTraversal(
  graphId: string,
  name: string,
  parameters: Record<string, unknown>,
  options?: { version?: number; graphVersion?: string; signal?: AbortSignal },
) {
  return postJson<NamedTraversalResult>(
    "/graph/run-traversal",
    {
      graph_id: graphId,
      name,
      parameters,
      version: options?.version,
      graph_version: options?.graphVersion,
    },
    options?.signal,
  );
}

export function orientGraph(
  graphId?: string,
  context: "capabilities" | "graph_card" | "full_map" = "graph_card",
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ context });
  if (graphId) params.set("graph", graphId);
  return getJson<GraphOrientation>(`/graph/orient?${params.toString()}`, signal);
}

/*
 * `whatGovernsGraph` and `checkGraphConformance` used to live here.
 *
 * Removed 2026-08-25: nothing in the frontend had ever called either. They
 * are the governance product's two verbs, and this frontend is a reader for
 * the graph product -- the agent asks questions through MCP traversal, not
 * through a coverage verdict rendered in a panel.
 *
 * The backend still serves `/graph/what-governs` and `/graph/check-conformance`
 * and they keep their tests. This deletes the wiring, not the capability.
 */
