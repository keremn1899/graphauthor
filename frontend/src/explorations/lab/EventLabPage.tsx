/**
 * Temporary fixture: the remaining event types, painted as a filled Logs page.
 * Nothing is emitted. Drop this file (and its route) once the copy is judged.
 */
import { type CSSProperties, useMemo, useState } from "react";
import { eventTypeLabel } from "../../shared/protocolVocabulary";
import {
  Instrument,
  InstrumentGroup,
  ProductShell,
} from "../../product/ProductShell";
import { Swap } from "../../styles/Swap";
import "../../product/ReviewWorkspace.css";
import "./EventLabPage.css";

type Specimen = {
  id: string;
  type: string;
  actor: string;
  ts: number;
  proposalId?: string;
  from?: string;
  to?: string;
  reason?: string;
};

const NOW = Date.parse("2026-08-27T09:40:00Z");

const SPECIMENS: Specimen[] = [
  {
    id: "ev_commit",
    type: "graph.committed",
    actor: "gate:auto-encode",
    ts: NOW,
    proposalId: "prop_14",
    from: "gv_a1b2c3d4e5f6",
    to: "gv_e5f6a7b8c9d0",
  },
  {
    id: "ev_reverted",
    type: "graph.reverted",
    actor: "operator",
    ts: NOW - 3600_000,
    proposalId: "prop_13",
    from: "gv_e5f6a7b8c9d0",
    to: "gv_a1b2c3d4e5f6",
    reason: "restore prior published graph",
  },
];

function formatWhen(ts: number) {
  return new Date(ts).toLocaleString();
}

function shortVersion(version: string) {
  if (!version) return "—";
  return version.length > 18 ? `${version.slice(0, 10)}…${version.slice(-4)}` : version;
}

function markOf(type: string): "committed" | "reverted" {
  if (type === "graph.reverted") return "reverted";
  return "committed";
}

function statusOf(type: string): { label: string; className: string } {
  if (type === "graph.reverted") {
    return { label: "reverted", className: "review-status" };
  }
  return { label: "committed", className: "review-status review-status--committed" };
}

function EventLabBody() {
  const [selectedId, setSelectedId] = useState(SPECIMENS[0]?.id ?? "");
  const selected =
    SPECIMENS.find((row) => row.id === selectedId) ?? SPECIMENS[0] ?? null;
  const index = selected ? SPECIMENS.findIndex((row) => row.id === selected.id) : -1;
  const newer = index > 0 ? SPECIMENS[index - 1] : null;
  const older = index >= 0 && index < SPECIMENS.length - 1 ? SPECIMENS[index + 1] : null;
  const status = selected ? statusOf(selected.type) : null;
  const versions = useMemo(() => {
    if (!selected?.from || !selected.to) return "";
    return `${shortVersion(selected.from)} → ${shortVersion(selected.to)}`;
  }, [selected]);

  return (
    <main className="review-workspace event-lab">
      <Instrument>
        <InstrumentGroup label="Fixture">
          <span>Committed and reverted · nothing emitted</span>
        </InstrumentGroup>
        <InstrumentGroup label="Selected" present={Boolean(selected)}>
          {selected ? (
            <>
              <button
                type="button"
                onClick={() => older && setSelectedId(older.id)}
                disabled={!older}
                aria-label="Older event"
              >
                ←
              </button>
              <span className="review-reading" title={selected.type}>
                {eventTypeLabel(selected.type)}
              </span>
              <button
                type="button"
                onClick={() => newer && setSelectedId(newer.id)}
                disabled={!newer}
                aria-label="Newer event"
              >
                →
              </button>
            </>
          ) : null}
        </InstrumentGroup>
      </Instrument>

      <div
        className="review-body"
        style={{ "--review-queue-width": "420px" } as CSSProperties}
      >
        <section id="review-queue" className="review-queue" aria-label="Event specimens">
          {SPECIMENS.map((row) => (
            <button
              key={row.id}
              type="button"
              className={`review-row${selected?.id === row.id ? " is-selected" : ""}`}
              onClick={() => setSelectedId(row.id)}
            >
              <span className={`review-row__mark review-row__mark--${markOf(row.type)}`} />
              <span className="review-row__main">
                <span className="review-row__summary">{eventTypeLabel(row.type)}</span>
                <span className="review-row__meta">
                  {formatWhen(row.ts)}
                  {row.proposalId ? ` · ${row.proposalId}` : ""}
                </span>
              </span>
              <span className="review-row__waiting">
                {row.from && row.to
                  ? `${shortVersion(row.from)} → ${shortVersion(row.to)}`
                  : formatWhen(row.ts)}
              </span>
            </button>
          ))}
        </section>

        <div className="review-divider" aria-hidden="true" />

        <aside className="review-inspector" aria-label="Event details">
          <Swap id={selected?.id ?? "none"}>
            {!selected ? (
              <div className="review-empty">
                <strong>Select an event</strong>
                <span>Committed and reverted are listed, newest first.</span>
              </div>
            ) : (
              <>
                <header className="review-inspector__header">
                  <div>
                    <h2>{eventTypeLabel(selected.type)}</h2>
                    <p className="review-inspector__who">
                      {selected.actor} · {formatWhen(selected.ts)}
                    </p>
                  </div>
                  {status ? <span className={status.className}>{status.label}</span> : null}
                </header>

                <section className="review-inspector__section">
                  <h3>Record</h3>
                  <ol className="review-events">
                    <li>
                      <span />
                      <div>
                        <strong>{eventTypeLabel(selected.type)}</strong>
                        <p>
                          {selected.actor} · {formatWhen(selected.ts)}
                        </p>
                        <code>{selected.type}</code>
                      </div>
                    </li>
                  </ol>
                  {versions ? (
                    <p className="review-versions">
                      <code>{selected.from}</code>
                      <span>→</span>
                      <code>{selected.to}</code>
                    </p>
                  ) : null}
                  {selected.reason ? (
                    <p className="review-handoff__note">{selected.reason}</p>
                  ) : null}
                </section>
              </>
            )}
          </Swap>
        </aside>
      </div>
    </main>
  );
}

export function EventLabPage() {
  return (
    <ProductShell active="log">
      <EventLabBody />
    </ProductShell>
  );
}
