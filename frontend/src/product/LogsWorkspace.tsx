import {
  type CSSProperties,
  useEffect,
  useMemo,
  useState,
} from "react";
import { isLiveMode } from "../api/graph";
import {
  fetchVersionDiff,
  fetchWriteCheckpoints,
  useWriteCheckpoints,
  type VersionDiff,
  type WriteCheckpoint,
} from "../api/ledger";
import {
  actionErrorMessage,
  useResource,
  visibleError,
} from "../api/resource";
import { eventTypeLabel } from "../shared/protocolVocabulary";
import { Swap } from "../styles/Swap";
import { NoticeCard, NoticeSurface, useBoundNotice } from "./Notice";
import { Instrument, InstrumentGroup } from "./ProductShell";
import { readStoredPanelSize, ResizableDivider, storePanelSize } from "./ResizableDivider";
import "./ReviewWorkspace.css";

const LOG_POLL_MS = 5_000;
const QUEUE_WIDTH_KEY = "graphauthor.logQueueWidth";

function eventParam() {
  const query = window.location.hash.split("?", 2)[1] ?? "";
  return new URLSearchParams(query).get("activity") ?? "";
}

function rememberEvent(eventId: string) {
  const [route, query = ""] = window.location.hash.split("?", 2);
  const params = new URLSearchParams(query);
  if (eventId) params.set("activity", eventId);
  else params.delete("activity");
  const suffix = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${route}${suffix ? `?${suffix}` : ""}`,
  );
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

function graphHref(row: WriteCheckpoint) {
  const params = liveHashParams({
    seam: "diff",
    return: "log",
    activity: row.id,
  });
  if (row.subjects.length) params.set("focus", row.subjects.join(","));
  if (row.proposalId) params.set("proposal", row.proposalId);
  if (row.from) params.set("from", row.from);
  if (row.to) params.set("to", row.to);
  return `#/graph?${params}`;
}

function formatWhen(ts: number) {
  if (!ts) return "";
  const millis = ts < 1e12 ? ts * 1000 : ts;
  return new Date(millis).toLocaleString();
}

function shortVersion(version: string) {
  if (!version) return "—";
  return version.length > 18 ? `${version.slice(0, 10)}…${version.slice(-4)}` : version;
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
      <span>
        {total} recorded change{total === 1 ? "" : "s"}
      </span>
      <dl>
        <div>
          <dt>Nodes added</dt>
          <dd>{diff.nodes_added.length}</dd>
        </div>
        <div>
          <dt>Nodes changed</dt>
          <dd>{diff.nodes_changed.length}</dd>
        </div>
        <div>
          <dt>Nodes removed</dt>
          <dd>{diff.nodes_removed.length}</dd>
        </div>
        <div>
          <dt>Edges added</dt>
          <dd>{diff.edges_added.length}</dd>
        </div>
        <div>
          <dt>Edges removed</dt>
          <dd>{diff.edges_removed.length}</dd>
        </div>
      </dl>
    </div>
  );
}

function ChangeNames({
  heading,
  items,
}: {
  heading: string;
  items: { id: string; label?: string }[];
}) {
  if (!items.length) return null;
  return (
    <div className="review-change-list">
      <h4>{heading}</h4>
      {items.map((item) => (
        <div key={item.id}>
          <strong>{item.label || item.id}</strong>
          <code>{item.id}</code>
        </div>
      ))}
    </div>
  );
}

export function LogsWorkspace() {
  const [selectedId, setSelectedId] = useState(eventParam);
  const [queueWidth, setQueueWidth] = useState(() =>
    readStoredPanelSize(QUEUE_WIDTH_KEY, 420),
  );
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [diffError, setDiffError] = useState("");
  const live = useMemo(() => isLiveMode(), []);

  useEffect(() => {
    storePanelSize(QUEUE_WIDTH_KEY, queueWidth);
  }, [queueWidth]);

  // Error/loading state for the write log; the rows themselves come from the
  // shared event-log store (one fetcher, `since` cursor), not a second poll.
  const log = useResource((signal) => fetchWriteCheckpoints(signal), {
    enabled: live,
    pollMs: LOG_POLL_MS,
    watch: "operator",
    fallbackError: "Could not read the write log.",
  });
  const rows = useWriteCheckpoints(live ? LOG_POLL_MS : 0);
  const newestFirst = useMemo(() => [...rows].reverse(), [rows]);
  const selected =
    newestFirst.find((row) => row.id === selectedId) ?? newestFirst[0] ?? null;
  const chronoIndex = selected
    ? rows.findIndex((row) => row.id === selected.id)
    : -1;
  const older = chronoIndex > 0 ? rows[chronoIndex - 1] : null;
  const newer =
    chronoIndex >= 0 && chronoIndex < rows.length - 1
      ? rows[chronoIndex + 1]
      : null;

  useEffect(() => {
    if (selected) rememberEvent(selected.id);
  }, [selected?.id]);

  const error = visibleError(log);
  useBoundNotice(
    "log",
    error
      ? {
          slot: "block",
          kind: "unavailable",
          title: "Logs could not be read",
          body: error,
        }
      : null,
  );

  useEffect(() => {
    setDiff(null);
    setDiffError("");
    if (!selected?.from || !selected.to || selected.from === selected.to) return;
    const controller = new AbortController();
    void fetchVersionDiff(selected.from, selected.to, controller.signal)
      .then(setDiff)
      .catch((nextError) => {
        if (controller.signal.aborted) return;
        const message = actionErrorMessage(nextError);
        if (message) setDiffError(message);
      });
    return () => controller.abort();
  }, [selected?.id, selected?.from, selected?.to]);

  return (
    <main className="review-workspace">
      <NoticeSurface />
      <Instrument>
        <InstrumentGroup
          label="Show write"
          present={Boolean(selected?.from && selected.to)}
        >
          {selected?.from && selected.to ? (
            <a href={graphHref(selected)}>Show on graph</a>
          ) : null}
        </InstrumentGroup>
        <InstrumentGroup label="Selected write" present={Boolean(selected)}>
          {selected ? (
            <>
              {rows.length > 1 ? (
                <button
                  type="button"
                  onClick={() => older && setSelectedId(older.id)}
                  disabled={!older}
                  aria-label="Older write"
                >
                  ←
                </button>
              ) : null}
              <span
                className="review-reading"
                title={`${selected.from} → ${selected.to}`}
              >
                {shortVersion(selected.from)} → {shortVersion(selected.to)}
              </span>
              {rows.length > 1 ? (
                <button
                  type="button"
                  onClick={() => newer && setSelectedId(newer.id)}
                  disabled={!newer}
                  aria-label="Newer write"
                >
                  →
                </button>
              ) : null}
            </>
          ) : null}
        </InstrumentGroup>
      </Instrument>

      <div
        className="review-body"
        style={{ "--review-queue-width": `${queueWidth}px` } as CSSProperties}
      >
        <section id="review-queue" className="review-queue" aria-label="Graph writes">
          {!live ? (
            <div className="review-empty">
              <strong>No operator host</strong>
              <span>
                Logs read a running operator plane. Open the product with{" "}
                <code>?api=live</code>.
              </span>
            </div>
          ) : null}
          {live && log.loading ? (
            <p className="review-empty">Loading writes…</p>
          ) : null}
          {live && !log.loading && !rows.length ? (
            <div className="review-empty">
              <strong>No writes yet</strong>
              <span>Committed and reverted graphs will appear here, newest first.</span>
            </div>
          ) : null}
          {newestFirst.map((row) => (
            <button
              key={row.id}
              type="button"
              className={`review-row${selected?.id === row.id ? " is-selected" : ""}`}
              onClick={() => setSelectedId(row.id)}
            >
              <span
                className={`review-row__mark review-row__mark--${
                  row.kind === "reverted" ? "reverted" : "committed"
                }`}
              />
              <span className="review-row__main">
                <span className="review-row__summary">
                  {eventTypeLabel(
                    row.kind === "reverted" ? "graph.reverted" : "graph.committed",
                  )}
                </span>
                <span className="review-row__meta">
                  {formatWhen(row.ts)}
                  {row.proposalId ? ` · ${row.proposalId}` : ""}
                </span>
              </span>
              <span className="review-row__waiting">
                {shortVersion(row.from)} → {shortVersion(row.to)}
              </span>
            </button>
          ))}
        </section>

        <ResizableDivider
          className="review-divider"
          label="Resize write list"
          controls="review-queue"
          size={queueWidth}
          defaultSize={420}
          minSize={280}
          maxSize={640}
          minTrailingSize={420}
          onResize={setQueueWidth}
          cssVariable="--review-queue-width"
        />

        <aside className="review-inspector" aria-label="Write details">
          {/* Swap on the selected write so a new subject emits in like any
              other change of subject, rather than cutting in place. */}
          <Swap id={selected?.id ?? "none"}>
            {!selected ? (
              <div className="review-empty">
                <strong>{rows.length ? "Select a write" : "No writes yet"}</strong>
                <span>
                  {rows.length
                    ? "The recorded change for that version pair is shown here."
                    : "A selected write shows what was added, changed, and removed."}
                </span>
              </div>
            ) : (
              <>
                <header className="review-inspector__header">
                  <div>
                    <h2>
                      {eventTypeLabel(
                        selected.kind === "reverted"
                          ? "graph.reverted"
                          : "graph.committed",
                      )}
                    </h2>
                    <p className="review-inspector__who">{formatWhen(selected.ts)}</p>
                  </div>
                  <span
                    className={
                      selected.kind === "committed"
                        ? "review-status review-status--committed"
                        : "review-status"
                    }
                  >
                    {selected.kind}
                  </span>
                </header>

                <section className="review-inspector__section" aria-labelledby="diff-heading">
                  <h3 id="diff-heading">What changed</h3>
                  {selected.from && selected.to && selected.from !== selected.to ? (
                    <>
                      {diff ? <DiffSummary diff={diff} /> : null}
                      {diff ? (
                        <>
                          <ChangeNames heading="Added" items={diff.nodes_added} />
                          <ChangeNames
                            heading="Changed"
                            items={diff.nodes_changed.map((node) => ({ id: node.id }))}
                          />
                          <ChangeNames heading="Removed" items={diff.nodes_removed} />
                        </>
                      ) : null}
                      {diffError ? <NoticeCard kind="fault" body={diffError} /> : null}
                      {!diff && !diffError ? <p>Loading change summary…</p> : null}
                      <p className="review-versions">
                        <code>{selected.from}</code>
                        <span>→</span>
                        <code>{selected.to}</code>
                      </p>
                    </>
                  ) : (
                    <p>This write did not record a version pair.</p>
                  )}
                  {selected.reason ? <p className="review-handoff__note">{selected.reason}</p> : null}
                </section>
              </>
            )}
          </Swap>
        </aside>
      </div>
    </main>
  );
}
