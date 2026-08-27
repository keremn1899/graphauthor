import { useEffect, useState } from "react";

/** Prefer OS preference; allow explicit override from controls. */
export function useReducedMotion(override?: boolean | null): boolean {
  const [prefers, setPrefers] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setPrefers(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  if (override === true) return true;
  if (override === false) return false;
  return prefers;
}
