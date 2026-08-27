/**
 * The operator-facing fault surface.
 *
 * Four things used to share the word "error" and none of them were the same
 * object. Collapsing them into toasts would make that worse: a toast vanishes,
 * and a vanished sentence about a failed publish is indistinguishable from a
 * publish that worked.
 *
 *   **Block** — this surface cannot be used. Host unreachable, map unreadable,
 *   review queue unreadable. One card over the subject, identity and instrument
 *   still reachable (Settings, a different graph). Not dismissible: the
 *   condition is still true.
 *
 *   **Dock** — a verb the operator just issued failed. Activate, confirm,
 *   export. Sits above the instrument until dismissed or the next success.
 *   Escape takes it, after any open drawer.
 *
 *   **Inline** — the form is still open. Publish in the library, browse, run a
 *   traversal, Settings, the node reader. The card is the same object; it just
 *   lives next to the control that produced it.
 *
 *   **Queue** — Review exceptions (`CORRECTION`, `SUPERSESSION`, …). Work
 *   waiting for a person, not a fault. They stay on Review. Honest traversal
 *   outcomes (`EMPTY`, `EXACT_MISS`, fallback) are receipts, not notices.
 *
 * Host-down is not a `FaultKind`: if the process cannot speak it cannot
 * classify. The client authors that sentence (`ApiError` status 0).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, type FaultKind } from "../api/client";
import { OVERLAY_RANK, useDismissableLayer } from "./overlayChrome";
import { useHeld, usePresence } from "../styles/usePresence";
import "../styles/presence.css";
import "./Notice.css";

export type NoticeKind = FaultKind | "host";
export type NoticeSlot = "block" | "dock" | "inline";

export type Notice = {
  id: string;
  slot: NoticeSlot;
  kind: NoticeKind;
  title: string;
  body: string;
  dismissible?: boolean;
  action?: { label: string; onClick: () => void };
};

export function kindOfCause(cause: unknown): NoticeKind {
  if (cause instanceof ApiError) {
    if (cause.hostUnreachable) return "host";
    return cause.kind ?? "fault";
  }
  return "fault";
}

/** Operator sentence plus kind, or null when the host itself is down. */
export function faultOf(
  cause: unknown,
  fallback: string,
): { kind: NoticeKind; body: string } | null {
  if (cause instanceof ApiError && cause.hostUnreachable) return null;
  const body =
    cause instanceof Error && cause.message ? cause.message : fallback;
  return { kind: kindOfCause(cause), body };
}

type NoticeApi = {
  notices: Notice[];
  raise: (notice: Notice) => void;
  clear: (id: string) => void;
};

const NoticeContext = createContext<NoticeApi>({
  notices: [],
  raise: () => {},
  clear: () => {},
});

export function useNotice(): NoticeApi {
  return useContext(NoticeContext);
}

export function NoticeProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([]);
  const raise = useCallback((notice: Notice) => {
    setNotices((current) => {
      const rest = current.filter((item) => item.id !== notice.id);
      return [...rest, notice];
    });
  }, []);
  const clear = useCallback((id: string) => {
    setNotices((current) => current.filter((item) => item.id !== id));
  }, []);
  const api = useMemo(
    () => ({ notices, raise, clear }),
    [clear, notices, raise],
  );
  return (
    <NoticeContext.Provider value={api}>{children}</NoticeContext.Provider>
  );
}

/**
 * Keep one notice in the host for as long as `spec` is set.
 *
 * Identity is `id`; the effect keys off the readable fields so a caller can
 * pass a fresh object each render without raising a loop. `action` is not
 * keyed — put callbacks on a blocking notice from a component that owns them.
 */
export function useBoundNotice(
  id: string,
  spec: Omit<Notice, "id" | "action"> | null,
) {
  const { raise, clear } = useNotice();
  const present = spec != null;
  const slot = spec?.slot;
  const kind = spec?.kind;
  const title = spec?.title;
  const body = spec?.body;
  const dismissible = spec?.dismissible;
  useEffect(() => {
    if (!present || !slot || !kind || title === undefined || !body) {
      clear(id);
      return;
    }
    raise({ id, slot, kind, title, body, dismissible });
    return () => clear(id);
  }, [body, clear, dismissible, id, kind, present, raise, slot, title]);
}

export function NoticeCard({
  kind: _kind,
  title,
  body,
  dismissible = false,
  action,
  onDismiss,
  bodyId,
}: {
  kind: NoticeKind;
  title?: string;
  body: string;
  dismissible?: boolean;
  action?: { label: string; onClick: () => void };
  onDismiss?: () => void;
  bodyId?: string;
}) {
  return (
    <div
      className={`notice-card${title ? "" : " notice-card--inline"}`}
      role="alert"
    >
      {dismissible && onDismiss ? (
        <div className="notice-card__head">
          <button
            type="button"
            className="notice-card__dismiss"
            onClick={onDismiss}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ) : null}
      {title ? <p className="notice-card__title">{title}</p> : null}
      <p className="notice-card__body" id={bodyId}>
        {body}
      </p>
      {action ? (
        <button
          type="button"
          className="notice-card__action"
          onClick={action.onClick}
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Paints block and dock notices into the current surface.
 *
 * Must live *inside* the subject (`.gm__main`, `.review-workspace`), not as a
 * sibling of it. Overlay drawers are siblings of `.gm__main` at z-index 30; a
 * host painted next to `.gm` would cover them, and then a failed map would
 * hide the library that is how you leave it.
 */
export function NoticeSurface() {
  const { notices, clear } = useNotice();
  const blocks = notices.filter((item) => item.slot === "block");
  const liveBlock = blocks.find((item) => item.id === "host") ?? blocks[0] ?? null;
  const liveDocks = notices.filter((item) => item.slot === "dock");
  const blockPresence = usePresence(Boolean(liveBlock));
  const dockPresence = usePresence(liveDocks.length > 0);
  const block = useHeld(liveBlock, blockPresence.mounted);
  const docks = useHeld(liveDocks.length ? liveDocks : null, dockPresence.mounted) ?? [];
  const dismissable = [...docks]
    .reverse()
    .find((item) => item.dismissible);

  useDismissableLayer(Boolean(dismissable), OVERLAY_RANK.notice, () => {
    if (dismissable) clear(dismissable.id);
  });

  if (!blockPresence.mounted && !dockPresence.mounted) return null;

  return (
    <>
      {blockPresence.mounted && block ? (
        <div
          className={`notice-block motion-layer motion-layer--fade${blockPresence.shown ? " is-in" : ""}`}
          role="alertdialog"
          aria-label={block.title}
          aria-describedby={`notice-${block.id}-body`}
        >
          <NoticeCard
            kind={block.kind}
            title={block.title}
            body={block.body}
            action={block.action}
            bodyId={`notice-${block.id}-body`}
          />
        </div>
      ) : null}
      {dockPresence.mounted && docks.length ? (
        <div className="notice-dock" aria-live="assertive">
          <div
            className={`notice-dock__motion motion-layer motion-layer--rise${dockPresence.shown ? " is-in" : ""}`}
          >
            {docks.map((item) => (
              <NoticeCard
                key={item.id}
                kind={item.kind}
                title={item.title}
                body={item.body}
                dismissible={item.dismissible}
                action={item.action}
                onDismiss={
                  item.dismissible ? () => clear(item.id) : undefined
                }
              />
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
