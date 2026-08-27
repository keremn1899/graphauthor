import * as radixColors from "@radix-ui/colors";
import {
  type CSSProperties,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  LEDGER_FEED_FIXTURES,
  kindLabel,
  relativeTime,
  stateLabel,
  type ActivityVM,
} from "./lab/ledgerFeedModel";
import {
  canFocusActivity,
  graphMapHrefForActivity,
} from "./lab/platformCoreScenario";
import {
  createMotionPlans,
  motionCssVariables,
  motionPoseKeyframes,
  MOTION_DURATION_MS,
  type MotionPlan,
} from "../styles/motion";
import { useMotion } from "../styles/useMotion";
import "./LedgerDnaWorkbenchPage.css";

const RADIX_SCALES = [
  "gray",
  "mauve",
  "slate",
  "sage",
  "olive",
  "sand",
  "grayDark",
  "mauveDark",
  "slateDark",
  "sageDark",
  "oliveDark",
  "sandDark",
] as const;

type RadixScale = (typeof RADIX_SCALES)[number];
type RadixToken = { scale: RadixScale; step: number };
type ThemeMode = "light" | "dark";
type QueueView = "all" | "needs" | "incidents" | "settled" | "ambient";
type LocalPhase = "absorbing" | "settled";

type LedgerPalette = {
  canvas: RadixToken;
  surface: RadixToken;
  ink: RadixToken;
  muted: RadixToken;
  rule: RadixToken;
  held: RadixToken;
};

type LedgerDnaParams = {
  light: LedgerPalette;
  dark: LedgerPalette;
  rowGap: number;
  rowPadding: number;
  summarySize: number;
  metaSize: number;
  inspectorWidth: number;
  attentionRail: number;
  ambientOpacity: number;
  selectedInset: number;
  motionEmit: number;
  motionAbsorb: number;
  motionSettle: number;
  gravityTravel: number;
};

const token = (scale: RadixScale, step: number): RadixToken => ({
  scale,
  step,
});

const DEFAULTS: LedgerDnaParams = {
  light: {
    canvas: token("gray", 1),
    surface: token("gray", 2),
    ink: token("gray", 12),
    muted: token("gray", 9),
    rule: token("gray", 6),
    held: token("gray", 12),
  },
  dark: {
    canvas: token("mauveDark", 1),
    surface: token("mauveDark", 2),
    ink: token("mauveDark", 12),
    muted: token("mauveDark", 9),
    rule: token("mauveDark", 6),
    held: token("mauveDark", 12),
  },
  rowGap: 7,
  rowPadding: 14,
  summarySize: 14,
  metaSize: 11,
  inspectorWidth: 390,
  attentionRail: 3,
  ambientOpacity: 0.56,
  selectedInset: 2,
  motionEmit: MOTION_DURATION_MS.emit,
  motionAbsorb: MOTION_DURATION_MS.absorb,
  motionSettle: MOTION_DURATION_MS.settle,
  gravityTravel: 9,
};

const SPECIMEN_IDS = [
  "act_await_encode",
  "act_ownership_revert",
  "act_escalate_outcome",
  "act_dep_rule",
  "act_batch_82fa",
  "act_orient_read",
  "act_snapshot_idle",
] as const;

const SPECIMEN_NOW = Date.parse("2026-07-18T08:05:00Z");

const QUEUES: Array<{ id: QueueView; label: string }> = [
  { id: "all", label: "All" },
  { id: "needs", label: "Needs me" },
  { id: "incidents", label: "Incidents" },
  { id: "settled", label: "Settled" },
  { id: "ambient", label: "Ambient" },
];

function radixValue(value: RadixToken): string {
  const scale = radixColors[value.scale] as Record<string, string>;
  const key = `${value.scale.replace("Dark", "")}${value.step}`;
  return scale[key] ?? "#888888";
}

function resolvedPalette(
  params: LedgerDnaParams,
  mode: ThemeMode,
): Record<keyof LedgerPalette, string> {
  return Object.fromEntries(
    Object.entries(params[mode]).map(([key, value]) => [
      key,
      radixValue(value),
    ]),
  ) as Record<keyof LedgerPalette, string>;
}

function formatRevision(value: string | number | undefined) {
  if (value == null) return "—";
  return typeof value === "number" ? `V${value}` : value;
}

function actorGlyph(activity: ActivityVM) {
  if (activity.actor.kind === "human") return "H";
  if (activity.actor.kind === "agent") return "A";
  if (activity.actor.kind === "gate") return "G";
  return "S";
}

function activityWithPhase(
  activity: ActivityVM,
  phase: LocalPhase | undefined,
): ActivityVM {
  if (phase !== "settled") return activity;
  return {
    ...activity,
    state: "SETTLED",
    resolution:
      activity.demand?.kind === "incident" ? "acked" : "committed",
    weight: "notable",
    needs_me: false,
    demand: undefined,
    hot: false,
  };
}

function inQueue(activity: ActivityVM, queue: QueueView) {
  if (queue === "needs") return activity.needs_me;
  if (queue === "incidents") {
    return activity.state === "OPEN" && activity.demand?.kind === "incident";
  }
  if (queue === "settled") return activity.state === "SETTLED";
  if (queue === "ambient") return activity.weight === "ambient";
  return true;
}

function weightOrder(activity: ActivityVM) {
  if (activity.needs_me) return 0;
  if (activity.demand?.kind === "incident") return 1;
  if (activity.weight === "demanding") return 2;
  if (activity.weight === "notable") return 3;
  return 4;
}

function humanize(value: string) {
  return value.replaceAll("_", " ");
}

function RangeControl({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="ldna__range">
      <span>
        {label}
        <output>
          {Number.isInteger(value) ? value : value.toFixed(2)}
          {unit}
        </output>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function RadixControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: RadixToken;
  onChange: (value: RadixToken) => void;
}) {
  return (
    <label className="ldna__radix">
      <span>{label}</span>
      <i style={{ background: radixValue(value) }} />
      <select
        value={value.scale}
        onChange={(event) =>
          onChange({ ...value, scale: event.target.value as RadixScale })
        }
      >
        {RADIX_SCALES.map((scale) => (
          <option key={scale} value={scale}>
            {scale}
          </option>
        ))}
      </select>
      <select
        value={value.step}
        onChange={(event) =>
          onChange({ ...value, step: Number(event.target.value) })
        }
        aria-label={`${label} Radix step`}
      >
        {Array.from({ length: 12 }, (_, index) => index + 1).map((step) => (
          <option key={step} value={step}>
            {step}
          </option>
        ))}
      </select>
    </label>
  );
}

function ActivityRow({
  activity,
  selected,
  phase,
  arrivalIndex,
  arrivalRun,
  arrivalMotion,
  gravityTravel,
  onSelect,
}: {
  activity: ActivityVM;
  selected: boolean;
  phase?: LocalPhase;
  arrivalIndex: number;
  arrivalRun: number;
  arrivalMotion: MotionPlan;
  gravityTravel: number;
  onSelect: () => void;
}) {
  const arrival = useMotion<HTMLElement>();

  useEffect(() => {
    arrival.play(
      motionPoseKeyframes(
        { y: -gravityTravel, scale: 0.994, opacity: 0 },
        { y: 0, scale: 1, opacity: 1 },
      ),
      arrivalMotion,
      { delay: arrivalIndex * 26, fill: "backwards" },
    );
  }, [
    arrival,
    arrivalIndex,
    arrivalMotion,
    arrivalRun,
    gravityTravel,
  ]);

  return (
    <article
      ref={arrival.ref}
      className={[
        "ldna__activity",
        `is-${activity.weight}`,
        activity.needs_me ? "needs-me" : "",
        activity.demand?.kind === "incident" ? "is-incident" : "",
        activity.state === "SETTLED" ? "is-settled" : "",
        selected ? "is-selected" : "",
        phase === "absorbing" ? "is-absorbing" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button type="button" onClick={onSelect} aria-pressed={selected}>
        <span className="ldna__attention" aria-hidden />
        <span
          className={`ldna__actor is-${activity.actor.kind}`}
          title={`${activity.actor.kind}: ${activity.actor.label}`}
        >
          {actorGlyph(activity)}
        </span>
        <span className="ldna__activity-copy">
          <strong>{activity.summary}</strong>
          <small>
            {activity.actor.label} · {relativeTime(activity.last_updated, SPECIMEN_NOW)}
          </small>
        </span>
        <span className="ldna__activity-meta">
          <span>{kindLabel(activity.kind)}</span>
          <em>{stateLabel(activity)}</em>
          <code>{activity.events.length}</code>
        </span>
      </button>
    </article>
  );
}

function ArcInspector({
  activity,
  phase,
  onResolve,
}: {
  activity: ActivityVM;
  phase?: LocalPhase;
  onResolve: () => void;
}) {
  const subjects = activity.subject_node_ids ?? activity.node_ids;
  const identifiers = Object.entries(activity.ids).filter(([, value]) =>
    Boolean(value),
  );

  return (
    <aside className="ldna__inspector" aria-label="Selected activity">
      <div className="ldna__inspector-scroll" key={activity.activity_id}>
        <header className="ldna__inspector-header">
          <div>
            <p>{kindLabel(activity.kind)}</p>
            <h2>{stateLabel(activity)}</h2>
          </div>
          <span className={`ldna__authority is-${activity.authority_type}`}>
            {humanize(activity.authority_type)}
          </span>
        </header>

        <p className="ldna__inspector-summary">{activity.summary}</p>

        <dl className="ldna__facts">
          <div>
            <dt>actor</dt>
            <dd>{activity.actor.label}</dd>
          </div>
          <div>
            <dt>authority</dt>
            <dd>{humanize(activity.authority_type)}</dd>
          </div>
          <div>
            <dt>arc</dt>
            <dd>{activity.activity_id}</dd>
          </div>
          <div>
            <dt>graph</dt>
            <dd>
              {formatRevision(activity.graph_revision_before)} →{" "}
              {formatRevision(activity.graph_revision_after)}
            </dd>
          </div>
        </dl>

        {subjects.length ? (
          <section className="ldna__inspector-section">
            <h3>Focus set</h3>
            <div className="ldna__subjects">
              {subjects.map((subject) => (
                <code key={subject}>{subject}</code>
              ))}
            </div>
            {canFocusActivity(activity) ? (
              <a
                className="ldna__graph-link"
                href={graphMapHrefForActivity(activity)}
              >
                Focus in graph
              </a>
            ) : null}
          </section>
        ) : null}

        {identifiers.length ? (
          <section className="ldna__inspector-section">
            <h3>Linkage</h3>
            <dl className="ldna__linkage">
              {identifiers.map(([key, value]) => (
                <div key={key}>
                  <dt>{humanize(key)}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {activity.needs_me ? (
          <section className="ldna__decision">
            <div>
              <p>Disposition required</p>
              <strong>Authority is waiting on a human decision.</strong>
            </div>
            <label>
              <span>Primary source</span>
              <input placeholder="Policy, ADR, handbook §…" />
            </label>
            <div className="ldna__decision-actions">
              <button
                type="button"
                className="is-primary"
                onClick={onResolve}
                disabled={phase === "absorbing"}
              >
                {phase === "absorbing" ? "Resolving…" : "Confirm specimen"}
              </button>
              <button type="button">Reject</button>
              <button type="button">Requeue</button>
            </div>
            <small>Workbench actions are local visual specimens.</small>
          </section>
        ) : activity.demand?.kind === "incident" ? (
          <section className="ldna__decision">
            <div>
              <p>Incident remains open</p>
              <strong>Its weight persists until the record says otherwise.</strong>
            </div>
            <button type="button" onClick={onResolve}>
              Acknowledge specimen
            </button>
            <small>Workbench action only.</small>
          </section>
        ) : null}

        <section className="ldna__inspector-section">
          <h3>Arc · {activity.events.length} recorded events</h3>
          <ol className="ldna__timeline">
            {activity.events.map((event, index) => (
              <li
                key={event.event_id}
                className={[
                  event.inferred ? "is-inferred" : "",
                  event.degraded ? "is-degraded" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <span>{index + 1}</span>
                <div>
                  <code>{event.type}</code>
                  <p>{event.summary}</p>
                  <small>
                    {event.actor_kind}
                    {event.outcome ? ` · ${event.outcome}` : ""}
                    {event.inferred ? " · inferred" : ""}
                    {event.degraded ? " · degraded" : ""}
                  </small>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {activity.evidence?.length ? (
          <section className="ldna__inspector-section">
            <h3>Evidence</h3>
            <ul className="ldna__plain-list">
              {activity.evidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {activity.gate_findings?.length ? (
          <section className="ldna__inspector-section">
            <h3>Gate findings</h3>
            <ul className="ldna__plain-list">
              {activity.gate_findings.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </aside>
  );
}

export function LedgerDnaWorkbenchPage() {
  const [params, setParams] = useState(DEFAULTS);
  const [themeMode, setThemeMode] = useState<ThemeMode>("light");
  const [queue, setQueue] = useState<QueueView>("all");
  const [selectedId, setSelectedId] = useState<string>("act_await_encode");
  const [arrivalRun, setArrivalRun] = useState(0);
  const [phases, setPhases] = useState<Record<string, LocalPhase>>({});
  const [copied, setCopied] = useState(false);
  const resolutionTimer = useRef(0);

  useEffect(
    () => () => {
      if (resolutionTimer.current) window.clearTimeout(resolutionTimer.current);
    },
    [],
  );

  const activities = useMemo(() => {
    const byId = new Map(
      LEDGER_FEED_FIXTURES.map((activity) => [activity.activity_id, activity]),
    );
    return SPECIMEN_IDS.map((id) => byId.get(id))
      .filter((activity): activity is ActivityVM => Boolean(activity))
      .map((activity) => activityWithPhase(activity, phases[activity.activity_id]))
      .sort((a, b) => {
        const weight = weightOrder(a) - weightOrder(b);
        if (weight) return weight;
        return Date.parse(b.last_updated) - Date.parse(a.last_updated);
      });
  }, [phases]);

  const rows = useMemo(
    () => activities.filter((activity) => inQueue(activity, queue)),
    [activities, queue],
  );

  useEffect(() => {
    if (rows.some((activity) => activity.activity_id === selectedId)) return;
    if (rows[0]) setSelectedId(rows[0].activity_id);
  }, [rows, selectedId]);

  const selected =
    activities.find((activity) => activity.activity_id === selectedId) ??
    rows[0] ??
    activities[0];
  const palette = resolvedPalette(params, themeMode);
  const motion = useMemo(
    () =>
      createMotionPlans(
        { travel: params.gravityTravel },
        {
          emit: params.motionEmit,
          absorb: params.motionAbsorb,
          settle: params.motionSettle,
        },
      ),
    [
      params.gravityTravel,
      params.motionAbsorb,
      params.motionEmit,
      params.motionSettle,
    ],
  );

  const patch = <K extends keyof LedgerDnaParams>(
    key: K,
    value: LedgerDnaParams[K],
  ) => setParams((current) => ({ ...current, [key]: value }));

  const patchPalette = (
    mode: ThemeMode,
    key: keyof LedgerPalette,
    value: RadixToken,
  ) =>
    setParams((current) => ({
      ...current,
      [mode]: { ...current[mode], [key]: value },
    }));

  const resolveSelected = () => {
    if (!selected || phases[selected.activity_id] === "absorbing") return;
    setPhases((current) => ({
      ...current,
      [selected.activity_id]: "absorbing",
    }));
    if (resolutionTimer.current) window.clearTimeout(resolutionTimer.current);
    resolutionTimer.current = window.setTimeout(() => {
      setPhases((current) => ({
        ...current,
        [selected.activity_id]: "settled",
      }));
    }, params.motionAbsorb);
  };

  const reset = () => {
    if (resolutionTimer.current) window.clearTimeout(resolutionTimer.current);
    setParams(DEFAULTS);
    setThemeMode("light");
    setQueue("all");
    setSelectedId("act_await_encode");
    setPhases({});
    setArrivalRun((value) => value + 1);
  };

  const copyParameters = async () => {
    try {
      await navigator.clipboard.writeText(
        JSON.stringify({ ledgerDna: params }, null, 2),
      );
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  const queueCount = (id: QueueView) =>
    activities.filter((activity) => inQueue(activity, id)).length;

  return (
    <main
      className={`ldna${themeMode === "dark" ? " is-dark" : ""}`}
      style={
        {
          "--ldna-canvas": palette.canvas,
          "--ldna-surface": palette.surface,
          "--ldna-ink": palette.ink,
          "--ldna-muted": palette.muted,
          "--ldna-rule": palette.rule,
          "--ldna-held": palette.held,
          "--ldna-row-gap": `${params.rowGap}px`,
          "--ldna-row-padding": `${params.rowPadding}px`,
          "--ldna-summary-size": `${params.summarySize}px`,
          "--ldna-meta-size": `${params.metaSize}px`,
          "--ldna-inspector-width": `${params.inspectorWidth}px`,
          "--ldna-attention-rail": `${params.attentionRail}px`,
          "--ldna-ambient-opacity": params.ambientOpacity,
          "--ldna-selected-inset": `${params.selectedInset}px`,
          "--ldna-motion-emit": `${params.motionEmit}ms`,
          "--ldna-motion-absorb": `${params.motionAbsorb}ms`,
          "--ldna-motion-settle": `${params.motionSettle}ms`,
          "--ldna-gravity-travel": `${params.gravityTravel}px`,
          "--ldna-emit-curve": motion.emit.easing.css,
          "--ldna-absorb-curve": motion.absorb.easing.css,
          "--ldna-settle-curve": motion.settle.easing.css,
          ...motionCssVariables(motion),
        } as CSSProperties
      }
    >
      <header className="ldna__header">
        <div>
          <p className="ldna__nav">
            <a href="#/explorations">Explorations</a> / Ledger DNA
          </p>
          <h1>Ledger DNA workbench</h1>
          <p>
            Tune the operator plane as recorded arcs: persistent attention,
            attributable authority, stable inspection, and restrained physical
            motion.
          </p>
        </div>
        <div className="ldna__header-actions">
          <span>ActivityVM · Jost · Radix</span>
          <button type="button" onClick={copyParameters}>
            {copied ? "Copied" : "Copy parameters"}
          </button>
          <button type="button" onClick={reset}>
            Reset
          </button>
        </div>
      </header>

      <div className="ldna__workbench">
        <aside className="ldna__controls">
          <section>
            <h2>Theme</h2>
            <div className="ldna__switch">
              <button
                type="button"
                className={themeMode === "light" ? "is-active" : ""}
                onClick={() => setThemeMode("light")}
              >
                Light
              </button>
              <button
                type="button"
                className={themeMode === "dark" ? "is-active" : ""}
                onClick={() => setThemeMode("dark")}
              >
                Dark
              </button>
            </div>
            {(Object.keys(params[themeMode]) as Array<keyof LedgerPalette>).map(
              (key) => (
                <RadixControl
                  key={`${themeMode}-${key}`}
                  label={humanize(key)}
                  value={params[themeMode][key]}
                  onChange={(value) => patchPalette(themeMode, key, value)}
                />
              ),
            )}
          </section>

          <section>
            <h2>Queue matter</h2>
            <p>
              Density changes the ledger’s working rhythm without changing what
              any state means.
            </p>
            <RangeControl
              label="Row gap"
              value={params.rowGap}
              min={0}
              max={20}
              unit="px"
              onChange={(value) => patch("rowGap", value)}
            />
            <RangeControl
              label="Row padding"
              value={params.rowPadding}
              min={8}
              max={26}
              unit="px"
              onChange={(value) => patch("rowPadding", value)}
            />
            <RangeControl
              label="Summary"
              value={params.summarySize}
              min={11}
              max={19}
              unit="px"
              onChange={(value) => patch("summarySize", value)}
            />
            <RangeControl
              label="Metadata"
              value={params.metaSize}
              min={8}
              max={14}
              unit="px"
              onChange={(value) => patch("metaSize", value)}
            />
            <RangeControl
              label="Inspector"
              value={params.inspectorWidth}
              min={310}
              max={560}
              step={10}
              unit="px"
              onChange={(value) => patch("inspectorWidth", value)}
            />
          </section>

          <section>
            <h2>Attention</h2>
            <p>
              Demanding work persists through weight. Ambient work recedes but
              is never made absent.
            </p>
            <RangeControl
              label="Held rail"
              value={params.attentionRail}
              min={1}
              max={8}
              step={0.5}
              unit="px"
              onChange={(value) => patch("attentionRail", value)}
            />
            <RangeControl
              label="Ambient presence"
              value={params.ambientOpacity}
              min={0.2}
              max={1}
              step={0.05}
              onChange={(value) => patch("ambientOpacity", value)}
            />
            <RangeControl
              label="Selection inset"
              value={params.selectedInset}
              min={1}
              max={6}
              unit="px"
              onChange={(value) => patch("selectedInset", value)}
            />
          </section>

          <section>
            <h2>Motion spine</h2>
            <p>
              Arrival emits, resolution absorbs, and selection settles laterally
              into a stable inspector.
            </p>
            <RangeControl
              label="Arrival"
              value={params.motionEmit}
              min={100}
              max={700}
              step={10}
              unit="ms"
              onChange={(value) => patch("motionEmit", value)}
            />
            <RangeControl
              label="Resolution"
              value={params.motionAbsorb}
              min={80}
              max={600}
              step={10}
              unit="ms"
              onChange={(value) => patch("motionAbsorb", value)}
            />
            <RangeControl
              label="Selection settle"
              value={params.motionSettle}
              min={120}
              max={800}
              step={10}
              unit="ms"
              onChange={(value) => patch("motionSettle", value)}
            />
            <RangeControl
              label="Gravity travel"
              value={params.gravityTravel}
              min={2}
              max={24}
              unit="px"
              onChange={(value) => patch("gravityTravel", value)}
            />
          </section>
        </aside>

        <section className="ldna__specimen">
          <div className="ldna__specimen-bar">
            <div>
              <strong>Operator specimen</strong>
              <span>recorded arcs · no invented urgency</span>
            </div>
            <button
              type="button"
              onClick={() => setArrivalRun((value) => value + 1)}
            >
              Replay arrival
            </button>
          </div>

          <div className="ldna__surface">
            <section className="ldna__queue">
              <header className="ldna__queue-header">
                <div>
                  <p>Review</p>
                  <h2>Activity</h2>
                </div>
                <span>
                  <i /> local record
                </span>
              </header>

              <nav className="ldna__queue-nav" aria-label="Ledger views">
                {QUEUES.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={queue === item.id ? "is-active" : ""}
                    onClick={() => setQueue(item.id)}
                  >
                    <span>{item.label}</span>
                    <code>{queueCount(item.id)}</code>
                  </button>
                ))}
              </nav>

              <p className="ldna__queue-status">
                {rows.length} arc{rows.length === 1 ? "" : "s"} · attention
                order
              </p>

              <div className="ldna__activities" key={arrivalRun}>
                {rows.length ? (
                  rows.map((activity, index) => (
                    <ActivityRow
                      key={activity.activity_id}
                      activity={activity}
                      selected={selected?.activity_id === activity.activity_id}
                      phase={phases[activity.activity_id]}
                      arrivalIndex={index}
                      arrivalRun={arrivalRun}
                      arrivalMotion={motion.emit}
                      gravityTravel={params.gravityTravel}
                      onSelect={() => setSelectedId(activity.activity_id)}
                    />
                  ))
                ) : (
                  <div className="ldna__empty">
                    <strong>No recorded arcs in this view.</strong>
                    <span>Absence stays explicit.</span>
                  </div>
                )}
              </div>
            </section>

            {selected ? (
              <ArcInspector
                activity={selected}
                phase={phases[selected.activity_id]}
                onResolve={resolveSelected}
              />
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
