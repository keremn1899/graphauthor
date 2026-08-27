import { useEffect, useMemo, useRef, useState } from "react";
import {
  EMPTY_FACETS,
  PRESETS,
  filterActivities,
  kindLabel,
  relativeTime,
  stateLabel,
  type ActivityFamily,
  type ActivityKind,
  type ActivityVM,
  type ActivityWeight,
  type ActorKind,
  type AuthorityType,
  type FeedFacets,
  type FeedPreset,
} from "./ledgerFeedModel";
import {
  MORNING_TAPE,
  SIM_DURATION_MS,
  SIM_ORIGIN_MS,
  buildOperatorInject,
  formatLabClock,
  nextBeatAt,
  reduceTapeToClock,
  type TapeEvent,
} from "./ledgerFeedSim";
import {
  canFocusActivity,
  canOpenProposal,
  canOpenVersionDiff,
  focusSetForActivity,
  graphDiffHrefForActivity,
  graphMapHrefForActivity,
  seamHrefForActivity,
} from "./platformCoreScenario";
import {
  confirmProposal,
  fetchActivities,
  fetchOperatorHealth,
  fetchProposals,
  fetchVersionDiff,
  isLiveMode,
  rejectProposal,
  requeueProposal,
  type OperatorHealth,
  type ProposalVM,
  type VersionDiff,
} from "../../api/ledger";
import { ApiError } from "../../api/client";
import {
  createMotionPlans,
  motionPoseKeyframes,
} from "../../styles/motion";
import { useMotion } from "../../styles/useMotion";
import {
  edgeStatement,
  proposalStatusLabel,
} from "../../shared/protocolVocabulary";
import "./LedgerFeedLabPage.css";

const PRODUCT_LEDGER_MOTION = createMotionPlans();

/**
 * Lab rows carry ordinal checkpoints (`V13`); live rows carry the engine's
 * opaque version id, where a `V` prefix would read as nonsense.
 */
function formatRevision(rev: string | number | undefined): string {
  if (rev == null) return "—";
  return typeof rev === "number" ? `V${rev}` : rev;
}

const WEIGHT_OPTIONS: ActivityWeight[] = ["ambient", "notable", "demanding"];
const ACTOR_OPTIONS: ActorKind[] = ["human", "agent", "gate", "system"];
const FAMILY_OPTIONS: ActivityFamily[] = [
  "decisions",
  "proposals",
  "graph_writes",
  "conformance",
  "failures",
  "l1_autonomous",
  "batches",
  "queries",
  "system",
];
const AUTHORITY_OPTIONS: AuthorityType[] = [
  "human",
  "agent",
  "gate",
  "query",
  "construction",
  "system",
  "gate_auto_l1",
];
const LIVE_KIND_OPTIONS: ActivityKind[] = [
  "gap",
  "incident",
  "interrogation",
  "misc",
];
const SPEEDS = [1, 2, 4] as const;
const LIVE_PRESETS: FeedPreset[] = ["needs_me", "incidents", "all"];
const FIXTURE_PRESETS: FeedPreset[] = [
  "living",
  "watch_live",
  "needs_me",
  "incidents",
];

function toggleFacet<T extends string>(list: T[], value: T): T[] {
  return list.includes(value)
    ? list.filter((item) => item !== value)
    : [...list, value];
}

function emphasisClass(activity: ActivityVM) {
  if (activity.state === "SETTLED") return "is-settled";
  if (activity.weight === "ambient") return "is-ambient";
  if (activity.demand?.kind === "incident" && activity.demand.open) {
    return "is-incident";
  }
  if (activity.needs_me || activity.weight === "demanding") {
    return "is-actionable";
  }
  return "is-notable";
}

function actorGlyph(kind: ActorKind) {
  if (kind === "human") return "H";
  if (kind === "agent") return "A";
  if (kind === "gate") return "G";
  return "S";
}

function authorityLabel(authority: AuthorityType) {
  if (authority === "gate_auto_l1") return "L1 gate";
  if (authority === "human") return "Human";
  if (authority === "agent") return "Agent";
  if (authority === "gate") return "Gate";
  if (authority === "query") return "Query";
  if (authority === "construction") return "Construction";
  return "System";
}

function weightLabel(weight: ActivityWeight) {
  if (weight === "ambient") return "Background";
  if (weight === "demanding") return "Needs attention";
  return "Notable";
}

type LiveAction =
  | { kind: "confirm"; primarySource: string }
  | { kind: "reject"; reason: string }
  | { kind: "requeue" };

function ActivityRow({
  activity,
  open,
  onToggle,
  nowMs,
  onOperatorAction,
  live,
  proposal,
  health,
  busy,
  actionError,
  onLiveAction,
  productMode = false,
  selected = false,
  detailOnly = false,
  arrivalIndex = 0,
}: {
  activity: ActivityVM;
  open: boolean;
  onToggle: () => void;
  nowMs: number;
  onOperatorAction: (
    activity: ActivityVM,
    action: "disposition" | "acknowledge",
  ) => void;
  live: boolean;
  proposal?: ProposalVM;
  health: OperatorHealth | null;
  busy: boolean;
  actionError?: string;
  onLiveAction: (activity: ActivityVM, action: LiveAction) => void;
  productMode?: boolean;
  selected?: boolean;
  detailOnly?: boolean;
  arrivalIndex?: number;
}) {
  const arrival = useMotion<HTMLElement>();
  const [primarySource, setPrimarySource] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [versionDiff, setVersionDiff] = useState<VersionDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);
  const needsDisposition = activity.needs_me;
  const needsAck =
    !needsDisposition &&
    activity.demand?.kind === "incident" &&
    activity.demand.open;
  const hasLiveVersionPair =
    live &&
    typeof activity.graph_revision_before === "string" &&
    typeof activity.graph_revision_after === "string" &&
    activity.graph_revision_before !== activity.graph_revision_after;

  useEffect(() => {
    if (!productMode || detailOnly) return;
    arrival.play(
      motionPoseKeyframes(
        {
          y: -PRODUCT_LEDGER_MOTION.emit.field.travel,
          scale: 0.994,
          opacity: 0,
        },
        { y: 0, scale: 1, opacity: 1 },
      ),
      PRODUCT_LEDGER_MOTION.emit,
      { delay: Math.min(arrivalIndex, 8) * 26, fill: "backwards" },
    );
  }, [arrival, arrivalIndex, detailOnly, productMode]);

  const loadVersionDiff = async () => {
    if (
      typeof activity.graph_revision_before !== "string" ||
      typeof activity.graph_revision_after !== "string"
    ) {
      return;
    }
    setDiffLoading(true);
    setDiffError(null);
    try {
      setVersionDiff(
        await fetchVersionDiff(
          activity.graph_revision_before,
          activity.graph_revision_after,
        ),
      );
    } catch (e: unknown) {
      setDiffError(e instanceof ApiError ? e.message : "Could not read this diff.");
    } finally {
      setDiffLoading(false);
    }
  };

  return (
    <article
      ref={arrival.ref}
      className={[
        "ledger-feed__row",
        emphasisClass(activity),
        activity.hot ? "is-hot" : "",
        open ? "is-open" : "",
        selected ? "is-selected" : "",
        detailOnly ? "is-detail-only" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {detailOnly ? null : <button
        type="button"
        className="ledger-feed__row-main"
        onClick={onToggle}
        aria-expanded={open}
        aria-pressed={selected}
      >
        <span className="ledger-feed__emphasis" aria-hidden />
        <span
          className={`ledger-feed__actor is-${activity.actor.kind}`}
          title={activity.actor.kind}
        >
          {actorGlyph(activity.actor.kind)}
        </span>
        <span className="ledger-feed__copy">
          <strong>{activity.summary}</strong>
          <small>
            {activity.actor.label}
            {" · "}
            started {relativeTime(activity.first_seen, nowMs)}
            {" · "}
            moved {relativeTime(activity.last_updated, nowMs)}
            {activity.reconstructed ? " · inferred transitions" : ""}
          </small>
        </span>
        <span className="ledger-feed__meta">
          <span className="ledger-feed__badge">{kindLabel(activity.kind)}</span>
          <span className="ledger-feed__badge is-state">
            {stateLabel(activity)}
          </span>
          <span className="ledger-feed__badge">
            {authorityLabel(activity.authority_type)}
          </span>
          {activity.graph_revision_before != null &&
          activity.graph_revision_after != null ? (
            <span className="ledger-feed__badge is-graph">
              {formatRevision(activity.graph_revision_before)} →{" "}
              {formatRevision(activity.graph_revision_after)}
            </span>
          ) : null}
          <span className="ledger-feed__count">
            {activity.events.length} event
            {activity.events.length === 1 ? "" : "s"}
          </span>
        </span>
      </button>}

      {(!productMode || detailOnly) && live && needsDisposition ? (
        <div className="ledger-feed__action is-live">
          {proposal?.status === "PENDING" ? (
            <>
              <label>
                <span>Primary source</span>
                <input
                  value={primarySource}
                  onChange={(event) => setPrimarySource(event.target.value)}
                  placeholder="Policy, ADR, handbook §…"
                  disabled={busy}
                />
              </label>
              <button
                type="button"
                onClick={() =>
                  onLiveAction(activity, {
                    kind: "confirm",
                    primarySource: primarySource.trim(),
                  })
                }
                disabled={
                  busy ||
                  !primarySource.trim() ||
                  (!health?.can_commit &&
                    !proposal.target_gap_id.startsWith("exclusion:"))
                }
                title={
                  !health?.can_commit &&
                  !proposal.target_gap_id.startsWith("exclusion:")
                    ? "The operator plane has no gate provider configured."
                    : "Confirm through the server gate."
                }
              >
                {busy ? "Working…" : "Confirm"}
              </button>
              {!health?.can_commit &&
              !proposal.target_gap_id.startsWith("exclusion:") ? (
                <span className="ledger-feed__action-note">
                  Confirm unavailable: this operator has no gate battery.
                </span>
              ) : null}
              <label>
                <span>Reject reason</span>
                <input
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  placeholder="Optional"
                  disabled={busy}
                />
              </label>
              <button
                type="button"
                onClick={() =>
                  onLiveAction(activity, {
                    kind: "reject",
                    reason: rejectReason.trim(),
                  })
                }
                disabled={busy}
              >
                Reject
              </button>
            </>
          ) : proposal &&
            ["GRAIN_FAILED", "GATE_FAILED", "ENCODE_FAILED"].includes(
              proposal.status,
            ) ? (
            <>
              <button
                type="button"
                onClick={() => onLiveAction(activity, { kind: "requeue" })}
                disabled={busy}
              >
                {busy ? "Working…" : "Requeue"}
              </button>
              <label>
                <span>Reject reason</span>
                <input
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  placeholder="Optional"
                  disabled={busy}
                />
              </label>
              <button
                type="button"
                onClick={() =>
                  onLiveAction(activity, {
                    kind: "reject",
                    reason: rejectReason.trim(),
                  })
                }
                disabled={busy}
              >
                Reject
              </button>
            </>
          ) : (
            <span className="ledger-feed__action-note">
              This activity needs attention, but no disposable proposal is
              attached.
            </span>
          )}
          {actionError ? (
            <span className="ledger-feed__action-error" role="alert">
              {actionError}
            </span>
          ) : null}
        </div>
      ) : (!productMode || detailOnly) && !live && (needsDisposition || needsAck) ? (
        <div className="ledger-feed__action">
          {needsDisposition ? (
            <button
              type="button"
              onClick={() => onOperatorAction(activity, "disposition")}
              title="Lab-local inject — operator API not wired"
            >
              Disposition (lab)
            </button>
          ) : null}
          {needsAck ? (
            <button
              type="button"
              onClick={() => onOperatorAction(activity, "acknowledge")}
              title="Lab-local ack store — ack event not yet in lifecycle"
            >
              Acknowledge (lab)
            </button>
          ) : null}
        </div>
      ) : null}

      {open && (!productMode || detailOnly) ? (
        <div className="ledger-feed__expand">
          {live && proposal ? (
            <section className="ledger-feed__proposal">
              <p className="ledger-feed__section-label">Proposal</p>
              <p>
                <code>{proposal.proposal_id}</code>
                {" · "}
                {proposalStatusLabel(proposal.status)}
                {" · "}
                {proposal.claim_level}
              </p>
              <p>
                {proposal.nodes.length} node
                {proposal.nodes.length === 1 ? "" : "s"} ·{" "}
                {proposal.edges.length} edge
                {proposal.edges.length === 1 ? "" : "s"}
              </p>
              {proposal.nodes.length ? (
                <ul>
                  {proposal.nodes.map((node) => (
                    <li key={node.id}>
                      <strong>{node.label}</strong> <code>{node.id}</code>
                    </li>
                  ))}
                </ul>
              ) : null}
              {proposal.demotion_reason ? (
                <p className="ledger-feed__proposal-note">
                  {proposal.demotion_reason}
                </p>
              ) : null}
            </section>
          ) : null}
          <section>
            <p className="ledger-feed__section-label">
              How this activity developed
            </p>
            <ol className="ledger-feed__causation">
              {activity.causation.map((eventId, index) => {
                const event = activity.events.find(
                  (item) => item.event_id === eventId,
                );
                return (
                  <li key={eventId}>
                    <span>{index + 1}</span>
                    <div>
                      <p>{event?.summary ?? eventId}</p>
                      <code>{event?.type ?? eventId}</code>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>

          <section>
            <p className="ledger-feed__section-label">Recorded events</p>
            <ol className="ledger-feed__events">
              {activity.events.map((event) => (
                <li
                  key={event.event_id}
                  className={[
                    event.degraded ? "is-degraded" : "",
                    event.inferred ? "is-inferred" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <p>{event.summary}</p>
                  <code>{event.type}</code>
                  <small>
                    {event.actor_kind}
                    {event.outcome ? ` · ${event.outcome}` : ""}
                    {event.inferred ? " · inferred" : ""}
                    {event.degraded ? " · engine_degraded" : ""}
                    {event.causation_event_id
                      ? ` · caused by ${event.causation_event_id}`
                      : ""}
                  </small>
                </li>
              ))}
            </ol>
          </section>

          {activity.evidence?.length || activity.gate_findings?.length ? (
            <section className="ledger-feed__evidence">
              {activity.evidence?.length ? (
                <div>
                  <p className="ledger-feed__section-label">Evidence</p>
                  <ul>
                    {activity.evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {activity.gate_findings?.length ? (
                <div>
                  <p className="ledger-feed__section-label">Gate findings</p>
                  <ul>
                    {activity.gate_findings.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="ledger-feed__seams">
            <p className="ledger-feed__section-label">Graph</p>
            <div className="ledger-feed__seam-actions">
              {canFocusActivity(activity) ? (
                <a
                  className="ledger-feed__seam-link"
                  href={
                    live
                      ? graphMapHrefForActivity(activity)
                      : seamHrefForActivity(activity, "focus")
                  }
                >
                  Focus nodes ({focusSetForActivity(activity).length})
                </a>
              ) : (
                <button type="button" disabled title="No graph focus">
                  Focus nodes
                </button>
              )}
              {hasLiveVersionPair ? (
                <button
                  type="button"
                  onClick={() => void loadVersionDiff()}
                  disabled={diffLoading}
                >
                  {diffLoading
                    ? "Reading diff…"
                    : versionDiff
                      ? "Refresh version diff"
                      : "Open version diff"}
                </button>
              ) : canOpenVersionDiff(activity) ? (
                <a
                  className="ledger-feed__seam-link"
                  href={seamHrefForActivity(activity, "diff")}
                >
                  Open version diff {formatRevision(activity.graph_revision_before)}
                  →{formatRevision(activity.graph_revision_after)}
                </a>
              ) : (
                <button type="button" disabled>
                  Open version diff
                </button>
              )}
              {!live && canOpenProposal(activity) ? (
                <a
                  className="ledger-feed__seam-link"
                  href={seamHrefForActivity(activity, "proposal")}
                >
                  Open proposal {activity.ids.proposal_id}
                </a>
              ) : (
                <button type="button" disabled>
                  {live && proposal ? "Proposal shown above" : "Open proposal"}
                  {!live && activity.ids.proposal_id
                    ? ` ${activity.ids.proposal_id}`
                    : ""}
                </button>
              )}
            </div>
            <p className="ledger-feed__seam-note">
              {live
                ? "Focus opens the nodes recorded on this activity in the committed graph."
                : "Deep-links Screen 1 with activity · proposal · focus · gv (lab scenario mirrors /operator contract)."}
            </p>
          </section>

          {live && (versionDiff || diffError) ? (
            <section className="ledger-feed__diff">
              <p className="ledger-feed__section-label">
                Version diff {formatRevision(activity.graph_revision_before)} →{" "}
                {formatRevision(activity.graph_revision_after)}
              </p>
              {diffError ? (
                <p className="ledger-feed__action-error" role="alert">
                  {diffError}
                </p>
              ) : versionDiff ? (
                <>
                <a
                  className="ledger-feed__seam-link"
                  href={graphDiffHrefForActivity(activity)}
                >
                  Show this diff on the graph
                </a>
                <ul>
                  {versionDiff.nodes_added.map((node) => (
                    <li key={`na:${node.id}`}>
                      <code>+ node</code> {node.label}{" "}
                      <small>{node.id}</small>
                    </li>
                  ))}
                  {versionDiff.nodes_removed.map((node) => (
                    <li key={`nr:${node.id}`}>
                      <code>− node</code> {node.label}{" "}
                      <small>{node.id}</small>
                    </li>
                  ))}
                  {versionDiff.nodes_changed.map((node) => (
                    <li key={`nc:${node.id}`}>
                      <code>~ node</code> {node.id}
                    </li>
                  ))}
                  {versionDiff.edges_added.map(([type, source, target, label]) => (
                    <li key={`ea:${type}:${source}:${target}:${label}`}>
                      <code title={`Protocol type: ${type}`}>+ edge</code>{" "}
                      {edgeStatement(type, source, target)}
                      {label ? ` · ${label}` : ""}
                    </li>
                  ))}
                  {versionDiff.edges_removed.map(
                    ([type, source, target, label]) => (
                      <li key={`er:${type}:${source}:${target}:${label}`}>
                        <code title={`Protocol type: ${type}`}>− edge</code>{" "}
                        {edgeStatement(type, source, target)}
                        {label ? ` · ${label}` : ""}
                      </li>
                    ),
                  )}
                  {!versionDiff.nodes_added.length &&
                  !versionDiff.nodes_removed.length &&
                  !versionDiff.nodes_changed.length &&
                  !versionDiff.edges_added.length &&
                  !versionDiff.edges_removed.length ? (
                    <li>No structural changes.</li>
                  ) : null}
                </ul>
                </>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

export function LedgerFeedLabPage({
  productMode = false,
}: {
  productMode?: boolean;
} = {}) {
  const live = useMemo(() => isLiveMode(), []);
  const [preset, setPreset] = useState<FeedPreset>(
    live ? "needs_me" : "living",
  );
  const [facets, setFacets] = useState<FeedFacets>(EMPTY_FACETS);
  const [liveKinds, setLiveKinds] = useState<ActivityKind[]>([]);
  const [linkageQuery, setLinkageQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(() => {
    const hash = window.location.hash;
    const q = hash.indexOf("?");
    if (q < 0) return null;
    return new URLSearchParams(hash.slice(q + 1)).get("activity");
  });
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(2);
  const [clockMs, setClockMs] = useState(0);
  const [injects, setInjects] = useState<TapeEvent[]>([]);
  const [showTape, setShowTape] = useState(false);
  const [liveRows, setLiveRows] = useState<ActivityVM[] | null>(null);
  const [liveProposals, setLiveProposals] = useState<ProposalVM[]>([]);
  const [liveHealth, setLiveHealth] = useState<OperatorHealth | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const [refreshKey, setRefreshKey] = useState(0);

  const clockRef = useRef(clockMs);
  clockRef.current = clockMs;

  useEffect(() => {
    const syncOpen = () => {
      const hash = window.location.hash;
      const q = hash.indexOf("?");
      if (q < 0) return;
      const activity = new URLSearchParams(hash.slice(q + 1)).get("activity");
      if (activity) setOpenId(activity);
    };
    window.addEventListener("hashchange", syncOpen);
    return () => window.removeEventListener("hashchange", syncOpen);
  }, []);

  useEffect(() => {
    if (live || !playing) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const delta = (now - last) * speed;
      last = now;
      setClockMs((current) => {
        const next = Math.min(SIM_DURATION_MS, current + delta);
        if (next >= SIM_DURATION_MS) setPlaying(false);
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [live, playing, speed]);

  // Live mode replaces the tape outright rather than seeding it: the playhead
  // is a fixture affordance for watching a scripted morning, and a real ledger
  // has no scrub bar — it has whatever the event log says right now.
  useEffect(() => {
    if (!live) return;
    const abort = new AbortController();
    const load = () => {
      Promise.all([
        fetchActivities(abort.signal),
        fetchProposals(abort.signal),
        fetchOperatorHealth(abort.signal),
      ])
        .then(([rows, proposals, health]) => {
          if (!abort.signal.aborted) {
            setLiveRows(rows);
            setLiveProposals(proposals);
            setLiveHealth(health);
            setLiveError(null);
          }
        })
        .catch((e: unknown) => {
          if (!abort.signal.aborted) {
            setLiveError(e instanceof ApiError ? e.message : "Could not read activities.");
          }
        });
    };
    void load();
    // The projection is a live fold of the event log, so a poll is the whole
    // subscription. Slow on purpose — this is an operator plane, not a ticker.
    const timer = window.setInterval(load, 5000);
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [live, refreshKey]);

  const tapeActivities = useMemo(
    () => reduceTapeToClock(MORNING_TAPE, clockMs, injects),
    [clockMs, injects],
  );
  // Never substitute the lab tape for an unavailable live event log. On the
  // trust plane, invented continuity is worse than an explicit empty/error.
  const activities = live ? liveRows ?? [] : tapeActivities;
  const proposalsById = useMemo(
    () => new Map(liveProposals.map((proposal) => [proposal.proposal_id, proposal])),
    [liveProposals],
  );

  const filteredRows = useMemo(
    () => filterActivities(activities, preset, facets),
    [activities, preset, facets],
  );
  const rows = useMemo(() => {
    const query = linkageQuery.trim().toLowerCase();
    return filteredRows.filter((activity) => {
      if (liveKinds.length && !liveKinds.includes(activity.kind)) return false;
      if (!query) return true;
      const glue = [
        activity.activity_id,
        ...Object.values(activity.ids),
        ...(activity.subject_node_ids ?? activity.node_ids),
      ];
      return glue.some((value) => value?.toLowerCase().includes(query));
    });
  }, [filteredRows, linkageQuery, liveKinds]);

  useEffect(() => {
    if (!productMode || !rows.length) return;
    if (rows.some((activity) => activity.activity_id === openId)) return;
    setOpenId(rows[0].activity_id);
  }, [openId, productMode, rows]);

  const selectedActivity =
    rows.find((activity) => activity.activity_id === openId) ?? rows[0];

  const simNow = SIM_ORIGIN_MS + clockMs;
  const appliedCount = MORNING_TAPE.filter((b) => b.at_ms <= clockMs).length;
  const nextAt = nextBeatAt(MORNING_TAPE, clockMs);

  const pickPreset = (next: FeedPreset) => {
    setPreset(next);
    setFacets(EMPTY_FACETS);
  };

  const reset = () => {
    setClockMs(0);
    setInjects([]);
    setOpenId(null);
    setPlaying(true);
  };

  const jumpNext = () => {
    const at = nextBeatAt(MORNING_TAPE, clockRef.current);
    if (at == null) {
      setClockMs(SIM_DURATION_MS);
      setPlaying(false);
      return;
    }
    setClockMs(at);
  };

  const onOperatorAction = (
    activity: ActivityVM,
    action: "disposition" | "acknowledge",
  ) => {
    const at = clockRef.current + 50;
    const beat = buildOperatorInject(
      action === "acknowledge"
        ? { kind: "acknowledge", activity_id: activity.activity_id }
        : {
            kind: "disposition",
            activity_id: activity.activity_id,
            outcome: "approved",
          },
      at,
    );
    setInjects((current) => [...current, beat]);
    setClockMs(at);
  };

  const onLiveAction = async (activity: ActivityVM, action: LiveAction) => {
    const proposalId = activity.ids.proposal_id;
    if (!proposalId || actionBusy) return;
    setActionBusy(activity.activity_id);
    setActionErrors((current) => {
      const next = { ...current };
      delete next[activity.activity_id];
      return next;
    });
    try {
      if (action.kind === "confirm") {
        await confirmProposal(proposalId, action.primarySource);
      } else if (action.kind === "reject") {
        await rejectProposal(proposalId, action.reason);
      } else {
        await requeueProposal(proposalId);
      }
    } catch (e: unknown) {
      setActionErrors((current) => ({
        ...current,
        [activity.activity_id]:
          e instanceof ApiError ? e.message : "The operator action failed.",
      }));
    } finally {
      // A refused confirm can still transition the proposal to GRAIN_FAILED,
      // GATE_FAILED, or ENCODE_FAILED. Refresh after errors too; the response
      // status is not proof that server state stayed unchanged.
      setRefreshKey((value) => value + 1);
      setActionBusy(null);
    }
  };

  return (
    <main
      className={
        productMode ? "ledger-feed ledger-feed--product" : "ledger-feed"
      }
    >
      <header className="ledger-feed__header">
        <div>
          <p className="ledger-feed__eyebrow">
            {productMode ? "Operator" : "Screen 2 · Ledger"}
          </p>
          <h1>{productMode ? "Review" : "Activity feed"}</h1>
          <p className="ledger-feed__lede">
            {productMode
              ? "Decide what needs you and inspect the recorded history behind it."
              : live
                ? "The operator's append-only event log, folded into activity arcs. Figure-ground by weight; presets over facets."
                : "Live morning scenario on an event tape → reducer → ActivityVM. Figure-ground by weight; presets over facets. Operator actions are lab-local injects."}
          </p>
          {!productMode ? (
            <p className="ledger-feed__nav">
              <a href="#/explorations">Explorations</a>
              {" · "}
              <a href="#/explorations/canvas-linkage">Canvas linkage</a>
              {" · "}
              <a href="#/construct?api=live">Construct</a>
              {" · "}
              <a href="#/explorations/ambient-canvas">Ambient canvas</a>
            </p>
          ) : null}
        </div>
        <aside className="ledger-feed__principle">
          <span>{productMode ? "Attention" : "Figure-ground"}</span>
          <strong>
            {productMode
              ? "Open decisions stay visible."
              : "The 99% flows. The 1% stays marked."}
          </strong>
          <p>
            {productMode
              ? "New activity is ordered by what needs you; settled history remains available."
              : "Urgency is persistence, not motion. Hot arrival fades; demanding rows hold until resolved."}
          </p>
        </aside>
      </header>

      {live ? null : (
        // Only true of the tape. A live feed folds the append-only event log,
        // which is the record — nothing about it is reconstructed, so showing
        // this over real data would be a false disclaimer.
        <div className="ledger-feed__banner" role="status">
          Partial history — reconstructed, not recorded. Until the append-only
          events table ships, arcs may carry inferred transitions.
        </div>
      )}

      {live ? null : (
      <div className="ledger-feed__transport" aria-label="Scenario transport">
        <div className="ledger-feed__transport-main">
          <button
            type="button"
            onClick={() => setPlaying((value) => !value)}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button type="button" onClick={jumpNext}>
            Next beat
          </button>
          <button type="button" onClick={reset}>
            Reset
          </button>
          <div className="ledger-feed__speeds">
            {SPEEDS.map((value) => (
              <button
                key={value}
                type="button"
                className={speed === value ? "is-active" : ""}
                onClick={() => setSpeed(value)}
              >
                {value}×
              </button>
            ))}
          </div>
          <button
            type="button"
            className={showTape ? "is-active" : ""}
            onClick={() => setShowTape((value) => !value)}
          >
            {showTape ? "Hide tape" : "Show tape"}
          </button>
        </div>
        <div className="ledger-feed__scrub">
          <input
            type="range"
            min={0}
            max={SIM_DURATION_MS}
            step={500}
            value={clockMs}
            onChange={(event) => {
              setPlaying(false);
              setClockMs(Number(event.target.value));
            }}
            aria-label="Lab clock"
          />
          <span>
            t={formatLabClock(clockMs)} / {formatLabClock(SIM_DURATION_MS)}
            {" · "}
            {appliedCount}/{MORNING_TAPE.length} beats
            {nextAt != null
              ? ` · next ${formatLabClock(nextAt)}`
              : " · end"}
          </span>
        </div>
      </div>
      )}

      {showTape ? (
        <ol className="ledger-feed__tape">
          {MORNING_TAPE.map((beat) => (
            <li
              key={beat.event_id}
              className={beat.at_ms <= clockMs ? "is-applied" : ""}
            >
              <button
                type="button"
                onClick={() => {
                  setPlaying(false);
                  setClockMs(beat.at_ms);
                }}
              >
                <code>{formatLabClock(beat.at_ms)}</code>
                <span>{beat.type}</span>
                <small>{beat.activity_id}</small>
              </button>
            </li>
          ))}
        </ol>
      ) : null}

      <div
        className={
          productMode
            ? "ledger-feed__product-layout"
            : "ledger-feed__standard-flow"
        }
      >
      <section className="ledger-feed__queue">
      <div className="ledger-feed__controls">
        <div
          className="ledger-feed__presets"
          role="tablist"
          aria-label="Feed presets"
        >
          {(live ? LIVE_PRESETS : FIXTURE_PRESETS).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={preset === id}
              className={preset === id ? "is-active" : ""}
              onClick={() => pickPreset(id)}
              title={PRESETS[id].note}
            >
              {PRESETS[id].label}
            </button>
          ))}
        </div>
      </div>

      <div
        className="ledger-feed__facets"
        aria-label={productMode ? "Activity filters" : "Facets"}
      >
        {live ? (
          <label className="ledger-feed__search">
            <span>Search records</span>
            <input
              type="search"
              value={linkageQuery}
              onChange={(event) => setLinkageQuery(event.target.value)}
              placeholder="Proposal, gap, activity, or node id"
            />
          </label>
        ) : null}
        <div>
          <span>{productMode ? "Attention" : "Weight"}</span>
          {WEIGHT_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              className={facets.weights.includes(value) ? "is-active" : ""}
              onClick={() =>
                setFacets((current) => ({
                  ...current,
                  weights: toggleFacet(current.weights, value),
                }))
              }
            >
              {productMode ? weightLabel(value) : value}
            </button>
          ))}
        </div>
        {!live ? (
          <div>
            <span>Actor</span>
            {ACTOR_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                className={facets.actorKinds.includes(value) ? "is-active" : ""}
                onClick={() =>
                  setFacets((current) => ({
                    ...current,
                    actorKinds: toggleFacet(current.actorKinds, value),
                  }))
                }
              >
                {value}
              </button>
            ))}
          </div>
        ) : null}
        {live ? (
          <div>
            <span>Kind</span>
            {LIVE_KIND_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                className={liveKinds.includes(value) ? "is-active" : ""}
                onClick={() =>
                  setLiveKinds((current) => toggleFacet(current, value))
                }
              >
                {kindLabel(value)}
              </button>
            ))}
          </div>
        ) : (
          <div>
            <span>Family</span>
            {FAMILY_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                className={facets.families.includes(value) ? "is-active" : ""}
                onClick={() =>
                  setFacets((current) => ({
                    ...current,
                    families: toggleFacet(current.families, value),
                  }))
                }
              >
                {value.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        )}
        {!live ? (
          <div>
            <span>Authority</span>
            {AUTHORITY_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                className={facets.authorities.includes(value) ? "is-active" : ""}
                onClick={() =>
                  setFacets((current) => ({
                    ...current,
                    authorities: toggleFacet(current.authorities, value),
                  }))
                }
              >
                {authorityLabel(value)}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <p className="ledger-feed__status">
        {productMode ? (
          <>
            {rows.length} activit{rows.length === 1 ? "y" : "ies"}
            {liveRows === null ? " · Reading…" : ""}
            {liveError ? ` · ${liveError}` : ""}
          </>
        ) : (
          <>
            {live
              ? liveError
                ? `live · ${liveError}`
                : liveRows === null
                  ? "live · reading"
                  : "live"
              : "tape"}
            {" · "}
            {PRESETS[preset].note}
            {" · "}
            {rows.length} activities
            {" · "}
            sort {PRESETS[preset].sort.replace("_", " ")}
            {injects.length ? ` · ${injects.length} lab inject(s)` : ""}
          </>
        )}
      </p>

      <section className="ledger-feed__list" aria-live="polite">
        {live && liveError && liveRows === null ? (
          <div className="ledger-feed__state is-empty" role="alert">
            <strong>The event log is unavailable.</strong>
            <p>{liveError}</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="ledger-feed__state is-empty">
            <strong>
              {live
                ? activities.length
                  ? "No activities in this view."
                  : "No recorded activity."
                : "The graph is quiet."}
            </strong>
            <p>
              {live
                ? activities.length
                  ? "Choose another tab or clear the linkage filter."
                  : "New activities will appear here as they are recorded."
                : clockMs < 14_000
                  ? "Ambient heartbeat only — switch to Watch live, or wait for the escalation."
                  : "Agent and operator activity will appear here."}
            </p>
          </div>
        ) : (
          rows.map((activity, index) => (
            <ActivityRow
              key={activity.activity_id}
              activity={activity}
              open={!productMode && openId === activity.activity_id}
              selected={openId === activity.activity_id}
              productMode={productMode}
              arrivalIndex={index}
              nowMs={live ? Date.now() : simNow}
              onOperatorAction={onOperatorAction}
              live={live}
              proposal={
                activity.ids.proposal_id
                  ? proposalsById.get(activity.ids.proposal_id)
                  : undefined
              }
              health={liveHealth}
              busy={actionBusy === activity.activity_id}
              actionError={actionErrors[activity.activity_id]}
              onLiveAction={onLiveAction}
              onToggle={() =>
                setOpenId((current) =>
                  current === activity.activity_id
                    ? null
                    : activity.activity_id,
                )
              }
            />
          ))
        )}
      </section>
      </section>

      {productMode && selectedActivity ? (
        <aside
          className="ledger-feed__inspector"
          aria-label="Selected activity"
        >
          <header className="ledger-feed__inspector-header">
            <div>
              <p>
                {kindLabel(selectedActivity.kind)} · {stateLabel(selectedActivity)}
              </p>
              <h2>{selectedActivity.summary}</h2>
            </div>
            <span>{authorityLabel(selectedActivity.authority_type)}</span>
          </header>
          <dl className="ledger-feed__inspector-facts">
            <div>
              <dt>Recorded by</dt>
              <dd>{selectedActivity.actor.label}</dd>
            </div>
            <div>
              <dt>Activity ID</dt>
              <dd>{selectedActivity.activity_id}</dd>
            </div>
            <div>
              <dt>Graph version</dt>
              <dd>
                {formatRevision(selectedActivity.graph_revision_before)} →{" "}
                {formatRevision(selectedActivity.graph_revision_after)}
              </dd>
            </div>
          </dl>
          <ActivityRow
            key={`detail-${selectedActivity.activity_id}`}
            activity={selectedActivity}
            open
            selected
            detailOnly
            productMode
            nowMs={live ? Date.now() : simNow}
            onOperatorAction={onOperatorAction}
            live={live}
            proposal={
              selectedActivity.ids.proposal_id
                ? proposalsById.get(selectedActivity.ids.proposal_id)
                : undefined
            }
            health={liveHealth}
            busy={actionBusy === selectedActivity.activity_id}
            actionError={actionErrors[selectedActivity.activity_id]}
            onLiveAction={onLiveAction}
            onToggle={() => {}}
          />
        </aside>
      ) : productMode ? (
        <aside
          className="ledger-feed__inspector is-empty"
          aria-label="Activity inspector"
        >
          <strong>No activity selected.</strong>
          <p>
            Recorded activity will remain inspectable here without replacing
            the queue.
          </p>
        </aside>
      ) : null}
      </div>
    </main>
  );
}
