import { useMemo, useState } from "react";
import {
  ACTIVITIES,
  type Activity,
  type EventTone,
} from "./architectureActivityData";
import "./ArchitectureActivityLabPage.css";

const FILTERS = [
  { id: "all", label: "All activity" },
  { id: "decisions", label: "Decisions" },
  { id: "proposals", label: "Proposals" },
  { id: "graph", label: "Graph writes" },
  { id: "conformance", label: "Conformance" },
  { id: "failures", label: "Failures" },
  { id: "l1", label: "L1 autonomous" },
  { id: "human", label: "Human" },
  { id: "batches", label: "Batches" },
] as const;

function toneLabel(tone: EventTone) {
  if (tone === "success") return "Passed";
  if (tone === "warning") return "Attention";
  if (tone === "danger") return "Failed";
  if (tone === "info") return "Recorded";
  return "System";
}

function matchesFilter(activity: Activity, filter: string) {
  if (filter === "all") return activity.category !== "system";
  if (filter === "l1") return activity.l1;
  if (filter === "human") return activity.human;
  if (filter === "decisions") {
    return activity.events.some((event) => event.type === "proposal.dispositioned");
  }
  if (filter === "proposals") {
    return activity.events.some((event) => event.type.startsWith("proposal."));
  }
  return activity.category === filter;
}

function ActivityDetail({ activity }: { activity: Activity }) {
  return (
    <div className="activity-ledger__detail">
      <div className="activity-ledger__detail-grid">
        <section>
          <p className="activity-ledger__section-label">Rationale</p>
          <p className="activity-ledger__rationale">{activity.rationale}</p>
        </section>
        <section>
          <p className="activity-ledger__section-label">Evidence</p>
          <ul className="activity-ledger__plain-list">
            {activity.evidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      </div>

      {activity.graphDiff ? (
        <section className="activity-ledger__diff">
          <p className="activity-ledger__section-label">Graph diff</p>
          <div className="activity-ledger__diff-grid">
            <div>
              <span className="activity-ledger__diff-key activity-ledger__diff-key--add">
                +
              </span>
              <ul>
                {activity.graphDiff.added.length ? (
                  activity.graphDiff.added.map((item) => <li key={item}>{item}</li>)
                ) : (
                  <li>Nothing added</li>
                )}
              </ul>
            </div>
            <div>
              <span className="activity-ledger__diff-key activity-ledger__diff-key--change">
                ~
              </span>
              <ul>
                {activity.graphDiff.changed.length ? (
                  activity.graphDiff.changed.map((item) => <li key={item}>{item}</li>)
                ) : (
                  <li>Nothing changed</li>
                )}
              </ul>
            </div>
            <div>
              <span className="activity-ledger__diff-key activity-ledger__diff-key--remove">
                −
              </span>
              <ul>
                {activity.graphDiff.removed.length ? (
                  activity.graphDiff.removed.map((item) => <li key={item}>{item}</li>)
                ) : (
                  <li>Nothing removed</li>
                )}
              </ul>
            </div>
          </div>
        </section>
      ) : null}

      {activity.findings?.length ? (
        <section className="activity-ledger__findings">
          <p className="activity-ledger__section-label">Gate findings</p>
          <ul className="activity-ledger__plain-list">
            {activity.findings.map((finding) => (
              <li key={finding}>{finding}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="activity-ledger__events">
        <div className="activity-ledger__events-heading">
          <div>
            <p className="activity-ledger__section-label">Underlying events</p>
            <p>Immutable facts grouped by correlation and causation.</p>
          </div>
          <span>{activity.events.length} events</span>
        </div>
        <ol>
          {activity.events.map((event, index) => {
            const isGraphWrite =
              event.type === "graph.committed" ||
              event.type === "graph.reverted";
            return (
              <li key={event.id}>
                <div className="activity-ledger__event-rail">
                  <span className={`activity-ledger__event-dot is-${event.tone}`} />
                </div>
                <div className="activity-ledger__event-body">
                  <div className="activity-ledger__event-topline">
                    <code>{event.type}</code>
                    <time>{event.time}</time>
                  </div>
                  <p>{event.summary}</p>
                  <div className="activity-ledger__event-meta">
                    <span>{event.actor}</span>
                    <span>{event.id}</span>
                    {index > 0 ? (
                      <span>caused by {activity.events[index - 1].id}</span>
                    ) : null}
                    {isGraphWrite ? <strong>timeline checkpoint</strong> : null}
                  </div>
                  <details className="activity-ledger__raw">
                    <summary>Raw record</summary>
                    <pre>{event.payload}</pre>
                  </details>
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      <footer className="activity-ledger__actions">
        <span>Permitted actions</span>
        <div>
          {activity.actions.map((action, index) => (
            <button
              type="button"
              key={action}
              className={index === 0 ? "is-primary" : ""}
            >
              {action}
            </button>
          ))}
        </div>
      </footer>
    </div>
  );
}

export function ArchitectureActivityLabPage() {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");

  const visibleActivities = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return ACTIVITIES.filter((activity) => {
      if (!matchesFilter(activity, filter)) return false;
      if (!normalizedQuery) return true;
      return [
        activity.title,
        activity.description,
        activity.reference,
        activity.actor,
        activity.authority,
        activity.graph,
        ...activity.events.map((event) => `${event.type} ${event.summary}`),
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    });
  }, [filter, query]);

  const grouped = visibleActivities.reduce<Record<string, Activity[]>>(
    (groups, activity) => {
      (groups[activity.date] ??= []).push(activity);
      return groups;
    },
    {},
  );
  const eventCount = visibleActivities.reduce(
    (total, activity) => total + activity.events.length,
    0,
  );

  return (
    <main className="activity-ledger">
      <header className="activity-ledger__header">
        <div>
          <p className="activity-ledger__eyebrow">Architecture governance</p>
          <h1>Activity</h1>
          <p className="activity-ledger__lede">
            Decisions, certification, graph writes, and conformance—grouped into
            readable work rather than exposed as internal execution noise.
          </p>
          <p className="activity-ledger__nav">
            <a href="#/explorations">← Explorations</a>
            <span aria-hidden> · </span>
            <a href="#/explorations/g6-history-overlay">Graph write timeline</a>
          </p>
        </div>
        <div className="activity-ledger__principle">
          <span>Ledger model</span>
          <strong>Activities explain. Events prove.</strong>
          <p>Traces stay in diagnostics unless a fault changes domain state.</p>
        </div>
      </header>

      <section className="activity-ledger__summary" aria-label="Ledger summary">
        <div>
          <span>Visible activity</span>
          <strong>{visibleActivities.length}</strong>
        </div>
        <div>
          <span>Underlying events</span>
          <strong>{eventCount}</strong>
        </div>
        <div>
          <span>Latest graph</span>
          <strong>V13</strong>
        </div>
        <div>
          <span>Graph writes</span>
          <strong>3</strong>
        </div>
        <p>
          <span className="activity-ledger__live-dot" />
          Append-only chronology · snapshots remain authoritative
        </p>
      </section>

      <section className="activity-ledger__toolbar" aria-label="Activity filters">
        <div className="activity-ledger__filters">
          {FILTERS.map((item) => (
            <button
              type="button"
              key={item.id}
              className={filter === item.id ? "is-active" : ""}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <label className="activity-ledger__search">
          <span>Search</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Work item, event, actor…"
          />
        </label>
      </section>

      <section className="activity-ledger__content">
        <div className="activity-ledger__column-head">
          <span>Chronology</span>
          <span>{visibleActivities.length} activities · newest first</span>
        </div>

        {Object.keys(grouped).length ? (
          Object.entries(grouped).map(([date, activities]) => (
            <section className="activity-ledger__day" key={date}>
              <h2>{date}</h2>
              <div className="activity-ledger__day-list">
                {activities.map((activity) => (
                  <article
                    className={`activity-ledger__activity is-${activity.tone}`}
                    key={activity.id}
                  >
                    <div className="activity-ledger__time">
                      <time>{activity.time}</time>
                      <span />
                    </div>
                    <details>
                      <summary>
                        <div className="activity-ledger__activity-main">
                          <div className="activity-ledger__activity-kicker">
                            <span
                              className={`activity-ledger__outcome is-${activity.tone}`}
                            >
                              {activity.outcome}
                            </span>
                            <span>{activity.category}</span>
                            {activity.badges?.map((badge) => (
                              <span key={badge}>{badge}</span>
                            ))}
                          </div>
                          <h3>{activity.title}</h3>
                          <p>{activity.description}</p>
                          <div className="activity-ledger__activity-meta">
                            <span>{activity.actor}</span>
                            <span>{activity.authority}</span>
                            <span>{activity.graph}</span>
                            {activity.version ? <strong>{activity.version}</strong> : null}
                          </div>
                          <code className="activity-ledger__reference">
                            {activity.reference}
                          </code>
                        </div>
                        <div className="activity-ledger__expand">
                          <span>{activity.events.length}</span>
                          <small>events</small>
                          <i aria-hidden>⌄</i>
                        </div>
                      </summary>
                      <ActivityDetail activity={activity} />
                    </details>
                  </article>
                ))}
              </div>
            </section>
          ))
        ) : (
          <div className="activity-ledger__empty">
            <strong>No matching activity</strong>
            <p>Try another filter or clear the search.</p>
            <button
              type="button"
              onClick={() => {
                setFilter("all");
                setQuery("");
              }}
            >
              Reset filters
            </button>
          </div>
        )}
      </section>

      <footer className="activity-ledger__footer">
        <span>Example projection · synthetic data</span>
        <span>
          Outcome language: {toneLabel("success")} · {toneLabel("warning")} ·{" "}
          {toneLabel("danger")}
        </span>
      </footer>
    </main>
  );
}
