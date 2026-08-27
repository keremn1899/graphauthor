import { type ReactNode, useEffect, useRef, useState } from "react";
import { useOutgoing, usePresence } from "./usePresence";
import "./presence.css";

/**
 * Inner-column change while a panel is already out. Do not slide the dock
 * again — absorb the previous subject, emit the new one.
 *
 * The outgoing copy is parked absolutely so the live child's scroll is not
 * fighting a stacked twin.
 */
export function Swap({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) {
  const [shownId, setShownId] = useState(id);
  const live = useRef(children);
  if (id === shownId) live.current = children;

  const [leaving, setLeaving] = useState<{
    id: string;
    children: ReactNode;
  } | null>(null);

  if (id !== shownId) {
    setLeaving({ id: shownId, children: live.current });
    setShownId(id);
    live.current = children;
  }

  const outgoing = useOutgoing(leaving?.id ?? null);
  useEffect(() => {
    if (leaving && !outgoing.mounted) setLeaving(null);
  }, [leaving, outgoing.mounted]);

  return (
    <div className="motion-swap">
      {leaving && outgoing.mounted ? (
        <div
          className={`motion-swap__was motion-layer motion-layer--fade${outgoing.shown ? " is-in" : ""}`}
          aria-hidden
        >
          {leaving.children}
        </div>
      ) : null}
      <Entering key={shownId}>{live.current}</Entering>
    </div>
  );
}

function Entering({ children }: { children: ReactNode }) {
  const presence = usePresence(true);
  return (
    <div
      className={`motion-swap__is motion-layer motion-layer--fade${presence.shown ? " is-in" : ""}`}
    >
      {children}
    </div>
  );
}
