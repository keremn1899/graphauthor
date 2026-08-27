import {
  type CSSProperties,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  fetchMapCached,
  orientGraph,
  isLiveMode,
  runNamedTraversal,
  type GraphMap,
  type MapNode,
} from "../api/graph";
import {
  actionErrorMessage,
  invalidate,
  useResource,
  visibleError,
} from "../api/resource";
import {
  acknowledgeIncident,
  classifyAbsence,
  confirmProposal,
  disposeEscalation,
  fetchActivities,
  fetchEscalations,
  fetchEventLog,
  fetchOperatorHealth,
  fetchProposal,
  fetchProposals,
  fetchVersionDiff,
  rejectProposal,
  requeueProposal,
  type ConstructionEvidenceSpan,
  type OperatorHealth,
  type ProposalVM,
  type VersionDiff,
} from "../api/ledger";
import type { ActivityVM } from "../explorations/lab/ledgerFeedModel";
import {
  relativeTime,
  stateLabel,
} from "../explorations/lab/ledgerFeedModel";
import {
  absencePriorLabel,
  edgeDisplayLabel,
  edgeStatement,
  eventTypeLabel,
  gateFindingLabel,
  nodeDisplayLabel,
  proposalStatusLabel,
} from "../shared/protocolVocabulary";
import { displayPositions, proposalPositions } from "./graphModel";
import {
  ProductGraphCanvas,
  type ProductGraphMode,
} from "./ProductGraphCanvas";
import {
  readStoredPanelSize,
  ResizableDivider,
  storePanelSize,
} from "./ResizableDivider";
import { Instrument, InstrumentGroup } from "./ProductShell";
import { NoticeCard, NoticeSurface, useBoundNotice } from "./Notice";
import { Swap } from "../styles/Swap";
import "./ReviewWorkspace.css";

/**
 * Review is the queue. It is not a view of the log.
 *
 * It used to be both, as three filter chips over one list — `needs-me`,
 * `incidents`, `all` — and the two are different objects wearing one shape:
 *
 *   A queue's success is **empty**. A log's success is **complete**. Same
 *   emptiness, opposite meanings, and one list cannot state both (see
 *   `chrome-constraints.md` §3.4). The surface said "This queue is clear" while
 *   `All` held five records; both true, together misleading.
 *
 *   They sort differently, and the code already knew: `needs-me` sorted by how
 *   long something had waited, `all` by when it happened. Two orderings of one
 *   list is two objects.
 *
 *   Dilution is what actually kills a queue. Every row nobody can act on
 *   teaches the operator not to open it — and then a real demand sits in one
 *   nobody reads. Six of six rows on a live Review were `query.completed`.
 *
 * So: only open demands reach this surface, ordered oldest-waiting, and the
 * record is reached through whatever it is about — a node's origin, an
 * activity's own event list — rather than as a global feed.
 *
 * The two demand kinds stay visibly separate. "A rule was broken" and "a
 * decision is waiting" are not the same work, and collapsing them is the same
 * mistake as collapsing UNGOVERNED with INSUFFICIENT.
 */
type ReviewView = "open" | "exceptions" | "incidents";

const EMPTY_HEALTH: OperatorHealth = {
  ready: false,
  can_commit: false,
  pending_count: 0,
  needs_me_count: 0,
  incident_count: 0,
};

/** Module-level so an empty queue keeps a stable identity across renders. */
const NO_ACTIVITIES: ActivityVM[] = [];

/** The queue is what the operator is looking at, so it is what is polled. */
const REVIEW_POLL_MS = 5_000;

function activityParam() {
  const query = window.location.hash.split("?", 2)[1] ?? "";
  return new URLSearchParams(query).get("activity") ?? "";
}

function rememberActivity(activityId: string) {
  const [route, query = ""] = window.location.hash.split("?", 2);
  const params = new URLSearchParams(query);
  if (activityId) params.set("activity", activityId);
  else params.delete("activity");
  const suffix = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${route}${suffix ? `?${suffix}` : ""}`,
  );
}

function focusIds(activity: ActivityVM): string[] {
  return activity.subject_node_ids?.length
    ? activity.subject_node_ids
    : activity.node_ids;
}

function liveHashParams(extra: Record<string, string> = {}) {
  const hash = window.location.hash;
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const next = new URLSearchParams();
  for (const key of ["api", "apiToken", "apiBase"]) {
    const value = params.get(key);
    if (value) next.set(key, value);
  }
  if (!next.get("api")) next.set("api", "live");
  for (const [key, value] of Object.entries(extra)) {
    if (value) next.set(key, value);
  }
  return next;
}

function graphHref(activity: ActivityVM, mode: "focus" | "diff") {
  const params = liveHashParams({
    seam: mode,
    return: "review",
    activity: activity.activity_id,
  });
  const focus = focusIds(activity);
  if (focus.length) params.set("focus", focus.join(","));
  if (activity.ids.proposal_id) params.set("proposal", activity.ids.proposal_id);
  if (activity.ids.gap_id) params.set("gap", activity.ids.gap_id);
  if (activity.graph_revision_before !== undefined) {
    params.set("from", String(activity.graph_revision_before));
  }
  if (activity.graph_revision_after !== undefined) {
    params.set("to", String(activity.graph_revision_after));
  }
  return `#/graph?${params}`;
}

/* ------------------------------------------------------------------ focus model */

/**
 * Build the canvas model for the selected activity.
 *
 * A **pending proposal is the one thing Review exists to look at, and it is
 * exactly what a committed-only focus cannot draw** — its node is not in the
 * map yet, so filtering focus ids against the map left nothing lit and the
 * panel fell back to rendering the whole graph under the label "0 nodes".
 * Proposed nodes are therefore added as ghosts, ringed around the committed
 * nodes their edges attach to.
 */
function buildFocusModel(
  map: GraphMap,
  ids: string[],
  proposal?: ProposalVM,
): { data: import("@antv/g6").GraphData; mode: ProductGraphMode; frameIds: string[] } | null {
  if (!map.nodes.length) return null;
  const positions = displayPositions(map);
  const committedIds = new Set(map.nodes.map((n) => n.id));

  // Only a proposal that has not landed yet has anything to add to the map.
  const pending =
    proposal && proposal.status !== "COMMITTED" ? proposal : undefined;
  const ghostPositions = pending
    ? proposalPositions(map, pending, positions)
    : new Map<string, { x: number; y: number }>();
  const ghostNodes = (pending?.nodes ?? []).filter((node) =>
    ghostPositions.has(node.id),
  );

  const focusSet = new Set([
    ...ids.filter((id) => committedIds.has(id)),
    ...ghostNodes.map((node) => node.id),
  ]);
  const frameIds = [...focusSet];
  const mode: ProductGraphMode = ghostNodes.length
    ? "proposal"
    : frameIds.length
      ? "focus"
      : "ambient";

  const drawable = new Set([...committedIds, ...ghostNodes.map((n) => n.id)]);

  return {
    mode,
    frameIds,
    data: {
      nodes: [
        ...map.nodes.map((node) => ({
          id: node.id,
          style: positions.get(node.id),
          data: {
            ...node,
            label: nodeDisplayLabel(node.label, node.kind),
            proposed: false,
            intensity: focusSet.has(node.id) ? 1 : 0,
            diff: "unchanged",
          },
        })),
        ...ghostNodes.map((node) => ({
          id: node.id,
          style: ghostPositions.get(node.id),
          data: {
            ...node,
            label: nodeDisplayLabel(node.label, node.kind),
            semantic_anchor: node.semantic_anchor ?? "",
            proposed: true,
            intensity: 1,
          },
        })),
      ],
      edges: [
        ...map.edges.map((edge, i) => ({
          id: `e${i}`,
          source: edge.source,
          target: edge.target,
          data: {
            type: edge.type,
            kind: edge.type.toLowerCase(),
            label: edgeDisplayLabel(edge.type, edge.label),
            proposed: false,
            intensity:
              focusSet.has(edge.source) || focusSet.has(edge.target) ? 1 : 0,
            diff: "unchanged",
            lens: 0,
            _lp: 0.5,
            _bond: 0,
            _bondSide: "source",
          },
        })),
        ...(pending?.edges ?? [])
          .filter(
            (edge) =>
              drawable.has(edge.source_id) && drawable.has(edge.target_id),
          )
          .map((edge, i) => ({
            id: `proposal-${i}`,
            source: edge.source_id,
            target: edge.target_id,
            data: {
              type: edge.type,
              kind: edge.type.toLowerCase(),
              label: edgeDisplayLabel(edge.type, edge.predicate || edge.label),
              proposed: true,
              intensity: 1,
              lens: 0,
              _lp: 0.5,
              _bond: 0,
              _bondSide: "source",
            },
          })),
      ],
    },
  };
}


function matchesSearch(activity: ActivityVM, search: string) {
  if (!search) return true;
  const haystack = [
    activity.summary,
    activity.activity_id,
    activity.ids.proposal_id,
    activity.ids.gap_id,
    ...focusIds(activity),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(search.toLowerCase());
}

function hasVersions(activity: ActivityVM) {
  const before = activity.graph_revision_before;
  const after = activity.graph_revision_after;
  return before !== undefined && after !== undefined && before !== after;
}

function DiffSummary({ diff }: { diff: VersionDiff }) {
  const total =
    diff.nodes_added.length +
    diff.nodes_removed.length +
    diff.nodes_changed.length +
    diff.edges_added.length +
    diff.edges_removed.length;
  return (
    <div className="review-diff">
      <span>{total} recorded change{total === 1 ? "" : "s"}</span>
      <dl>
        <div><dt>Nodes added</dt><dd>{diff.nodes_added.length}</dd></div>
        <div><dt>Nodes changed</dt><dd>{diff.nodes_changed.length}</dd></div>
        <div><dt>Nodes removed</dt><dd>{diff.nodes_removed.length}</dd></div>
        <div><dt>Edges added</dt><dd>{diff.edges_added.length}</dd></div>
        <div><dt>Edges removed</dt><dd>{diff.edges_removed.length}</dd></div>
      </dl>
    </div>
  );
}

/**
 * What the operator is being asked to do with this row.
 *
 * The queue carries four different things — a proposal awaiting a sourced
 * decision, a refused one awaiting recovery, an open incident, and a record of
 * something already settled. They were all rendered as one fixed stack of
 * sections, so every shape scrolled past sections that did not apply to it and
 * the action itself sat below a canvas. Naming the intent is what lets the
 * inspector lead with the action and show only the evidence that action needs.
 */
type ReviewIntent =
  | "decide"
  | "recover"
  | "resolve"
  | "encode"
  | "handoff"
  | "record";

const RECOVERABLE = ["GRAIN_FAILED", "GATE_FAILED", "ENCODE_FAILED"];

function intentOf(
  activity: ActivityVM,
  proposal: ProposalVM | undefined,
): ReviewIntent {
  if (proposal?.status === "PENDING") return "decide";
  if (proposal && RECOVERABLE.includes(proposal.status)) return "recover";
  if (activity.demand?.kind === "incident" && activity.state !== "SETTLED") {
    return "resolve";
  }
  // A construction run waiting on a person. Without this case it fell to
  // "record" and the pane printed "Recorded — nothing to decide here" beside a
  // badge reading AWAITING YOU and a queue reading Waiting 1 — three claims,
  // at most one of them true (`chrome-constraints.md` §2.7).
  if (activity.kind === "construction" && activity.state !== "SETTLED") {
    return "handoff";
  }
  // An escalation with no proposal yet: an agent hit a predicate it could not
  // govern and asked for one. The product's *oldest* demand type, and it fell
  // through to "record" exactly as construction did — the same contradiction,
  // on the row that has been in the queue since the beginning.
  if (
    activity.state !== "SETTLED" &&
    activity.ids.handoff_id &&
    activity.events.some((e) => e.type === "escalation.recorded")
  ) {
    return "encode";
  }
  return "record";
}

type GateFinding = {
  query_id?: string;
  kind?: string;
  flaky_only?: boolean;
};

/**
 * Why the gate refused, in words — this is the reason someone is being asked to
 * intervene, so it cannot stay a JSON blob. The blob is kept underneath: the
 * report is also the record, and a summary is not a substitute for it.
 */
function GateReport({ report }: { report: unknown }) {
  const record = (report ?? {}) as {
    findings?: GateFinding[];
    closure?: { n?: number; governed?: number; right_reason?: number };
    distractors_clean?: boolean;
  };
  const findings = record.findings ?? [];
  const closure = record.closure;
  return (
    <div className="review-gate">
      {findings.length ? (
        <ul className="review-gate__findings">
          {findings.map((finding, index) => (
            <li key={`${finding.query_id ?? "finding"}-${index}`}>
              <span>{gateFindingLabel(finding.kind ?? "")}</span>
              {finding.query_id ? <code>{finding.query_id}</code> : null}
              {finding.flaky_only ? <em>did not reproduce</em> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="review-gate__clean">The gate recorded no findings.</p>
      )}
      {closure ? (
        <p className="review-gate__closure">
          {closure.governed ?? 0} of {closure.n ?? 0} checked question
          {closure.n === 1 ? "" : "s"} governed
          {closure.right_reason !== undefined
            ? `, ${closure.right_reason} for the right reason`
            : ""}
          {record.distractors_clean === false
            ? " · captured something it should have left alone"
            : ""}
        </p>
      ) : null}
      <details className="review-technical">
        <summary>Full gate report</summary>
        <pre>{JSON.stringify(report, null, 2)}</pre>
      </details>
    </div>
  );
}

function NodeBody({ text }: { text: string }) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  if (trimmed.length <= 280) return <p>{trimmed}</p>;
  return (
    <details className="review-change-body">
      <summary>Source text</summary>
      <p>{trimmed}</p>
    </details>
  );
}

/**
 * The change itself. The heading follows the status: calling a committed change
 * "proposed" told the reader the opposite of the badge beside it.
 */
function ProposalChange({ proposal }: { proposal: ProposalVM }) {
  const heading =
    proposal.status === "COMMITTED"
      ? "What entered the graph"
      : RECOVERABLE.includes(proposal.status) || proposal.status === "REJECTED"
        ? "What it proposed"
        : "What would change";
  return (
    <section className="review-inspector__section" aria-labelledby="proposal-heading">
      <div className="review-section-heading">
        <h3 id="proposal-heading">{heading}</h3>
        <span className={`review-status review-status--${proposal.status.toLowerCase()}`}>
          {proposalStatusLabel(proposal.status)}
        </span>
      </div>
      {proposal.demotion_reason ? (
        <p className="review-callout">{proposal.demotion_reason}</p>
      ) : null}
      {proposal.nodes.length ? (
        <div className="review-change-list">
          <h4>Nodes</h4>
          {proposal.nodes.map((node) => (
            <div key={node.id}>
              <strong>{nodeDisplayLabel(node.label || node.id, node.kind)}</strong>
              <code>{node.id}</code>
              {node.text_content ? <NodeBody text={node.text_content} /> : null}
            </div>
          ))}
        </div>
      ) : null}
      {proposal.edges.length ? (
        <div className="review-change-list">
          <h4>Edges</h4>
          {proposal.edges.map((edge, index) => (
            <div key={`${edge.type}-${edge.source_id}-${edge.target_id}-${index}`}>
              <strong>
                {edgeStatement(
                  edge.type,
                  edge.source_id,
                  edge.target_id,
                  edge.predicate,
                )}
              </strong>
              <code>{edge.predicate || edge.type}</code>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function evidenceSpanMeta(span: ConstructionEvidenceSpan): string {
  const grain = (span.granularity || "").toUpperCase();
  const grainLabel =
    grain === "SUBSPAN"
      ? "Subspan"
      : grain === "ATOM"
        ? "Whole atom"
        : grain === "SPAN"
          ? "Span"
          : "";
  const cited =
    span.evidence_characters ?? Math.max(0, span.end - span.start);
  const atom = span.atom_characters;
  const size =
    typeof atom === "number" && atom > 0
      ? `${cited} of ${atom} characters`
      : `${cited} characters`;
  return [grainLabel, size, span.locator || span.unit_id, `${span.start}–${span.end}`]
    .filter(Boolean)
    .join(" · ");
}

function ConstructionAudit({ proposal }: { proposal: ProposalVM }) {
  const receipt = proposal.construction_receipt;
  if (!Object.keys(receipt).length) return null;
  const spanCount = Object.values(proposal.construction_evidence).reduce(
    (total, spans) => total + spans.length,
    0,
  );
  const authorProfile =
    receipt.author_profile && typeof receipt.author_profile === "object"
      ? (receipt.author_profile as Record<string, unknown>)
      : {};

  return (
    <section
      className="review-inspector__section review-construction-audit"
      aria-labelledby="construction-audit-heading"
    >
      <div className="review-section-heading">
        <h3 id="construction-audit-heading">Construction evidence</h3>
        <span className="review-status review-status--committed">Attached</span>
      </div>
      <p>
        {spanCount} exact source span{spanCount === 1 ? "" : "s"} ·{" "}
        {proposal.construction_edge_evidence.length} evidenced edge
        {proposal.construction_edge_evidence.length === 1 ? "" : "s"}. This
        material explains the proposal; it does not confirm it.
      </p>

      {proposal.nodes.map((node) => {
        const spans = proposal.construction_evidence[node.id] ?? [];
        const reason = proposal.construction_reasons[node.id] ?? "";
        if (!spans.length && !reason) return null;
        return (
          <details className="review-evidence-group" key={node.id}>
            <summary>
              {nodeDisplayLabel(node.label || node.id, node.kind)} ·{" "}
              {spans.length ? `${spans.length} source span${spans.length === 1 ? "" : "s"}` : "synthetic"}
            </summary>
            {reason ? (
              <p className="review-evidence-reason">
                <strong>Construction rationale</strong> {reason}
              </p>
            ) : null}
            {spans.map((span, index) => (
              <div className="review-evidence-span" key={`${span.unit_id}-${span.start}-${index}`}>
                <blockquote>{span.quote}</blockquote>
                <code>{evidenceSpanMeta(span)}</code>
              </div>
            ))}
          </details>
        );
      })}

      {proposal.construction_edge_evidence.length ? (
        <div className="review-change-list review-edge-evidence">
          <h4>Edge provenance</h4>
          {proposal.construction_edge_evidence.map((edge, index) => (
            <div key={`${edge.source_id}-${edge.predicate}-${edge.target_id}-${index}`}>
              <strong>
                {edge.source_id} —{edge.predicate}→ {edge.target_id}
              </strong>
              <p>
                {edge.inferred
                  ? edge.construction_reason || "Constructor inference"
                  : `${edge.source_unit_ids?.length ?? 0} cited source atom${
                      edge.source_unit_ids?.length === 1 ? "" : "s"
                    }`}
              </p>
            </div>
          ))}
        </div>
      ) : null}

      <details className="review-evidence-receipt">
        <summary>Audit fingerprints</summary>
        <dl>
          <dt>Receipt</dt>
          <dd>{String(receipt.receipt_fingerprint ?? "")}</dd>
          <dt>Proposal</dt>
          <dd>{String(receipt.proposal_fingerprint ?? "")}</dd>
          <dt>Evidence</dt>
          <dd>{String(receipt.evidence_fingerprint ?? "")}</dd>
          <dt>Author</dt>
          <dd>{String(authorProfile.author_fingerprint ?? "")}</dd>
        </dl>
      </details>
    </section>
  );
}

function exceptionList(proposal: ProposalVM) {
  if (!proposal.review_exceptions.length) return null;
  return (
    <ul className="review-exceptions">
      {proposal.review_exceptions.map((item) => (
        <li key={item.code}>
          <strong>{item.code.replaceAll("_", " ")}</strong>
          <span>{item.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function TraversalPreflight({
  proposal,
  currentGraphVersion,
  currentFormatFingerprint,
  onLightPacket,
  lighting,
  lightError,
  packetLit,
}: {
  proposal: ProposalVM;
  currentGraphVersion: string;
  currentFormatFingerprint: string;
  onLightPacket?: () => void;
  lighting?: boolean;
  lightError?: string;
  packetLit?: boolean;
}) {
  const receipt = proposal.traversal_receipt;
  const canLight = Boolean(onLightPacket && receipt.recipe_name);
  const lightControl = canLight ? (
    <div className="review-preflight__act">
      <button type="button" disabled={Boolean(lighting)} onClick={onLightPacket}>
        {lighting ? "Lighting…" : packetLit ? "Packet lit" : "Light packet"}
      </button>
      {lightError ? (
        <NoticeCard kind="fault" body={lightError} />
      ) : null}
    </div>
  ) : null;
  if (!Object.keys(receipt).length) {
    return (
      <section className="review-inspector__section review-preflight">
        <div className="review-section-heading">
          <h3>Context preflight</h3>
          <span className="review-status">
            {proposal.review_required ? "Exception" : "Not supplied"}
          </span>
        </div>
        <p>
          This proposal was not attached to a named traversal. Review the change
          against the graph directly.
        </p>
        {exceptionList(proposal)}
      </section>
    );
  }
  const receiptGraph = String(receipt.graph_version ?? "");
  const receiptFormat = String(receipt.format_fingerprint ?? "");
  const stale =
    (Boolean(currentGraphVersion) && receiptGraph !== currentGraphVersion) ||
    (Boolean(currentFormatFingerprint) &&
      receiptFormat !== currentFormatFingerprint);
  return (
    <section className="review-inspector__section review-preflight">
      <div className="review-section-heading">
        <h3>Context preflight</h3>
        <span
          className={`review-status ${
            stale ? "review-status--gate_failed" : "review-status--committed"
          }`}
        >
          {stale ? "Stale" : "Current"}
        </span>
      </div>
      <p>
        {stale
          ? "The graph or format moved after this context packet was prepared. Re-run the procedure before confirming."
          : "The attached procedure was reproduced before this proposal entered the queue."}
      </p>
      {exceptionList(proposal)}
      <dl className="review-facts">
        <div>
          <dt>Procedure</dt>
          <dd>
            {String(receipt.recipe_name ?? "—")} · v
            {String(receipt.recipe_version ?? "—")}
          </dd>
        </div>
        <div>
          <dt>Result</dt>
          <dd>{String(receipt.result_fingerprint ?? "—")}</dd>
        </div>
        <div>
          <dt>Graph basis</dt>
          <dd>{receiptGraph || "—"}</dd>
        </div>
      </dl>
      {lightControl}
    </section>
  );
}

export function ReviewWorkspace() {
  const [view, setView] = useState<ReviewView>("open");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState(activityParam);
  const [actionError, setActionError] = useState("");
  const [working, setWorking] = useState("");
  const [reason, setReason] = useState("");
  const [hold, setHold] = useState<{
    activityId: string;
    outcome: "confirmed" | "rejected";
  } | null>(null);
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [diffError, setDiffError] = useState("");
  const [queueWidth, setQueueWidth] = useState(() =>
    readStoredPanelSize("graphauthor.reviewQueueWidth", 420),
  );
  const live = useMemo(() => isLiveMode(), []);
  const [inspectedNode, setInspectedNode] = useState<MapNode | null>(null);
  const [packetIds, setPacketIds] = useState<string[]>([]);
  const [packetBusy, setPacketBusy] = useState(false);
  const [packetError, setPacketError] = useState("");

  useEffect(() => {
    storePanelSize("graphauthor.reviewQueueWidth", queueWidth);
  }, [queueWidth]);

  // Two polled reads, both paused while the tab is hidden. The proposal body
  // is fetched per selection below rather than pulling the whole proposal
  // table — the inspector only ever renders one.
  const queue = useResource((signal) => fetchActivities(signal), {
    enabled: live,
    pollMs: REVIEW_POLL_MS,
    watch: "operator",
    fallbackError: "Could not read review activity.",
  });
  const healthRead = useResource((signal) => fetchOperatorHealth(signal), {
    enabled: live,
    pollMs: REVIEW_POLL_MS,
    watch: "operator",
    fallbackError: "Could not read operator health.",
  });
  const proposalsRead = useResource((signal) => fetchProposals(signal), {
    enabled: live,
    pollMs: REVIEW_POLL_MS,
    watch: "operator",
    fallbackError: "Could not read proposals.",
  });
  const activities = queue.data ?? NO_ACTIVITIES;
  const health = healthRead.data ?? EMPTY_HEALTH;
  const loading = queue.loading;
  const refreshing = queue.refreshing || healthRead.refreshing;
  const error = visibleError(queue) || visibleError(healthRead);
  useBoundNotice(
    "review",
    error
      ? {
          slot: "block",
          kind: "unavailable",
          title: "Review could not be read",
          body: error,
        }
      : null,
  );
  useBoundNotice(
    "review-act",
    actionError
      ? {
          slot: "dock",
          kind: "fault",
          title: "That did not complete",
          body: actionError,
          dismissible: true,
        }
      : null,
  );
  const proposalsById = useMemo(() => {
    const next = new Map<string, ProposalVM>();
    for (const row of proposalsRead.data ?? []) next.set(row.proposal_id, row);
    return next;
  }, [proposalsRead.data]);

  const isException = (activity: ActivityVM) => {
    const proposalId = activity.ids.proposal_id;
    return Boolean(proposalId && proposalsById.get(proposalId)?.review_required);
  };

  // The map is a read of the graph, so a commit anywhere invalidates it: the
  // focus canvas used to keep showing the pre-confirm graph until a reload.
  const mapRead = useResource((signal) => fetchMapCached(undefined, signal), {
    enabled: live,
    watch: "graph",
  });
  const map: GraphMap | null = mapRead.data;
  const orientationRead = useResource(
    (signal) => orientGraph(undefined, "graph_card", signal),
    {
      enabled: live,
      watch: "graph",
      fallbackError: "Could not check proposal context.",
    },
  );

  // Reset node inspector and packet overlay when activity changes.
  useEffect(() => {
    setInspectedNode(null);
    setPacketIds([]);
    setPacketError("");
  }, [selectedId]);

  /**
   * Only open demands, oldest waiting first.
   *
   * `demand.open` is the queue's whole admission test, and it is a fact the
   * backend already states — an activity either carries an open demand on a
   * human or it is a record. Nothing else is filtered *in*; a settled activity
   * is history and reaches the operator through its subject.
   *
   * Oldest-first on both views, because the question a queue answers is "what
   * has been waiting longest", never "what happened most recently".
   */
  const openDemands = useMemo(
    () => activities.filter((activity) => activity.demand?.open),
    [activities],
  );

  const visible = useMemo(() => {
    const rows = openDemands.filter((activity) => {
      const incident = activity.demand?.kind === "incident";
      const exception = isException(activity);
      if (view === "incidents") return incident;
      if (view === "exceptions") return exception && !incident;
      return !incident && !exception;
    }).filter((activity) => matchesSearch(activity, search.trim()));
    rows.sort((a, b) => Date.parse(a.first_seen) - Date.parse(b.first_seen));
    return rows;
  }, [openDemands, proposalsById, search, view]);

  useEffect(() => {
    if (visible.some((activity) => activity.activity_id === selectedId)) return;
    if (hold?.activityId === selectedId) return;
    const next = visible[0]?.activity_id ?? "";
    setSelectedId(next);
    rememberActivity(next);
  }, [selectedId, visible, hold]);

  const selected =
    activities.find((activity) => activity.activity_id === selectedId) ??
    visible.find((activity) => activity.activity_id === selectedId);
  const proposalId = selected?.ids.proposal_id ?? "";
  const proposalRead = useResource(
    (signal) => fetchProposal(proposalId, signal),
    {
      enabled: live && Boolean(proposalId),
      deps: [proposalId],
      watch: "operator",
      fallbackError: "Could not read the proposal.",
    },
  );
  // Guard against showing the previous selection's proposal for one frame
  // while the new one is in flight.
  const proposal =
    proposalId && proposalRead.data?.proposal_id === proposalId
      ? proposalRead.data
      : undefined;

  /* The escalation behind the selected row.
     Fetched as a list and matched by handoff — there is no single-escalation
     endpoint, and the open set is small by construction: an escalation that
     stays open is a gap nobody has answered, and a product with many of those
     has a bigger problem than a fetch. */
  const handoffId = selected?.ids.handoff_id ?? "";
  const escalationsRead = useResource((signal) => fetchEscalations(signal), {
    enabled: live && Boolean(handoffId),
    deps: [handoffId],
    watch: "operator",
    fallbackError: "Could not read the escalation.",
  });
  const escalation = handoffId
    ? escalationsRead.data?.find((row) => row.handoffId === handoffId)
    : undefined;

  /**
   * Export the record.
   *
   * Written client-side from the verbatim log rather than asking the server for
   * a file, because the server has no export endpoint and inventing one would
   * put a second serialisation of the same truth in a second place. The bytes
   * here are `JSON.stringify` of exactly what `/operator/events` returned.
   *
   * The filename carries the date, so two exports never silently overwrite one
   * another in a downloads folder — the failure mode of every audit trail that
   * lands as `export.json`.
   */
  const [exporting, setExporting] = useState(false);
  const exportRecord = async () => {
    setExporting(true);
    setActionError("");
    try {
      const events = await fetchEventLog();
      const blob = new Blob([JSON.stringify(events, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `record-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      // Revoked on the next tick, not immediately. Tearing down the blob in the
      // same frame as the click races the browser's own read of it, and the
      // failure is a silently empty or missing file — the worst outcome for a
      // record export, because it looks like it worked.
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (err) {
      setActionError(actionErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  const predicate = escalation?.ungovernedPredicate ?? "";
  const priorRead = useResource((signal) => classifyAbsence(predicate, signal), {
    enabled: live && Boolean(predicate),
    deps: [predicate],
    watch: "operator",
    fallbackError: "",
  });
  const prior =
    predicate && priorRead.data?.predicate === predicate
      ? priorRead.data
      : undefined;

  useEffect(() => {
    setReason("");
    setActionError("");
  }, [proposal?.proposal_id]);

  useEffect(() => {
    setDiff(null);
    setDiffError("");
    if (!selected || !hasVersions(selected)) return;
    const controller = new AbortController();
    void fetchVersionDiff(
      String(selected.graph_revision_before),
      String(selected.graph_revision_after),
      controller.signal,
    )
      .then(setDiff)
      .catch((nextError) => {
        if (controller.signal.aborted) return;
        const message = actionErrorMessage(nextError);
        if (message) setDiffError(message);
      });
    return () => controller.abort();
  }, [selected?.activity_id, selected?.graph_revision_before, selected?.graph_revision_after]);

  const act = async (name: string, operation: () => Promise<unknown>) => {
    setWorking(name);
    setActionError("");
    try {
      await operation();
      if (
        selected &&
        (name === "confirm" || name === "reject")
      ) {
        setHold({
          activityId: selected.activity_id,
          outcome: name === "confirm" ? "confirmed" : "rejected",
        });
      }
      // Confirming writes the graph as well as the ledger. Announcing both is
      // what keeps the focus canvas here — and the map on the Graph page —
      // from continuing to show the version this action just replaced.
      invalidate("operator", "graph");
    } catch (nextError) {
      setActionError(actionErrorMessage(nextError));
    } finally {
      setWorking("");
    }
  };

  const select = (activity: ActivityVM) => {
    if (hold && hold.activityId !== activity.activity_id) setHold(null);
    setSelectedId(activity.activity_id);
    rememberActivity(activity.activity_id);
    setInspectedNode(null);
  };

  const continueFromHold = () => {
    setHold(null);
    const next = visible.find((activity) => activity.activity_id !== selectedId);
    if (next) {
      select(next);
      return;
    }
    setSelectedId("");
    rememberActivity("");
  };

  const intent: ReviewIntent = selected
    ? intentOf(selected, proposal)
    : "record";

  // The gate wrote why it refused into the event it emitted; the incident pane
  // should say that rather than making the operator open the record to find it.
  const incidentReason =
    selected?.events.find((event) => event.evidence_refs?.length)
      ?.evidence_refs?.[0] ?? "";

  const lightPacket = async () => {
    const receipt = proposal?.traversal_receipt;
    const recipe = String(receipt?.recipe_name ?? "").trim();
    if (!map || !recipe) return;
    const raw = receipt?.canonical_parameters;
    const params =
      raw && typeof raw === "object" && !Array.isArray(raw)
        ? (raw as Record<string, unknown>)
        : {};
    const versionRaw = Number(receipt?.recipe_version);
    setPacketBusy(true);
    setPacketError("");
    try {
      const next = await runNamedTraversal(map.graph_id, recipe, params, {
        version:
          Number.isFinite(versionRaw) && versionRaw > 0 ? versionRaw : undefined,
        graphVersion: map.graph_version,
      });
      if (next.kind === "INVALID_TRAVERSAL" || next.kind === "TRAVERSAL_FAILED") {
        throw new Error(
          next.errors?.map(String).join("; ") || "The traversal could not run.",
        );
      }
      const onMap = new Set(map.nodes.map((node) => node.id));
      setPacketIds(
        (next.evidence?.node_records ?? [])
          .map((node) => node.id)
          .filter((id) => onMap.has(id)),
      );
    } catch (reason) {
      setPacketError(
        actionErrorMessage(reason) || "The packet could not be lit.",
      );
    } finally {
      setPacketBusy(false);
    }
  };

  // Build the inline focus canvas model from the current activity + map.
  const canvasFocusIds = [
    ...new Set([...(selected ? focusIds(selected) : []), ...packetIds]),
  ];
  const canvasModel = useMemo(() => {
    if (!map || (!canvasFocusIds.length && !proposal)) return null;
    return buildFocusModel(map, canvasFocusIds, proposal);
  }, [map, canvasFocusIds.join("\0"), proposal]);

  const counts: Record<ReviewView, number> = {
    open: openDemands.filter(
      (a) => a.demand?.kind !== "incident" && !isException(a),
    ).length,
    exceptions: openDemands.filter(
      (a) => a.demand?.kind !== "incident" && isException(a),
    ).length,
    incidents: openDemands.filter((a) => a.demand?.kind === "incident").length,
  };

  return (
    <main className="review-workspace">
      <NoticeSurface />
      {/* Review's verbs, in the shell's instrument band.

          They used to be a second full-width band directly under the shell's
          own — one surface's answer to "where do page controls live", different
          from Graph's and different from Construct's (`chrome-constraints.md`
          §2.5). One place now, on every surface.

          The `<h1>Review</h1>` that led this row is gone: the tab above it
          already says Review, and a heading whose only job is to repeat the
          navigation is the same fact twice (§1.2). */}
      <Instrument>
        {/* Leads the band, as Find does on Graph.

            A locate control is the one an operator aims at without looking, so
            it is worth spending the one position that is the same on every
            surface on it. It used to sit third here and first there, which is a
            difference the two screens had no reason to have — and the whole
            point of a fixed instrument band is that moving between surfaces does
            not move your hands. */}
        <InstrumentGroup label="Search">
          <label className="review-search">
            <span className="sr-only">Search review activity</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search"
            />
          </label>
        </InstrumentGroup>

        {/* Ordinary waiting, review exceptions, and broken rules stay apart.
            Exceptions are still decisions, but they failed a graph.md check
            the ordinary queue should not bury. */}
        <InstrumentGroup label="Open demands">
          {(["open", "exceptions", "incidents"] as ReviewView[]).map((item) => (
            <button
              type="button"
              key={item}
              aria-pressed={view === item}
              onClick={() => setView(item)}
            >
              {item === "open"
                ? "Waiting"
                : item === "exceptions"
                  ? "Exceptions"
                  : "Incidents"}
              <span className="review-count">{counts[item]}</span>
            </button>
          ))}
        </InstrumentGroup>


        {/* The operator's reachability used to be a coloured dot beside the
            word that already said it — green for ready, red for not. Colour
            carrying what a word carries is the doctrine's oldest forbidden
            (§2.1), and the dot was the product's most visible instance of it.
            The word stays; the dot is gone. */}
        <InstrumentGroup label="Operator">
          {healthRead.hostUnreachable ? null : (
            <span
              className="review-reading"
              title={health.error || (health.ready ? "Operator ready" : "Operator unavailable")}
            >
              {health.ready ? "Ready" : "Unavailable"}
            </span>
          )}
          <button
            type="button"
            onClick={() => {
              void queue.refresh();
              void healthRead.refresh();
            }}
            disabled={refreshing}
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </InstrumentGroup>

        {/* The record's outlet. Instrument rather than identity: it acts on
            this operator's log, not on the product. */}
        <InstrumentGroup label="Record">
          <button type="button" onClick={() => void exportRecord()} disabled={exporting}>
            {exporting ? "Exporting…" : "Export"}
          </button>
        </InstrumentGroup>
      </Instrument>

      <div
        className="review-body"
        style={{ "--review-queue-width": `${queueWidth}px` } as CSSProperties}
      >
        <section id="review-queue" className="review-queue" aria-label="Review activity">
          {/* Swap on the active view so switching Waiting / Exceptions /
              Incidents changes the queue's subject with a fade rather than a
              cut in place. */}
          <Swap id={view}>
          {!live ? (
            <div className="review-empty">
              <strong>No operator host</strong>
              <span>
                Review reads a running operator plane; there is no fixture for
                it. Open the product with <code>?api=live</code>.
              </span>
            </div>
          ) : null}
          {live && loading ? <p className="review-empty">Loading review activity…</p> : null}
          {/* Which emptiness this is (`chrome-constraints.md` §3.4).

              Three different facts used to share one sentence. A cleared queue
              is an *achievement* and should read as one; a search that matched
              nothing is a dead end you back out of; and "nothing has been
              recorded yet" is a fourth state that is not this surface's problem
              any more, because the log is no longer here.

              "New work will appear here automatically" was the old copy for all
              of it. It described the plumbing, and it was the wrong thing to
              tell someone who had just finished their work. */}
          {live && !loading && queue.data !== null && !visible.length ? (
            <div className="review-empty">
              {search ? (
                <>
                  <strong>Nothing matches</strong>
                  <span>No open demand matches that ID or phrase.</span>
                </>
              ) : view === "incidents" ? (
                <>
                  <strong>No open incidents</strong>
                  <span>Nothing governed is currently broken.</span>
                </>
              ) : view === "exceptions" ? (
                <>
                  <strong>No review exceptions</strong>
                  <span>
                    Nothing waiting failed a required traversal, source, or
                    contradiction check.
                  </span>
                </>
              ) : (
                <>
                  <strong>Nothing is waiting on you</strong>
                  <span>
                    Every demand has been discharged. What happened is on
                    record — reach it from the node or proposal it concerns.
                  </span>
                </>
              )}
            </div>
          ) : null}
          {visible.map((activity) => (
            <button
              type="button"
              key={activity.activity_id}
              className={`review-row${selectedId === activity.activity_id ? " is-selected" : ""}`}
              onClick={() => select(activity)}
            >
              <span className={`review-row__mark review-row__mark--${activity.demand?.kind ?? activity.state.toLowerCase()}`} />
              <span className="review-row__main">
                <span className="review-row__summary">{activity.summary}</span>
                {/* Who, and nothing else. The row already carries a time — how
                    long this has been waiting, which is what the queue is
                    ordered by — and on a fresh demand `last_updated` is the
                    same value, so the row printed one fact twice (§2.2). Of the
                    two, waiting time is the one that decides what to pick up. */}
                <span className="review-row__meta">{activity.actor.label}</span>
              </span>
              {/* Every row here is an open demand now, so a "Needs me" tag on
                  some of them said nothing the list did not already say. What
                  is worth carrying is how long it has waited, which is what the
                  queue is ordered by. */}
              <span className="review-row__waiting">
                {relativeTime(activity.first_seen)}
              </span>
            </button>
          ))}
          </Swap>
        </section>

        <ResizableDivider
          className="review-divider"
          label="Resize review queue"
          controls="review-queue"
          size={queueWidth}
          defaultSize={420}
          minSize={280}
          maxSize={720}
          minTrailingSize={420}
          cssVariable="--review-queue-width"
          onResize={setQueueWidth}
        />

        <aside className="review-inspector" aria-label="Activity details">
          {/* Nothing to select is not the same as nothing selected.

              "Select an activity" used to fill this pane whenever `selected`
              was falsy — including when the queue was empty, where it invited
              an action that could not be taken and put a second empty state
              beside the one that had already explained the screen. Two empties
              saying different things about one condition (§3.4).

              With a queue behind it the invitation is true and worth making;
              with an empty queue this side simply has nothing to say, and says
              nothing. */}
          {!selected ? (
            visible.length ? (
              <div className="review-empty">
                <strong>Select a demand</strong>
                <span>Its record, evidence and the graph it touches open here.</span>
              </div>
            ) : null
          ) : (
            <Swap id={selected.activity_id}>
            <>
              <header className="review-inspector__header">
                <div>
                  <h2>{selected.summary}</h2>
                  <p className="review-inspector__who">
                    {selected.actor.label} · {relativeTime(selected.last_updated)}
                  </p>
                </div>
                <span className={`review-state review-state--${hold && selected.activity_id === hold.activityId ? "settled" : selected.state.toLowerCase()}`}>
                  {hold && selected.activity_id === hold.activityId
                    ? hold.outcome === "confirmed"
                      ? "entered"
                      : "rejected"
                    : stateLabel(selected)}
                </span>
              </header>

              {/* The action comes first. It is why this row is in the queue,
                  and it used to sit below a canvas, off the bottom of the
                  screen. */}
              {hold && selected?.activity_id === hold.activityId ? (
                <section className="review-decision" aria-labelledby="settled-heading">
                  <h3 id="settled-heading">
                    {hold.outcome === "confirmed"
                      ? "This change is in the graph"
                      : "This change was rejected"}
                  </h3>
                  <p>
                    {hold.outcome === "confirmed"
                      ? "It left the queue. The nodes are on the map; this record stays with them."
                      : "It left the queue and did not enter the graph."}
                  </p>
                  <div className="review-decision__actions">
                    <button
                      type="button"
                      className="is-primary"
                      onClick={continueFromHold}
                    >
                      {visible.some((activity) => activity.activity_id !== selectedId)
                        ? "Next waiting"
                        : "Done"}
                    </button>
                  </div>
                </section>
              ) : null}

              {intent === "decide" && proposal && !hold ? (
                <section className="review-decision" aria-labelledby="decision-heading">
                  <h3 id="decision-heading">Confirm or reject this change</h3>
                  <div className="review-decision__actions">
                    <button
                      type="button"
                      className="is-primary"
                      disabled={!health.can_commit || Boolean(working)}
                      onClick={() => void act("confirm", () => confirmProposal(proposal.proposal_id, ""))}
                    >
                      {working === "confirm" ? "Confirming…" : "Confirm change"}
                    </button>
                    <button
                      type="button"
                      disabled={Boolean(working)}
                      onClick={() => void act("reject", () => rejectProposal(proposal.proposal_id, reason.trim()))}
                    >
                      {working === "reject" ? "Rejecting…" : "Reject"}
                    </button>
                  </div>
                  <label>
                    Decision note <span>Optional</span>
                    <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
                  </label>
                </section>
              ) : null}

              {intent === "recover" && proposal ? (
                <section className="review-decision" aria-labelledby="recovery-heading">
                  <h3 id="recovery-heading">Requeue or close this proposal</h3>
                  <p>Requeueing returns it to the decision queue without erasing the failure below.</p>
                  <div className="review-decision__actions">
                    <button
                      type="button"
                      className="is-primary"
                      disabled={Boolean(working)}
                      onClick={() => void act("requeue", () => requeueProposal(proposal.proposal_id))}
                    >
                      {working === "requeue" ? "Requeueing…" : "Requeue proposal"}
                    </button>
                    <button
                      type="button"
                      disabled={Boolean(working)}
                      onClick={() => void act("reject", () => rejectProposal(proposal.proposal_id, reason.trim()))}
                    >
                      Reject
                    </button>
                  </div>
                  <label>
                    Decision note <span>Optional</span>
                    <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
                  </label>
                </section>
              ) : null}

              {intent === "resolve" ? (
                <section className="review-decision" aria-labelledby="incident-heading">
                  <h3 id="incident-heading">Acknowledge this incident</h3>
                  {incidentReason ? (
                    <p className="review-callout">{incidentReason}</p>
                  ) : null}
                  <label>
                    Acknowledgement note <span>Optional</span>
                    <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
                  </label>
                  <div className="review-decision__actions">
                    <button
                      type="button"
                      className="is-primary"
                      disabled={Boolean(working)}
                      onClick={() => void act("ack", () => acknowledgeIncident(selected.activity_id, reason.trim()))}
                    >
                      {working === "ack" ? "Acknowledging…" : "Acknowledge incident"}
                    </button>
                  </div>
                </section>
              ) : null}

              {/* What the agent could not settle, and the two ways to close it.
                  There is no third: encoding an answer is a graph edit, which
                  is the Graph surface's authority, not this one's. Offering a
                  half-built "encode" here would be a control that looks like it
                  writes and does not. */}
              {intent === "encode" ? (
                <section className="review-decision" aria-labelledby="encode-heading">
                  <h3 id="encode-heading">An agent could not govern this</h3>
                  {escalation ? (
                    <>
                      <p className="review-escalation__question">
                        {escalation.question}
                      </p>
                      <p className="review-handoff__note">
                        Nothing in the graph decides{" "}
                        <code>{escalation.ungovernedPredicate}</code>. Until
                        something does, every agent that reaches this question
                        will stop here.
                      </p>
                      {/* A structural guess, offered as one. It reads the graph's
                          shape around the predicate and says which way it leans;
                          it decides nothing and hides nothing, and the layer
                          that computes it insists on both. */}
                      {prior ? (
                        <p className="review-handoff__note">
                          Structurally, this is{" "}
                          {absencePriorLabel(prior.prior)} — advisory only.
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <p className="review-handoff__note">
                      Reading the escalation…
                    </p>
                  )}
                  <div className="review-decision__actions">
                    <button
                      type="button"
                      className="is-primary"
                      disabled={Boolean(working) || !escalation}
                      onClick={() =>
                        void act("defer", () =>
                          disposeEscalation(escalation!.handoffId, "deferred"),
                        )
                      }
                    >
                      {working === "defer" ? "Deferring…" : "Defer — real, not now"}
                    </button>
                    <button
                      type="button"
                      disabled={Boolean(working) || !escalation}
                      onClick={() =>
                        void act("dismiss", () =>
                          disposeEscalation(escalation!.handoffId, "dismissed"),
                        )
                      }
                    >
                      {working === "dismiss"
                        ? "Dismissing…"
                        : "Dismiss — needs no rule"}
                    </button>
                  </div>
                  {/* Deferring and dismissing are both closures, and the
                      difference between them is the whole point: one keeps the
                      gap true, the other says it never was. */}
                  <p className="review-handoff__note">
                    To answer it instead, encode a rule on the graph — that is a
                    graph edit, and it happens in Graph.
                  </p>
                </section>
              ) : null}

              {/* The demand is here; the work is not.
                  Approving a draft means reading its findings against its
                  source units, and none of that is on this screen. Review says
                  what is waiting and hands off to the surface that holds the
                  evidence — a decision that would otherwise be made by looking
                  at a summary is the definition of a rubber stamp. */}
              {intent === "handoff" ? (
                <section className="review-decision" aria-labelledby="handoff-heading">
                  <h3 id="handoff-heading">A construction run stopped for you</h3>
                  <p className="review-handoff__note">
                    It built a draft and will not publish until someone approves
                    it. The findings and the source they came from are in
                    Construct.
                  </p>
                  <div className="review-decision__actions">
                    <button
                      type="button"
                      className="is-primary"
                      onClick={() => {
                        window.location.hash = selected.mint_glue
                          ? `#/construct?api=live&run=${encodeURIComponent(selected.mint_glue)}`
                          : "#/construct?api=live";
                      }}
                    >
                      Open the run in Construct
                    </button>
                  </div>
                </section>
              ) : null}

              {intent === "record" && !hold ? (
                <p className="review-settled" role="status">
                  Recorded — nothing to decide here.
                </p>
              ) : null}

              {/* Exceptions and the packet first, then the patch, then the
                  map. The encode gate is why a recover row was refused, so it
                  stays after the change rather than heading ordinary review. */}
              {proposal ? (
                <TraversalPreflight
                  proposal={proposal}
                  currentGraphVersion={orientationRead.data?.graph_version ?? ""}
                  currentFormatFingerprint={
                    orientationRead.data?.graph_contract?.fingerprint ?? ""
                  }
                  onLightPacket={() => void lightPacket()}
                  lighting={packetBusy}
                  lightError={packetError}
                  packetLit={packetIds.length > 0}
                />
              ) : null}

              {proposal ? <ProposalChange proposal={proposal} /> : null}
              {proposal ? <ConstructionAudit proposal={proposal} /> : null}

              {canvasModel ? (
                <section className="review-focus" aria-label="Graph focus">
                  <header className="review-focus__header">
                    <h3 id="focus-heading">
                      {canvasModel.mode === "proposal" ? "Where it would attach" : "Where it sits"}
                    </h3>
                    <span className="review-focus__count">
                      {canvasModel.frameIds.length} node{canvasModel.frameIds.length === 1 ? "" : "s"}
                      {canvasModel.mode === "proposal" ? " · not yet in the graph" : ""}
                      {packetIds.length ? " · packet lit" : ""}
                    </span>
                  </header>
                  <div className="review-focus__stage">
                    <ProductGraphCanvas
                      data={canvasModel.data}
                      mode={canvasModel.mode}
                      frameIds={canvasModel.frameIds}
                      onSelect={(nodeId) =>
                        setInspectedNode(
                          nodeId
                            ? map?.nodes.find((n) => n.id === nodeId) ?? null
                            : null,
                        )
                      }
                    />
                  </div>
                  {inspectedNode ? (
                    <div className="review-focus__inspect">
                      <button
                        type="button"
                        className="review-focus__close"
                        onClick={() => setInspectedNode(null)}
                        aria-label="Close node detail"
                      >
                        ×
                      </button>
                      <strong>
                        {nodeDisplayLabel(inspectedNode.label, inspectedNode.kind)}
                      </strong>
                      <code>{inspectedNode.id}</code>
                      {inspectedNode.semantic_anchor ? (
                        <p className="review-focus__anchor">{inspectedNode.semantic_anchor}</p>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="review-inspector__links">
                    {focusIds(selected).length ? <a href={graphHref(selected, "focus")}>Open in graph</a> : null}
                    {hasVersions(selected) ? <a href={graphHref(selected, "diff")}>Open graph changes</a> : null}
                  </div>
                </section>
              ) : null}

              {hasVersions(selected) ? (
                <section className="review-inspector__section" aria-labelledby="diff-heading">
                  <h3 id="diff-heading">What changed in the graph</h3>
                  {diff ? (
                    <DiffSummary diff={diff} />
                  ) : diffError ? (
                    <NoticeCard kind="fault" body={diffError} />
                  ) : healthRead.hostUnreachable ? null : (
                    <p>Loading change summary…</p>
                  )}
                  <p className="review-versions">
                    <code>{String(selected.graph_revision_before)}</code>
                    <span>→</span>
                    <code>{String(selected.graph_revision_after)}</code>
                  </p>
                </section>
              ) : null}

              {intent === "recover" && proposal?.gate_report &&
              Object.keys(proposal.gate_report as object).length ? (
                <section className="review-inspector__section" aria-labelledby="gate-heading">
                  <h3 id="gate-heading">Why it was refused</h3>
                  <GateReport report={proposal.gate_report} />
                </section>
              ) : null}

              {/* The record is the audit trail, not the task. It stays
                  available and stops competing with the decision. */}
              <details className="review-record">
                <summary>
                  Activity record · {selected.events.length} event
                  {selected.events.length === 1 ? "" : "s"}
                </summary>
                <ol className="review-events">
                  {[...selected.events].reverse().map((event) => (
                    <li key={event.event_id}>
                      <span />
                      <div>
                        <strong>{eventTypeLabel(event.type)}</strong>
                        <p>{event.actor_id || event.actor_kind} · {relativeTime(event.occurred_at)}</p>
                        <code>{event.type}</code>
                      </div>
                    </li>
                  ))}
                </ol>
                {focusIds(selected).length ? (
                  <div className="review-chips">
                    {focusIds(selected).map((id) => <code key={id}>{id}</code>)}
                  </div>
                ) : null}
                <dl className="review-facts">
                  <div><dt>Activity</dt><dd>{selected.activity_id}</dd></div>
                  <div><dt>Kind</dt><dd>{selected.kind}</dd></div>
                </dl>
              </details>
            </>
            </Swap>
          )}
        </aside>
      </div>
    </main>
  );
}
