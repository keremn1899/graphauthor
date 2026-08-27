import { useEffect, useRef, useState } from "react";
import { createMotionPlans } from "./motion";

/**
 * Leave time for anything that must stay mounted through absorb.
 *
 * Read from the spine, not copied. A panel that unmounts on the close frame
 * has no transition to run, which is why OverlayPanel's reader used to snap
 * while the library beside it slid.
 */
const SPINE = createMotionPlans();

export function presenceLeaveMs() {
  return SPINE.absorb.durationMs;
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Keep a node in the tree for the absorb, and park it one frame on enter
 * so a CSS transition has a previous pose.
 *
 * `shown` is the class toggle (`is-in` / `is-open`). `mounted` is whether
 * to render at all. Drawers that keep a handle pass `stayMounted`.
 */
export function usePresence(
  open: boolean,
  options: { stayMounted?: boolean } = {},
) {
  const stayMounted = options.stayMounted === true;
  const [mounted, setMounted] = useState(() => open || stayMounted);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      if (prefersReducedMotion()) {
        setShown(true);
        return;
      }
      let inner = 0;
      const outer = requestAnimationFrame(() => {
        inner = requestAnimationFrame(() => setShown(true));
      });
      return () => {
        cancelAnimationFrame(outer);
        cancelAnimationFrame(inner);
      };
    }

    setShown(false);
    if (stayMounted) return;
    if (prefersReducedMotion()) {
      setMounted(false);
      return;
    }
    const timer = window.setTimeout(
      () => setMounted(false),
      SPINE.absorb.durationMs + 16,
    );
    return () => window.clearTimeout(timer);
  }, [open, stayMounted]);

  return { mounted: stayMounted || mounted, shown };
}

/** Hold the last non-null value while `alive` (a presence `mounted`) is true. */
export function useHeld<T>(
  value: T | null | undefined,
  alive: boolean,
): T | null {
  const held = useRef<T | null>(value ?? null);
  if (value != null) held.current = value;
  if (!alive) return null;
  return value ?? held.current;
}

/**
 * Start shown, then absorb. Swap uses this so the previous subject has a
 * leave to run instead of unmounting on the same frame the new one arrives.
 */
export function useOutgoing(token: string | null) {
  const [mounted, setMounted] = useState(() => Boolean(token));
  const [shown, setShown] = useState(true);

  useEffect(() => {
    if (!token) {
      setMounted(false);
      setShown(true);
      return;
    }
    setMounted(true);
    setShown(true);
    if (prefersReducedMotion()) {
      setMounted(false);
      return;
    }
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => setShown(false));
    });
    const timer = window.setTimeout(
      () => setMounted(false),
      SPINE.absorb.durationMs + 16,
    );
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
      window.clearTimeout(timer);
    };
  }, [token]);

  return { mounted, shown };
}
