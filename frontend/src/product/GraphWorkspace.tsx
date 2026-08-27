/**
 * Graph map — load a real committed graph and look at it.
 *
 * A place to pick one of the graphs this server holds (the operator's own, plus
 * anything the construction wizard published) and read it. Separate from
 * `AmbientCanvasLabPage` on purpose: that one is the design surface and is being
 * reworked; this one owns the data path, so the two can merge once the visual
 * language is settled rather than fighting over one file mid-flight.
 *
 * Design language (executable-design-constraints §1.5, §3.1): **geometry states
 * truth, not colour**. Nothing here is coloured.
 *
 * Edge type follows the ambient canvas's LINKAGE-IDLE look rather than painting
 * every kind on permanently:
 *
 *   at rest    every edge is a plain filament, weight by kind, no arrowheads
 *   on hover   the edges touching that node declare themselves — arrowheads on
 *              the directed kinds (CONTAINS, LEADSTO, EXPRESSES) and a kind
 *              chip on all
 *
 * A map where every edge shouts its type is noise; the type only matters once
 * you are asking about a particular node, so asking is what reveals it. NEARTO
 * never gets an arrowhead because it is the one symmetric edge type.
 *
 * Nodes are equal matter at the ambient level; structural role is reported in
 * the inspect panel rather than painted. Unequal mass belongs to the separate
 * regional LOD experiment, where abstraction has an explicit zoom meaning.
 * Coordinates still come from the server: manipulation is local and no browser
 * layout silently replaces the persisted map.
 */

import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import {
  fetchMapCached,
  activateGraph,
  orientGraph,
  isLiveMode,
  listGraphs,
  prefetchNodeContent,
  publishGraph,
  type NamedTraversalResult,
  type GraphOverlay,
  type GraphSummary,
  type MapNode,
} from "../api/graph";
import { ApiError } from "../api/client";
import { useResource } from "../api/resource";
import {
  fetchProposal,
  fetchVersionDiff,
  useWriteCheckpoints,
  type ProposalVM,
  type VersionDiff,
  type WriteCheckpoint,
} from "../api/ledger";
import { readHashSeamParams } from "../explorations/lab/platformCoreScenario";
import { edgeDisplayLabel } from "../shared/protocolVocabulary";
import {
  ProductGraphCanvas,
  type NudgeState,
  type ProductGraphMode,
} from "./ProductGraphCanvas";
import {
  dimmableSpokes,
  displayPositions,
  proposalPositions,
  spokeKey,
} from "./graphModel";
import {
  onGraphPrefsChange,
  readGraphPrefs,
  type GraphPrefs,
} from "./graphPrefs";
import NodeFinder from "./NodeFinder";
import { NodeReaderPanel } from "./NodeReaderPanel";
import { OverlayPanel } from "./OverlayPanel";
import { TraversalMenu } from "./TraversalMenu";
import { readStoredPanelSize, storePanelSize } from "./ResizableDivider";
import { useHeld, usePresence } from "../styles/usePresence";
import { Swap } from "../styles/Swap";
import "../styles/presence.css";
import {
  Instrument,
  InstrumentGroup,
  InstrumentReadings,
  ShellAction,
  useActiveSurface,
  useProductTheme,
  useProvisionalSurface,
} from "./ProductShell";
import {
  NoticeCard,
  NoticeSurface,
  faultOf,
  useBoundNotice,
  type NoticeKind,
} from "./Notice";
import {
  OVERLAY_RANK,
  useDismissableLayer,
  useOverlayChrome,
} from "./overlayChrome";
import { useGraphDnaRuntime } from "./graphDnaRuntime";
import { WriteTimeline } from "./WriteTimeline";
import "./GraphWorkspace.css";

const PICKER_OPEN_KEY = "graphauthor.graphPickerOpen";
const READER_WIDTH_KEY = "graphauthor.nodeReaderWidth";

function readPickerOpen(): boolean {
  try {
    const raw = window.localStorage.getItem(PICKER_OPEN_KEY);
    if (raw === null) return true;
    return raw === "1" || raw === "true";
  } catch {
    return true;
  }
}

function storePickerOpen(open: boolean) {
  try {
    window.localStorage.setItem(PICKER_OPEN_KEY, open ? "1" : "0");
  } catch {
    /* open/close still works when storage is unavailable */
  }
}

function hashParam(name: string): string | undefined {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  if (q < 0) return undefined;
  return new URLSearchParams(hash.slice(q + 1)).get(name) ?? undefined;
}

/** Kept in the URL so an arrangement can be linked to, not just reached. */
function setHashParam(name: string, value: string | undefined) {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const base = q < 0 ? hash : hash.slice(0, q);
  const params = new URLSearchParams(q < 0 ? "" : hash.slice(q + 1));
  if (value) params.set(name, value);
  else params.delete(name);
  const suffix = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${base}${suffix ? `?${suffix}` : ""}`,
  );
}

/**
 * Arrangements, in product words. The server decides which are *offered* —
 * `applicable_lenses` withholds a lens that has nothing to say about a graph,
 * because an operator who switches to one and sees the whole map dumped into a
 * band learns that the control is broken. So the client renders what it is
 * given. Applicability is the server's; the client only drops a requested
 * lens the payload did not offer, so a stale bookmark cannot keep asking
 * for a tray.
 */
const LENS_LABELS: Record<string, string> = {
  canonical: "Structure",
  causal: "Cause",
  membership: "Belonging",
};

const LENS_HINTS: Record<string, string> = {
  canonical: "What is in this graph?",
  causal: "Where does this lead?",
  membership: "Who belongs to what?",
};

/**
 * Nodes the current arrangement sat out of the reading. The band is the
 * product: orphans, non-causal material, non-members. A number with no
 * sentence would look like a packing leftover.
 */
function gutterReading(
  lens: string | undefined,
  count: number,
): { text: string; title: string } {
  if (lens === "causal") {
    return {
      text: `${count} not in the flow`,
      title:
        "These have no lead-to relation, so they sit out of this arrangement.",
    };
  }
  if (lens === "membership") {
    return {
      text: `${count} not in a group`,
      title:
        "These do not belong to the membership this arrangement is reading.",
    };
  }
  return {
    text: `${count} isolated`,
    title:
      "Nothing in the graph connects these. They sit in the gutter — output, not noise.",
  };
}

function lensLabel(lens: string): string {
  return LENS_LABELS[lens] ?? lens;
}


/**
 * What the map is currently paying attention to, and who asked for it.
 *
 * There is one of these at a time, on purpose. Ledger links from Logs and an
 * answer's evidence used to light at once as a union nobody had asked about,
 * with a Clear that only cleared one of them. They are different questions, so
 * the later one replaces the earlier rather than joining it.
 *
 * Finding a node is not a focus. It is a select-and-fly, the same jump a
 * neighbour-strip row already does, so it never joins this overlay.
 *
 * `source` also gives the banner something true to say. "Focus · 4 nodes" is
 * the same sentence whether those nodes are an answer's evidence or a ledger
 * subject, and those are not the same claim.
 */
type FocusSource = "ledger" | "answer" | "traversal";

type Focus = {
  ids: string[];
  /**
   * The node the focus radiated out from, when there is one.
   *
   * An answer's evidence is a set with no centre. When a focus does have one,
   * only the edges that reach it light — not every edge a neighbour happens
   * to have, including ones leaving the set entirely.
   */
  origin?: string;
  source: FocusSource;
  /** Short phrase naming the subject: a verdict, a node, an activity. */
  label: string;
  /** Roles the engine already computed. Honoured instead of a flat id list. */
  overlay?: GraphOverlay;
  /** When set, only this trail is lit — a citation, not the whole answer. */
  trailKey?: string;
  /**
   * The subset of `ids` that answers the question, as opposed to the context
   * retrieved alongside it.
   *
   * Focus was two tiers, lit and dim. A traversal packet is three things: the
   * answer, the context it was found through, and the rest of the graph.
   * Collapsing the first two is the same mistake as collapsing UNGOVERNED
   * with INSUFFICIENT — it reports more certainty than the result carries.
   */
  answerIds?: string[];
};

const FOCUS_HEADING: Record<FocusSource, string> = {
  ledger: "Logs",
  answer: "Evidence",
  traversal: "Traversal",
};


function overlayEdgeKey(source: string, target: string, type: string): string {
  return `${source}→${target}:${type}`;
}

/** Patch the hash the same way Logs → Graph does for a recorded write. */
function writeHashSeamFocus(focusIds: string[] | null) {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const base = q < 0 ? hash : hash.slice(0, q);
  const params = new URLSearchParams(q < 0 ? "" : hash.slice(q + 1));
  if (focusIds?.length) {
    params.set("seam", "focus");
    params.set("focus", focusIds.join(","));
  } else {
    params.delete("seam");
    params.delete("focus");
    params.delete("activity");
    params.delete("proposal");
    params.delete("gap");
    params.delete("from");
    params.delete("to");
    params.delete("gv");
    params.delete("return");
  }
  const suffix = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${base}${
      suffix ? `?${suffix}` : ""
    }`,
  );
}

function writeHashSeamDiff(row: WriteCheckpoint) {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const base = q < 0 ? hash : hash.slice(0, q);
  const params = new URLSearchParams(q < 0 ? "" : hash.slice(q + 1));
  params.set("seam", "diff");
  params.set("return", "log");
  params.set("activity", row.id);
  if (row.subjects.length) params.set("focus", row.subjects.join(","));
  else params.delete("focus");
  if (row.proposalId) params.set("proposal", row.proposalId);
  else params.delete("proposal");
  if (row.from) params.set("from", row.from);
  else params.delete("from");
  if (row.to) params.set("to", row.to);
  else params.delete("to");
  const suffix = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${base}${
      suffix ? `?${suffix}` : ""
    }`,
  );
}

export function GraphWorkspace({
  productMode = false,
  constructionMode = false,
}: {
  productMode?: boolean;
  /**
   * The same map, over the graphs nobody has published yet.
   *
   * Not a second workspace and not a wizard: a construction is a graph, the
   * only honest thing to do with one is look at it, and this surface already
   * knows how. What changes is the shelf it reads from and that the map is
   * visibly provisional — a construction that rendered identically to a
   * published graph would be indistinguishable from one, which is the whole
   * failure this separation exists to prevent.
   *
   * Everything that *changes* a construction happens in the agent session.
   * There is no source pane and no rebuild button here, because the server
   * does not own the program that builds these graphs.
   */
  constructionMode?: boolean;
} = {}) {
  const theme = useProductTheme();
  const activeSurface = useActiveSurface();
  const graphOnScreen = activeSurface === "graph";
  const { setProvisional } = useProvisionalSurface();
  const { setFocused: setChromeFocused, setHidden: setChromeHidden } =
    useOverlayChrome();
  const dnaRuntime = useGraphDnaRuntime();
  const live = useMemo(() => isLiveMode(), []);
  const [linkage, setLinkage] = useState(() => readHashSeamParams());
  const requestedGraph = useMemo(() => hashParam("graph"), []);
  const [focus, setFocus] = useState<Focus | null>(null);
  // Published by the canvas: which nodes have been pulled aside by hand, and
  // the operations available over them.
  const [nudges, setNudges] = useState<NudgeState | null>(null);
  // Memoised on `focus`, not derived inline. A fresh `[]` on every render made
  // `canvasModel` recompute every render, which handed the canvas a new `data`
  // object, which counted as a data change, which republished the nudge state,
  // which set state here — a render loop that React eventually killed with
  // "Maximum update depth exceeded", taking pan and node-drag down with it.
  const focusIds = useMemo(() => focus?.ids ?? [], [focus]);
  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [listed, setListed] = useState(false);
  const [selected, setSelected] = useState<string | undefined>();
  const [sceneReady, setSceneReady] = useState(false);
  const [lens, setLens] = useState<string | undefined>(() => hashParam("lens"));
  const [catalogueFault, setCatalogueFault] = useState<{
    kind: NoticeKind;
    body: string;
  } | null>(null);
  const [verbFault, setVerbFault] = useState<{
    kind: NoticeKind;
    body: string;
  } | null>(null);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  const [inspected, setInspected] = useState<MapNode | null>(null);
  /**
   * A node the reader named from off the disc — neighbour strip, named chip,
   * or Find. The canvas flies to it; a click on a disc must not, because that
   * node is already under the pointer.
   */
  const [followId, setFollowId] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState("");
  const [proposal, setProposal] = useState<ProposalVM | null>(null);
  const [versionDiff, setVersionDiff] = useState<VersionDiff | null>(null);
  const [pickerOpen, setPickerOpen] = useState(() => readPickerOpen());
  /**
   * The reader stays mounted through absorb so the drawer can leave. Presence
   * is the same primitive OverlayPanel uses to park on enter — a copied 320ms
   * timeout was a second clock for one law.
   */
  const readerPresence = usePresence(Boolean(inspected));
  const readerNode = useHeld(inspected, readerPresence.mounted);
  const [readerWidth, setReaderWidth] = useState(() =>
    readStoredPanelSize(READER_WIDTH_KEY, 420),
  );
  const [traversalOpen, setTraversalOpen] = useState(false);
  // Display preferences live in the browser and can change from Settings while
  // this page is mounted, so the page listens rather than reading once.
  const [prefs, setPrefs] = useState<GraphPrefs>(() => readGraphPrefs());

  useEffect(() => onGraphPrefsChange(setPrefs), []);


  useEffect(() => {
    const sync = () => setLinkage(readHashSeamParams());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    storePickerOpen(pickerOpen);
  }, [pickerOpen]);

  useEffect(() => {
    const hash = window.location.hash;
    if (!hash.startsWith("#/construct")) return;
    const query = hash.includes("?") ? hash.slice(hash.indexOf("?")) : "";
    window.history.replaceState(null, "", `#/graph${query}`);
  }, []);

  useEffect(() => {
    storePanelSize(READER_WIDTH_KEY, readerWidth);
  }, [readerWidth]);

  useEffect(() => {
    setPreviewId(null);
  }, [inspected]);

  // Escape order lives in `overlayChrome.tsx`, not in a chain here. This page
  // used to own it, which meant every new overlay anywhere in the product had
  // to be added to an `if` ladder in this file or silently miss out.
  // Escape clears the selection. The name is at the top of the column; a
  // closed reader has no tab to reopen, so you pick a node again.
  useDismissableLayer(Boolean(inspected), OVERLAY_RANK.reader, () =>
    setInspected(null),
  );
  useDismissableLayer(pickerOpen, OVERLAY_RANK.drawer, () =>
    setPickerOpen(false),
  );

  // The hash seam is how Review hands this page a subject. It is the only focus
  // that has to survive a navigation, so it is the only one kept in the URL —
  // an answer's evidence belongs to this session.
  useEffect(() => {
    const ids = [...new Set(linkage.focus ?? [])];
    if (ids.length) {
      setFocus({
        ids,
        source: "ledger",
        label: linkage.activity ? String(linkage.activity) : "",
      });
      return;
    }
    setFocus((current) => (current?.source === "ledger" ? null : current));
  }, [linkage.activity, linkage.focus]);

  useEffect(() => {
    if (!live) return;
    const abort = new AbortController();
    listGraphs(abort.signal)
      .then(async (initialRows) => {
        if (abort.signal.aborted) return;
        let rows = initialRows;
        const requested = rows.find((row) => row.id === requestedGraph);
        if (productMode && requested && !requested.is_current) {
          await activateGraph(requested.id, abort.signal);
          rows = await listGraphs(abort.signal);
        }
        if (abort.signal.aborted) return;
        setGraphs(rows);
        setListed(true);
        setCatalogueFault(null);
        const published = rows.filter((r) => r.state !== "construction");
        const constructions = rows.filter((r) => r.state === "construction");
        const shelved = constructionMode ? constructions : published;
        setSelected(
          (cur) =>
            cur ??
            requested?.id ??
            shelved.find((r) => r.is_current && (r.node_count ?? 0) > 0)?.id ??
            shelved.find((r) => (r.node_count ?? 0) > 0)?.id ??
            shelved.find((r) => r.is_current)?.id ??
            shelved[0]?.id,
        );
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        const fault = faultOf(e, "Could not list graphs.");
        if (fault) setCatalogueFault(fault);
      });
    return () => abort.abort();
  }, [live, productMode, constructionMode, requestedGraph]);

  // The map is a read of graph state, so a write anywhere in the product
  // refreshes it. Before this, confirming a proposal on Review left this page
  // showing the version that confirm had just replaced, until a reload.
  const mapRead = useResource(
    async (signal) => {
      const ask = `${selected ?? ""}\0${lens ?? ""}`;
      const payload = await fetchMapCached(selected, signal, lens);
      return { ask, payload };
    },
    {
      enabled: live && Boolean(selected),
      deps: [selected, lens],
      watch: "graph",
      fallbackError: "Could not read the map.",
    },
  );
  const map = mapRead.data?.payload ?? null;
  const loading = mapRead.loading;
  const placeError =
    (mapRead.hostUnreachable ? "" : mapRead.error) || canvasError;
  useBoundNotice(
    "map",
    graphOnScreen && catalogueFault
      ? {
          slot: "block",
          kind: catalogueFault.kind,
          title: "The catalogue could not be read",
          body: catalogueFault.body,
        }
      : graphOnScreen && placeError
        ? {
            slot: "block",
            kind: "unavailable",
            title: "The map could not be read",
            body: placeError,
          }
        : null,
  );
  useBoundNotice(
    "verb",
    graphOnScreen && verbFault
      ? {
          slot: "dock",
          kind: verbFault.kind,
          title: "That did not complete",
          body: verbFault.body,
          dismissible: true,
        }
      : null,
  );
  const gutterCount = useMemo(() => {
    if (!map?.gutter?.length) return 0;
    const onMap = new Set(map.nodes.map((node) => node.id));
    return map.gutter.filter((id) => onMap.has(id)).length;
  }, [map]);
  const orientationRead = useResource(
    (signal) => orientGraph(selected, "graph_card", signal),
    {
      enabled: live && Boolean(selected),
      deps: [selected],
      watch: "graph",
      fallbackError: "Could not read the graph contract.",
    },
  );
  const graphContract = orientationRead.data?.graph_contract;
  const namedTraversals =
    graphContract?.available && graphContract.traversals
      ? graphContract.traversals
      : {};


  // A bookmark can name a lens this graph has nothing to say with. The
  // server already fell back; staying on the request would keep asking for
  // the tray, and would spring that lens on the next graph that does offer it.
  useEffect(() => {
    if (!map || !lens) return;
    const offered = map.available_lenses ?? [];
    if (offered.length > 0 && !offered.includes(lens)) {
      setLens(undefined);
      setHashParam("lens", undefined);
    }
  }, [map, lens]);

  useEffect(() => {
    setInspected(null);
    setFollowId(null);
    setTraversalOpen(false);
  }, [selected]);

  useEffect(() => {
    const proposalId = linkage.proposal;
    if (!live || !proposalId) {
      setProposal(null);
      return;
    }
    const abort = new AbortController();
    fetchProposal(proposalId, abort.signal)
      .then((record) => {
        if (!abort.signal.aborted) {
          setProposal(
            record.status === "COMMITTED" || record.status === "REJECTED"
              ? null
              : record,
          );
        }
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        const fault = faultOf(e, "Could not read the proposal overlay.");
        if (fault) setVerbFault(fault);
      });
    return () => abort.abort();
  }, [linkage.proposal, live]);

  useEffect(() => {
    const before = linkage.from;
    const after = linkage.to;
    if (
      !live ||
      linkage.seam !== "diff" ||
      typeof before !== "string" ||
      typeof after !== "string" ||
      before === after
    ) {
      setVersionDiff(null);
      return;
    }
    const abort = new AbortController();
    fetchVersionDiff(before, after, abort.signal)
      .then((diff) => {
        if (!abort.signal.aborted) setVersionDiff(diff);
      })
      .catch((reason: unknown) => {
        if (abort.signal.aborted) return;
        const fault = faultOf(reason, "Could not read the recorded version diff.");
        if (fault) setVerbFault(fault);
      });
    return () => abort.abort();
  }, [linkage.from, linkage.seam, linkage.to, live]);

  const writeCheckpoints = useWriteCheckpoints(live && productMode ? 15_000 : 0);
  const selectedWriteId = useMemo(() => {
    const activity = String(linkage.activity ?? "");
    if (activity && writeCheckpoints.some((row) => row.id === activity)) {
      return activity;
    }
    if (linkage.seam === "diff" && linkage.from && linkage.to) {
      const match = writeCheckpoints.find(
        (row) =>
          row.from === String(linkage.from) && row.to === String(linkage.to),
      );
      return match?.id ?? null;
    }
    return null;
  }, [linkage.activity, linkage.from, linkage.seam, linkage.to, writeCheckpoints]);

  const canvasModel = useMemo(() => {
    if (!map) return null;
    const mapIds = new Set(map.nodes.map((node) => node.id));
    const committedPositions = displayPositions(
      map,
      dnaRuntime?.params.spacing ?? prefs.spacing,
    );
    const positions = proposal
      ? proposalPositions(map, proposal, committedPositions)
      : new Map();
    const ghostNodes =
      proposal?.nodes.filter((node) => positions.has(node.id)) ?? [];
    const diffApplies =
      Boolean(versionDiff) && String(linkage.to ?? "") === map.graph_version;
    const addedIds = new Set(
      diffApplies ? versionDiff!.nodes_added.map((node) => node.id) : [],
    );
    const removedNodes = diffApplies
      ? versionDiff!.nodes_removed.filter((node) => !mapIds.has(node.id))
      : [];
    const removedIds = new Set(
      diffApplies ? versionDiff!.nodes_removed.map((node) => node.id) : [],
    );
    const touchedIds = new Set(
      diffApplies ? versionDiff!.nodes_changed.map((node) => node.id) : [],
    );
    const diffIds = new Set([...addedIds, ...removedIds, ...touchedIds]);
    const committedCenter = [...committedPositions.values()].reduce(
      (center, position) => ({
        x: center.x + position.x / Math.max(1, committedPositions.size),
        y: center.y + position.y / Math.max(1, committedPositions.size),
      }),
      { x: 0, y: 0 },
    );
    const removedPositions = new Map(
      removedNodes.map((node, index) => {
        const angle =
          -Math.PI / 2 +
          (index * Math.PI * 2) / Math.max(3, removedNodes.length);
        return [
          node.id,
          {
            x: committedCenter.x + Math.cos(angle) * 180,
            y: committedCenter.y + Math.sin(angle) * 180,
          },
        ];
      }),
    );
    const allNodeIds = new Set([
      ...mapIds,
      ...ghostNodes.map((node) => node.id),
      ...removedNodes.map((node) => node.id),
    ]);
    const visibleFocusIds = [
      ...new Set([
        ...focusIds,
        ...ghostNodes.map((node) => node.id),
        ...diffIds,
      ]),
    ].filter((id) => allNodeIds.has(id));
    const focusSet = new Set(visibleFocusIds);
    /**
     * Which edges the focus lights.
     *
     * With an origin, only the edges that reach it. Those are the ones the
     * focus is *about*; an edge between two of its neighbours is a fact about
     * them.
     *
     * Without one — an answer's evidence — the origin does not exist, so the
     * rule is both ends lit: the subgraph the evidence actually spans. Either
     * way it is an `&&`, where it used to be an `||` that reached one hop
     * further than the focus it was drawn from.
     */
    const focusOrigin = focus?.origin ?? "";
    const trailFocus = Boolean(focus?.trailKey);
    const overlayEdges = focus?.overlay?.edges;
    const overlayNodes = focus?.overlay?.nodes;
    const overlayLightsEdge = (src: string, tgt: string, type: string) => {
      if (!overlayEdges || !Object.keys(overlayEdges).length) return null;
      const types = [type, type.toUpperCase(), type.toLowerCase()];
      for (const t of types) {
        if (
          overlayEdges[overlayEdgeKey(src, tgt, t)] ||
          overlayEdges[overlayEdgeKey(tgt, src, t)]
        ) {
          return true;
        }
      }
      return false;
    };
    const overlayHitsOnMap = overlayEdges
      ? map.edges.some((edge) =>
          overlayLightsEdge(edge.source, edge.target, edge.type),
        )
      : false;
    const litEdge = (src: string, tgt: string, type: string) => {
      if (focusOrigin) return src === focusOrigin || tgt === focusOrigin;
      if (!trailFocus && overlayHitsOnMap) {
        return overlayLightsEdge(src, tgt, type) === true;
      }
      return focusSet.has(src) && focusSet.has(tgt);
    };
    const nodeIntensity = (id: string) => {
      if (trailFocus) return focusSet.has(id) ? 1 : 0;
      // Frontier nodes are still evidence — used by the answer, and adjacent
      // to material it did not use. Drawing them below the lit threshold made
      // nine of eleven evidence nodes look like context. Both roles light.
      if (overlayNodes?.[id]) return 1;
      return focusSet.has(id) ? 1 : 0;
    };
    const mode: ProductGraphMode = proposal
      ? "proposal"
      : diffApplies
        ? "diff"
      : visibleFocusIds.length
        ? "focus"
        : "ambient";
    const edgeKey = (
      type: string,
      source: string,
      target: string,
      label = "",
    ) => `${type}:${source}:${target}:${label}`;
    const spokeKeys = prefs.dimSpokes ? dimmableSpokes(map) : new Set<string>();
    const addedEdges = new Set(
      diffApplies
        ? versionDiff!.edges_added.map(([type, source, target, label]) =>
            edgeKey(type, source, target, label),
          )
        : [],
    );

    return {
      mode,
      frameIds: visibleFocusIds,
      data: {
        nodes: [
          ...map.nodes.map((node) => ({
            id: node.id,
            style: committedPositions.get(node.id),
            data: {
              ...node,
              label: node.label || node.id,
              proposed: false,
              intensity: nodeIntensity(node.id),
              diff: addedIds.has(node.id)
                ? "added"
                : touchedIds.has(node.id)
                  ? "touched"
                  : "unchanged",
            },
          })),
          ...ghostNodes.map((node) => ({
            id: node.id,
            style: positions.get(node.id),
            data: {
              ...node,
              label: node.label || node.id,
              semantic_anchor: node.semantic_anchor ?? "",
              proposed: true,
              intensity: 1,
            },
          })),
          ...removedNodes.map((node) => ({
            id: node.id,
            style: removedPositions.get(node.id),
            data: {
              ...node,
              semantic_anchor: "Absent from the later committed version.",
              proposed: false,
              intensity: 1,
              diff: "removed",
            },
          })),
        ],
        edges: [
          ...map.edges.map((edge, index) => ({
            id: `e${index}`,
            source: edge.source,
            target: edge.target,
            data: {
              type: edge.type,
              kind: edge.type.toLowerCase(),
              // Predicate is the name. SST rides beside it only when the
              // operator asked to see the geometry type on the map.
              label: edgeDisplayLabel(edge.type, edge.label, {
                includeType: prefs.edgeTypeLabels,
              }),
              proposed: false,
              intensity: diffApplies
                ? addedEdges.has(
                    edgeKey(edge.type, edge.source, edge.target, edge.label),
                  )
                  ? 1
                  : 0
                : litEdge(edge.source, edge.target, edge.type)
                  ? 1
                  : 0,
              diff: addedEdges.has(
                edgeKey(edge.type, edge.source, edge.target, edge.label),
              )
                ? "added"
                : "unchanged",
              lens: 0,
              // Named by the server as an edge no arrangement can draw well —
              // see `spokeDimOf`. Not a style decision made here: which edges
              // are structural noise is a fact about the layout.
              spoke: spokeKeys.has(spokeKey(edge.source, edge.target)),
              _lp: 0.5,
              _bond: 0,
              _bondSide: "source",
            },
          })),
          ...(proposal?.edges ?? [])
            .filter(
              (edge) =>
                allNodeIds.has(edge.source_id) &&
                allNodeIds.has(edge.target_id),
            )
            .map((edge, index) => ({
              id: `proposal-${index}`,
              source: edge.source_id,
              target: edge.target_id,
              data: {
                type: edge.type,
                kind: edge.type.toLowerCase(),
                label: edgeDisplayLabel(
                  edge.type,
                  edge.predicate || edge.label,
                  { includeType: prefs.edgeTypeLabels },
                ),
                proposed: true,
                intensity: 1,
                lens: 0,
                _lp: 0.5,
                _bond: 0,
                _bondSide: "source",
              },
            })),
          ...(diffApplies ? versionDiff!.edges_removed : [])
            .filter(([, source, target]) =>
              allNodeIds.has(source) && allNodeIds.has(target),
            )
            .map(([type, source, target, label], index) => ({
              id: `removed-${index}`,
              source,
              target,
              data: {
                type,
                kind: type.toLowerCase(),
                label: edgeDisplayLabel(type, label, {
                  includeType: prefs.edgeTypeLabels,
                }),
                proposed: false,
                intensity: 1,
                diff: "removed",
                lens: 0,
                _lp: 0.5,
                _bond: 0,
                _bondSide: "source",
              },
            })),
        ],
      },
    };
  }, [dnaRuntime?.params.spacing, focus, focusIds, linkage.to, map, prefs, proposal, versionDiff]);

  const askedLens = lens ?? map?.lens ?? "canonical";
  // Catalogue ids are not `map.graph_id`. Duplicate file stems (every demo
  // workbook writes `graph.lbug`) get a path-hash suffix in the catalogue;
  // the map endpoint stamps the stem. The fetch records the id it asked with
  // so this veil can lift without those two names agreeing.
  const askKey = `${selected ?? ""}\0${lens ?? ""}`;
  const mapMatchesAsk = Boolean(map) && mapRead.data?.ask === askKey;
  const [waitExpired, setWaitExpired] = useState(false);
  useLayoutEffect(() => {
    setSceneReady(false);
  }, [selected, lens]);
  useEffect(() => {
    setWaitExpired(false);
  }, [askKey]);
  useEffect(() => {
    const blocked =
      live &&
      Boolean(selected) &&
      !placeError &&
      !mapRead.hostUnreachable &&
      (switching || !mapMatchesAsk || !sceneReady);
    if (!blocked || waitExpired) return;
    const timer = window.setTimeout(() => setWaitExpired(true), 10_000);
    return () => window.clearTimeout(timer);
  }, [
    live,
    mapMatchesAsk,
    mapRead.hostUnreachable,
    placeError,
    sceneReady,
    selected,
    switching,
    waitExpired,
  ]);
  const waitingMap =
    live &&
    Boolean(selected) &&
    !placeError &&
    !mapRead.hostUnreachable &&
    !waitExpired &&
    (switching || !mapMatchesAsk || !sceneReady);
  const waitingPresence = usePresence(waitingMap);
  const heldAsk = mapRead.data?.ask ?? "";
  const heldGraph = heldAsk.slice(0, Math.max(0, heldAsk.indexOf("\0")));
  const waitingLabel =
    switching || (heldGraph && selected && heldGraph !== selected)
      ? "Opening…"
      : lens &&
          (heldAsk !== askKey ||
            (map && (map.lens ?? "canonical") !== askedLens))
        ? "Arranging…"
        : "Reading the map…";

  /**
   * Publish the canvas's reading state to the shell.
   *
   * The canvas has always inverted its field whenever it is showing a subject
   * rather than the ambient map (`inverted = mode !== "ambient"`), and nothing
   * outside the canvas knew. So the map went dark while every panel standing on
   * it — and the shell bar floating over it — stayed in the page theme, putting
   * one reading state on screen in two palettes. Ask now reads `--ink` /
   * `--canvas`, which this effect remaps onto the focus scale when the map
   * inverts, so an empty Ask in light is gray 12 on gray 1, not grayDark 12
   * on a mid-grey frost.
   */
  const focusedField = Boolean(canvasModel && canvasModel.mode !== "ambient");
  useLayoutEffect(() => {
    setChromeFocused(graphOnScreen && focusedField);
    return () => setChromeFocused(false);
  }, [focusedField, graphOnScreen, setChromeFocused]);
  useLayoutEffect(() => {
    if (!graphOnScreen) setChromeHidden(false);
  }, [graphOnScreen, setChromeHidden]);

  // The selected graph's own row is what named it in the bar; the library rail
  // and the product header both still do, so nothing here needs to look it up.
  // A ledger link can name nodes this graph does not have — it was written
  // against a version, and versions lose nodes. The other two sources filter
  // against the open map before they ever set a focus, so this only ever
  // reports on a link that arrived from elsewhere.
  const committedFocusCount = map
    ? focusIds.filter((id) => map.nodes.some((node) => node.id === id)).length
    : 0;
  const unavailableFocusCount = focusIds.length - committedFocusCount;
  const mapReadChip =
    focus && map
      ? [
          FOCUS_HEADING[focus.source],
          `${committedFocusCount} node${committedFocusCount === 1 ? "" : "s"}`,
          unavailableFocusCount ? `${unavailableFocusCount} unavailable` : "",
          focus.label,
        ]
          .filter(Boolean)
          .join(" · ")
      : [
          loading ? "reading…" : "",
          switching ? "switching workspace…" : "",
          map && map.structural_mode !== "full" ? "uniform sizes" : "",
          gutterCount > 0 && map
            ? gutterReading(map.lens, gutterCount).text
            : "",
        ]
          .filter(Boolean)
          .join(" · ") || null;

  const commitSelection = (graphId: string) => {
    setSelected(graphId);
    setLinkage({});
    setProposal(null);
    const hash = window.location.hash;
    const q = hash.indexOf("?");
    const base = q < 0 ? hash : hash.slice(0, q);
    const params = new URLSearchParams(q < 0 ? "" : hash.slice(q + 1));
    params.set("graph", graphId);
    for (const key of [
      "activity",
      "proposal",
      "gap",
      "focus",
      "from",
      "to",
      "gv",
      "seam",
    ]) {
      params.delete(key);
    }
    window.history.replaceState(null, "", `${base}?${params}`);
  };

  const pickGraph = async (graphId: string) => {
    if (switching || graphId === selected) return;
    setSwitching(true);
    setVerbFault(null);
    try {
      const active = await activateGraph(graphId);
      const rows = await listGraphs();
      setGraphs(rows);
      const activeRow = rows.find((row) => row.is_current);
      window.dispatchEvent(
        new CustomEvent("graphauthor:workspace", {
          detail: { label: activeRow?.label ?? active.graph.label },
        }),
      );
      commitSelection(activeRow?.id ?? active.graph.id);
    } catch (e: unknown) {
      const fault = faultOf(e, "Could not switch workspace.");
      if (fault) setVerbFault(fault);
    } finally {
      setSwitching(false);
    }
  };

  /**
   * The human half of the loop, and the only write this surface makes.
   *
   * Publishing does not touch the graph — it records that a person looked at
   * it and said so. Withdrawing deletes that record, which is why a graph can
   * come back for another cut without anything being undone.
   *
   * The selection is deliberately *not* cleared on success. The graph leaves
   * this shelf, and the map stays on it until the operator picks something
   * else: a map that emptied itself the moment you approved it would read as
   * having lost the graph.
   */
  const setPublished = async (graphId: string, published: boolean) => {
    if (publishing) return;
    setPublishing(true);
    setPublishError("");
    try {
      await publishGraph(graphId, published);
      setGraphs(await listGraphs());
    } catch (e: unknown) {
      if (e instanceof ApiError && e.hostUnreachable) return;
      setPublishError(
        e instanceof ApiError
          ? e.message
          : published
            ? "Could not publish this graph."
            : "Could not return this graph to construction.",
      );
    } finally {
      setPublishing(false);
    }
  };

  /** Drop the focus. A Logs-opened subject returns to Logs. */
  const clearFocus = () => {
    const returning =
      hashParam("return") === "log" || hashParam("return") === "review";
    if ((focus?.source === "ledger" || linkage.seam === "diff") && returning) {
      const params = new URLSearchParams();
      const api = hashParam("api");
      const token = hashParam("apiToken");
      const base = hashParam("apiBase");
      params.set("api", api || "live");
      if (token) params.set("apiToken", token);
      if (base) params.set("apiBase", base);
      const activity = linkage.activity || hashParam("activity");
      if (activity) params.set("activity", activity);
      window.location.hash = `#/log?${params}`;
      return;
    }
    if (linkage.focus?.length) {
      writeHashSeamFocus(null);
      setLinkage(readHashSeamParams());
    }
    setFocus(null);
  };

  const focusOn = (next: Focus | null) => {
    // A new subject replaces the old one. If the old one was a ledger link, the
    // URL has to let go of it too, or a reload would resurrect it on top.
    if (linkage.focus?.length) {
      writeHashSeamFocus(null);
      setLinkage(readHashSeamParams());
    }
    setFocus(next && next.ids.length ? next : null);
  };

  /**
   * Inspect a node the operator named from off the disc, and fly to it.
   * Neighbour-strip rows, named chips, and Find all take this path.
   */
  const jumpTo = (node: MapNode) => {
    setTraversalOpen(false);
    setInspected(node);
    setFollowId(node.id);
  };


  const selectedRow = graphs.find((graph) => graph.id === selected);
  const provisional = selectedRow?.state === "construction";

  /**
   * Tell the shell, so chrome moves with the map rather than a step behind it.
   *
   * Cleared only on unmount: the previous cleanup also ran when `provisional`
   * flipped, which reset the shell to published chrome for a frame (and, under
   * Strict Mode, could leave it there). Publication is a property of the open
   * graph; leaving the page is when the mute has to come off.
   */
  useLayoutEffect(() => {
    setProvisional(graphOnScreen && provisional);
  }, [graphOnScreen, provisional, setProvisional]);
  useEffect(() => {
    return () => setProvisional(false);
  }, [setProvisional]);

  /**
   * Published and construction graphs share one catalogue. The split is `state`
   * rather than `source`: a construction being looked at right now is
   * `source: "current"`, so filtering on `source` would empty the list of the
   * graph on screen.
   *
   * The open graph leads its own shelf. Everything else is ordered by where it
   * came from — opened, built, then examples.
   */
  const SOURCE_ORDER: Record<string, number> = {
    opened: 0,
    construction: 1,
    example: 2,
  };
  const published = graphs.filter((graph) => graph.state !== "construction");
  const constructions = graphs.filter((graph) => graph.state === "construction");
  const sortShelf = (rows: GraphSummary[]) =>
    [...rows].sort((a, b) => {
      if (a.id === selected) return -1;
      if (b.id === selected) return 1;
      const rank =
        (SOURCE_ORDER[a.source] ?? 0) - (SOURCE_ORDER[b.source] ?? 0);
      return rank !== 0 ? rank : a.label.localeCompare(b.label);
    });
  const publishedGraphs = sortShelf(published);
  const constructionGraphs = sortShelf(constructions);

  /**
   * Two shelves, same heading, same rows. Constructions used to be a third
   * product tab, then a collapsible leftover under an unlabeled list. Both
   * were the wrong hierarchy: one catalogue, two states, one drawer.
   *
   * The row also used to carry `N nodes · M edges · 1.4 MB`. Node count says
   * how big the thing is; the other two never decided anything.
   */
  const SOURCE_TAG: Record<string, string> = {
    construction: "built",
    example: "example",
    opened: "opened",
  };

  const renderGraphList = (rows: GraphSummary[], provisional: boolean) => (
    <ul
      className={`gm__list${provisional ? " gm__list--provisional" : ""}`}
    >
      {/* Swap keyed on membership so a row that changes shelf (publish /
          return) moves with a fade instead of an instant list rebuild. */}
      <Swap id={rows.map((g) => g.id).join(",")}>
        {rows.map((g) => (
        <li key={g.id}>
          <button
            type="button"
            className={g.id === selected ? "is-selected" : ""}
            onClick={() => void pickGraph(g.id)}
            disabled={switching}
            title={
              g.source === "construction" && g.workspace_name
                ? g.workspace_name
                : undefined
            }
          >
            <span className="gm__list-name">
              {g.label}
              {g.state !== "construction" && SOURCE_TAG[g.source] ? (
                <em>{SOURCE_TAG[g.source]}</em>
              ) : null}
            </span>
            <span className="gm__list-meta">
              {g.node_count === null ? "unreadable" : `${g.node_count} nodes`}
            </span>
            {g.read_error ? (
              <span className="gm__list-error">{g.read_error}</span>
            ) : null}
          </button>
        </li>
      ))}
      </Swap>
    </ul>
  );

  // The map keeps its size whichever panels are open — nothing here reflows the
  // canvas, and map chrome no longer tracks open drawers (padding is fixed).
  return (
    <main
      className={`${productMode ? "gm gm--product" : "gm"}${
        pickerOpen ? " is-picker-open" : ""
      }${
        inspected ? " is-reader-open" : ""
      }`}
    >
      <section className="gm__main">
        <NoticeSurface />
        {/* ------------------------------------------------------- instrument

            In focus, most of this goes.

            Focus means one subject is lit and the rest of the graph is context.
            The controls that survive are the ones that act on *that subject*:
            what is lit and how to stop lighting it, and the hand-moves you make
            while reading it. Find, the lenses and the appearance controls
            are all about choosing a different subject. Ask stays when this
            subject is an answer.
            Identity goes too — see `.product-shell.is-focus` in the CSS. */}
        <Instrument>

          {/* Order: **controls first, readings after.**

              Find leads the band, and Logs' Show on graph leads its own,
              because a locate control is the one you reach for without looking,
              and a control you aim at should be in the same place every time
              you aim. Across the two surfaces it was not: third there, first
              here.

              On this surface the change is close to a no-op, and it is worth
              saying so rather than claiming a fix. The three readings below used
              to lead, and a conditional group in front of fixed controls is
              exactly what `Hand-moved nodes` was moved to the end to avoid — but
              here the readings almost never coexist with the controls. Each one
              renders in a state that also drives `mode !== "ambient"`, and that
              is what hides this whole div (`.product-shell.is-focus
              .gm__choosing`). Draft, diff and focus take Find, the lenses and
              appearance with them. Traversal sits outside this wrapper so an
              answer's evidence does not bury the question that made it.

              Almost. `focus && map` can be true while `visibleFocusIds` is
              empty — a focus whose nodes are none of them on the open map, the
              case the `N unavailable` reading exists to report. Then the mode is
              ambient, the controls stay, and the reading did sit in front of
              them. One narrow state, now consistent with the rest.

              The reason to keep the move is the order itself: source order is
              what the next person reads the grammar from, and a grammar that is
              only true when a condition happens to be false is not one. */}
          <div className="gm__choosing">
            <InstrumentGroup label="Find a node">
              <NodeFinder
                map={map}
                onPick={(node) => {
                  // Locate is one disc, not an overlay. Drop whatever was
                  // lighting the map so the neighbour-strip jump can run on
                  // the ambient field: inspect, fly, incident filaments fan.
                  if (focus) clearFocus();
                  jumpTo(node);
                }}
              />
            </InstrumentGroup>
          </div>

          {/* Traversal sits outside the choosing wrapper on purpose. A
              traversal result *is* a focus, and the control that produced it
              must stay reachable — "Clear" undoes the lighting; Traversal is
              how you ask the next question of the same subject. Putting it
              inside `.gm__choosing` hid it the moment its own result landed. */}
          <InstrumentGroup
            label="Traversal"
            present={Boolean(
              productMode && live && selected && Object.keys(namedTraversals).length,
            )}
          >
            <TraversalMenu
                traversals={namedTraversals}
                map={map ?? null}
                inspected={inspected}
                graphId={selected ?? ""}
                graphVersion={orientationRead.data?.graph_version}
                open={traversalOpen}
                onOpenChange={setTraversalOpen}
                onResult={(result: NamedTraversalResult) => {
                  if (!map) return;
                  const records = result.evidence?.node_records ?? [];
                  // A recipe returns a packet and says which of it was asked for.
                  // Lighting both alike says the context was part of the finding.
                  const answers = new Set(
                    result.answer_node_ids?.length
                      ? result.answer_node_ids
                      : records.filter((n) => n.is_answer).map((n) => n.id),
                  );
                  const packet = records.map((node) => node.id);
                  // Nodes the packet named that this map does not hold. Today the
                  // map is the whole graph so this is always empty -- but the
                  // filter that used to drop them was silent, and the moment the
                  // map is windowed a bounded traversal's answer would vanish
                  // with no indication that it had.
                  const mapIds = new Set(map.nodes.map((node) => node.id));
                  const offMap = packet.filter((id) => !mapIds.has(id));
                  const ids = packet.filter((id) => mapIds.has(id));
                  const outcome = result.outcome.replaceAll("_", " ");
                  focusOn({
                    ids,
                    source: "traversal",
                    label: offMap.length
                      ? `${outcome} · ${offMap.length} not on this map`
                      : outcome,
                    overlay: result.overlay,
                    answerIds: ids.filter((id) => answers.has(id)),
                  });
                }}
              />
          </InstrumentGroup>


          <div className="gm__choosing">

            {/* Only when the server offers a choice. One lens is not a control. */}
            {map && (map.available_lenses?.length ?? 0) > 1 ? (
              <InstrumentGroup label="How the map is arranged">
                {map.available_lenses!.map((name) => {
                  const current = (map.lens ?? "canonical") === name;
                  return (
                    <button
                      key={name}
                      type="button"
                      aria-pressed={current}
                      title={LENS_HINTS[name] ?? ""}
                      onClick={() => {
                        if (current) return;
                        setLens(name);
                        setHashParam("lens", name);
                        setInspected(null);
                      }}
                    >
                      {lensLabel(name)}
                    </button>
                  );
                })}
              </InstrumentGroup>
            ) : null}

            {/* Hiding the chrome is a verb about the map: it exists so the map
                can be read or captured bare. It sat in identity because that is
                where there was room, which is not a reason. */}
            <InstrumentGroup label="Chrome">
              <button
                type="button"
                onClick={() => setChromeHidden(true)}
                title="Hide the controls and read the map bare · press . to bring them back"
              >
                Hide
              </button>
            </InstrumentGroup>
          </div>

          {/* Clear is the verb that undoes the lighting. */}
          <InstrumentGroup
            label="Clear focus"
            present={Boolean(focus && map)}
          >
            {focus && map ? (
              <button type="button" onClick={clearFocus}>
                Clear
              </button>
            ) : null}
          </InstrumentGroup>

          <InstrumentReadings
            label="Draft on the map"
            present={Boolean(proposal)}
          >
            {proposal ? (
              <span className="gm__reading">
                Draft · {proposal.nodes.length} node
                {proposal.nodes.length === 1 ? "" : "s"} ·{" "}
                {proposal.edges.length} edge
                {proposal.edges.length === 1 ? "" : "s"}
              </span>
            ) : null}
          </InstrumentReadings>

          <InstrumentReadings
            label="Version difference"
            present={Boolean(linkage.seam === "diff" && versionDiff && map)}
          >
            {linkage.seam === "diff" && versionDiff && map ? (
              <span className="gm__reading">
                Diff · {versionDiff.nodes_added.length} added ·{" "}
                {versionDiff.nodes_removed.length} removed ·{" "}
                {versionDiff.nodes_changed.length} changed
                {String(linkage.to ?? "") !== map.graph_version &&
                String(linkage.to ?? "") !==
                  (writeCheckpoints[writeCheckpoints.length - 1]?.to ?? "")
                  ? " · later version not open"
                  : ""}
              </span>
            ) : null}
          </InstrumentReadings>
          {/* Last among the verbs: undo only exists after a move. */}
          <InstrumentGroup
            label="Hand-moved nodes"
            present={Boolean(nudges && nudges.count > 0)}
          >
            {nudges && nudges.count > 0 ? (
              <>
              <button
                type="button"
                onClick={nudges.undo}
                disabled={!nudges.canUndo}
                title="Undo the last move"
              >
                Undo
              </button>
              <button
                type="button"
                onClick={nudges.redo}
                disabled={!nudges.canRedo}
                title="Redo the last undone move"
              >
                Redo
              </button>
              <button
                type="button"
                onClick={nudges.reset}
                title={`Put ${nudges.count} moved node${
                  nudges.count === 1 ? "" : "s"
                } back where the arrangement placed ${
                  nudges.count === 1 ? "it" : "them"
                }`}
              >
                Reset {nudges.count}
              </button>
              </>
            ) : null}
          </InstrumentGroup>
          {/* One chip, on the right of the centred bar. Isolated nodes, a
              traversal packet, uniform sizes — facts, not verbs, drawn as the
              same cell the controls use. */}
          <InstrumentGroup label="Map reading" present={Boolean(mapReadChip)}>
            {mapReadChip ? (
              <span className="gm__reading">{mapReadChip}</span>
            ) : null}
          </InstrumentGroup>
        </Instrument>

        {/* Publish / return sits in the identity bar — same row as Graph,
            Logs and Settings, not a caption on the map. */}
        {productMode && live && selectedRow?.state ? (
          <ShellAction>
            <button
              type="button"
              disabled={publishing}
              onClick={() =>
                void setPublished(
                  selectedRow.id,
                  selectedRow.state === "construction",
                )
              }
            >
              {selectedRow.state === "construction" ? "Publish" : "Return"}
            </button>
          </ShellAction>
        ) : null}
        {productMode && live && (map?.graph_version || writeCheckpoints.at(-1)?.to) ? (
          <WriteTimeline
            checkpoints={writeCheckpoints}
            selectedId={selectedWriteId}
            liveVersion={map?.graph_version || writeCheckpoints.at(-1)?.to || ""}
            provisional={provisional}
            diffFrom={
              linkage.seam === "diff" ? String(linkage.from ?? "") : undefined
            }
            diffTo={
              linkage.seam === "diff" ? String(linkage.to ?? "") : undefined
            }
            onSelect={(row) => {
              writeHashSeamDiff(row);
              setLinkage(readHashSeamParams());
            }}
          />
        ) : null}
        {publishError ? (
          <div className="gm__publish-fault">
            <NoticeCard kind="fault" body={publishError} />
          </div>
        ) : null}

        <div className={`gm__stage${waitingMap ? " is-waiting" : ""}`}>
          {canvasModel ? (
            <ProductGraphCanvas
              data={canvasModel.data}
              mapKey={askKey}
              mode={canvasModel.mode}
              theme={theme}
              provisional={provisional}
              frameIds={canvasModel.frameIds}
              onNudgesChange={setNudges}
              onRenderError={setCanvasError}
              onSceneReady={setSceneReady}
              selectedId={inspected?.id ?? null}
              followId={followId}
              previewId={previewId}
              onSelect={(nodeId) => {
                setFollowId(null);
                setInspected(
                  nodeId
                    ? map?.nodes.find((node) => node.id === nodeId) ?? null
                    : null,
                );
              }}
              onHover={(nodeId) => {
                if (nodeId && selected && map?.topology_version) {
                  prefetchNodeContent(nodeId, selected, map.topology_version);
                }
              }}
              onPreview={setPreviewId}
              onJump={(nodeId) => {
                const next = map?.nodes.find((node) => node.id === nodeId) ?? null;
                if (next) jumpTo(next);
              }}
            />
          ) : null}
          {waitingPresence.mounted ? (
            <div
              className={`gm__stage-wait motion-layer motion-layer--fade${waitingPresence.shown ? " is-in" : ""}`}
              role="status"
              aria-live="polite"
            >
              {waitingLabel}
            </div>
          ) : null}
        </div>

      </section>


      {/* The reader docks opposite the library, without a side tab: the
          name lives in the column. Close it with Escape or by clicking
          the map. */}
      {readerNode && map ? (
        <OverlayPanel
          id="node-reader"
          side="right"
          title={readerNode.label || readerNode.id}
          open={Boolean(inspected)}
          onToggle={(next) => {
            if (!next) setInspected(null);
          }}
          handle={false}
          width={readerWidth}
          onWidthChange={setReaderWidth}
          flush
        >
          <Swap id={readerNode.id}>
            <NodeReaderPanel
              node={readerNode}
              graphId={selected}
              map={map}
              theme={theme}
              onSelectNode={(nodeId) => {
                const next = map.nodes.find((row) => row.id === nodeId) ?? null;
                if (next) jumpTo(next);
              }}
              onPreviewNode={setPreviewId}
            />
          </Swap>
        </OverlayPanel>
      ) : null}

      <OverlayPanel
        id="graph-picker"
        side="left"
        title="Graphs"
        open={pickerOpen}
        onToggle={setPickerOpen}
        dismissOnOutsideClick
        flush
      >
        <div className="gm__picker">
          {live ? (
            <>
              <div className="gm__picker-shelves">
                <section className="gm__shelf" aria-label="Published">
                  <h2>
                    Published
                    {publishedGraphs.length ? ` · ${publishedGraphs.length}` : ""}
                  </h2>
                  {publishedGraphs.length ? (
                    renderGraphList(publishedGraphs, false)
                  ) : listed && !catalogueFault ? (
                    <p className="gm__empty">No published graphs yet.</p>
                  ) : null}
                </section>
                <section className="gm__shelf" aria-label="Constructions">
                  <h2>
                    Constructions
                    {constructionGraphs.length
                      ? ` · ${constructionGraphs.length}`
                      : ""}
                  </h2>
                  {constructionGraphs.length ? (
                    renderGraphList(constructionGraphs, true)
                  ) : (
                    <p className="gm__empty">
                      Built in the agent session. They appear here when they land.
                    </p>
                  )}
                </section>
              </div>
              {productMode && selectedRow?.state ? (
                <footer className="gm__picker-foot">
                  <p>
                    {selectedRow.state === "construction"
                      ? "In construction. Only you can see it here."
                      : "Published. It sits with your graphs."}
                  </p>
                  {publishError ? (
                    <NoticeCard kind="fault" body={publishError} />
                  ) : null}
                </footer>
              ) : null}
            </>
          ) : (
            <div className="gm__picker-offline">
              <p className="gm__hint">
                This page reads real graphs. Open it against a running operator:
                <code>?api=live&amp;apiToken=…</code>
              </p>
            </div>
          )}
        </div>
      </OverlayPanel>
    </main>
  );
}
