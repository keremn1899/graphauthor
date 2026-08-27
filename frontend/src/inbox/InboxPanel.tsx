import { useMemo, useState } from "react";
import { useGraphController } from "../app/GraphController";
import type { EscalationHandoff, EscalationStatus } from "./types";
import { AuthorSheet } from "./AuthorSheet";
import "./InboxPanel.css";

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function InboxPanel() {
  const { escalations, setEscalations, applyWrite, requestFlyTo } =
    useGraphController();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [authoringId, setAuthoringId] = useState<string | null>(null);

  const open = useMemo(
    () => escalations.filter((e) => e.status === "open"),
    [escalations],
  );
  const closed = useMemo(
    () => escalations.filter((e) => e.status !== "open"),
    [escalations],
  );

  const authoring = escalations.find((e) => e.id === authoringId) ?? null;

  const setStatus = (id: string, status: EscalationStatus) => {
    setEscalations((list) =>
      list.map((e) => (e.id === id ? { ...e, status } : e)),
    );
  };

  return (
    <aside className="inbox-panel" aria-label="Escalation inbox">
      <header className="inbox-panel__header">
        <p className="inbox-panel__eyebrow">Surface 2</p>
        <h1 className="inbox-panel__title">Escalation inbox</h1>
        <p className="inbox-panel__lede">
          Predicate-centric decisions. Not graph objects — time-ordered
          handoffs.
        </p>
      </header>

      {authoring ? (
        <AuthorSheet
          escalation={authoring}
          onCancel={() => setAuthoringId(null)}
          onCommit={(label) => {
            applyWrite({
              label,
              attachToId: authoring.graphRegionId,
              edgeKind: "CONTAINS",
              fromEscalationId: authoring.id,
            });
            setAuthoringId(null);
          }}
        />
      ) : (
        <>
          <section className="inbox-panel__section">
            <h2 className="inbox-panel__section-title">
              Open · {open.length}
            </h2>
            <ul className="inbox-list">
              {open.map((e) => (
                <InboxItem
                  key={e.id}
                  item={e}
                  active={activeId === e.id}
                  onSelect={() =>
                    setActiveId((id) => (id === e.id ? null : e.id))
                  }
                  onShow={() =>
                    e.graphRegionId && requestFlyTo(e.graphRegionId)
                  }
                  onAuthor={() => setAuthoringId(e.id)}
                  onDispose={(status) => setStatus(e.id, status)}
                />
              ))}
              {open.length === 0 && (
                <li className="inbox-list__empty">No open escalations.</li>
              )}
            </ul>
          </section>

          {closed.length > 0 && (
            <section className="inbox-panel__section">
              <h2 className="inbox-panel__section-title">
                Closed · {closed.length}
              </h2>
              <ul className="inbox-list inbox-list--closed">
                {closed.map((e) => (
                  <li key={e.id} className="inbox-item inbox-item--closed">
                    <span className="inbox-item__status">{e.status}</span>
                    <span className="inbox-item__pred">
                      {e.ungovernedPredicate}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </aside>
  );
}

function InboxItem({
  item,
  active,
  onSelect,
  onShow,
  onAuthor,
  onDispose,
}: {
  item: EscalationHandoff;
  active: boolean;
  onSelect: () => void;
  onShow: () => void;
  onAuthor: () => void;
  onDispose: (s: EscalationStatus) => void;
}) {
  return (
    <li className={active ? "inbox-item is-active" : "inbox-item"}>
      <button type="button" className="inbox-item__main" onClick={onSelect}>
        <span className="inbox-item__when">
          {formatWhen(item.createdAt)}
        </span>
        <span className="inbox-item__pred">{item.ungovernedPredicate}</span>
        <span className="inbox-item__q">{item.question}</span>
        <span className="inbox-item__prov">
          {item.provenance.actor} · {item.provenance.source}
        </span>
      </button>

      {active && (
        <div className="inbox-item__actions">
          <button type="button" onClick={onAuthor}>
            Author rule
          </button>
          {item.graphRegionId && (
            <button type="button" onClick={onShow}>
              Show on graph
            </button>
          )}
          <button type="button" onClick={() => onDispose("deferred")}>
            Defer
          </button>
          <button type="button" onClick={() => onDispose("intentional")}>
            Intentionally ungoverned
          </button>
          <button type="button" onClick={() => onDispose("dismissed")}>
            Dismiss
          </button>
        </div>
      )}
    </li>
  );
}
