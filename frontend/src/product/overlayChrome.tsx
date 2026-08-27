/**
 * The overlay system: how everything floating over the map behaves.
 *
 * The map is the product. Every floating thing borrows space from it, so each
 * one has to be returnable — and until now each one decided for itself what
 * that meant. The library dismissed on an outside click, the reader on its
 * handle, Ask on its fog, and `Escape` was a hand-written chain inside
 * `GraphWorkspace` that knew all three by name. Adding a fourth overlay meant
 * editing that chain, and forgetting to was silent.
 *
 * Two kinds of floating thing, with two different rules:
 *
 * **Chrome** — the bars, the handles, the banners. Controls you act *with*,
 * which are not what you came to look at. Chrome rests at low presence and
 * comes up when you approach it or focus it, and the hide key takes all of it
 * away at once so the map can be read or captured bare. It is never "dismissed"
 * because it was never in the way of a task; it was in the way of a view.
 *
 * **Layers** — the library, the node reader, the Ask spotlight. Content you are
 * reading. These are dismissed rather than dimmed, `Escape` takes the topmost
 * one, and "topmost" is decided by rank here rather than by an `if` chain
 * somewhere else. A layer that forgets to register simply is not dismissable,
 * which is a visible bug rather than a silent one.
 *
 * Chrome recession is CSS (`overlayChrome.css`), not state: pointer proximity
 * at 60fps through React would re-render the whole surface to change one
 * opacity. Only the hide key, which is a real decision, lives in state.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import "./overlayChrome.css";

/**
 * Which layer `Escape` takes first. Higher goes first, and the numbers are
 * spaced so a new layer can be placed between two without renumbering.
 *
 * The order is "innermost first": a reader opened from a panel closes before
 * the panel that produced it, and the spotlight — which covers everything —
 * closes before anything under it.
 */
export const OVERLAY_RANK = {
  spotlight: 300,
  /** Menus opened from chrome. Above the reader so Escape closes the menu first. */
  menu: 250,
  reader: 200,
  drawer: 100,
  /** Docked notices. Below drawers so Escape closes the library first. */
  notice: 50,
} as const;

export type OverlayRank = number;

type LayerEntry = {
  rank: OverlayRank;
  dismiss: () => void;
};

type ChromeApi = {
  /** Whether the operator has hidden the chrome outright. */
  hidden: boolean;
  setHidden: (hidden: boolean) => void;
  /**
   * Whether the surface below is in its focus reading state.
   *
   * Published up here rather than kept on the page because the shell's own bar
   * *floats over the same field*. When the map inverts, a bar still painting
   * from the page theme is light-theme ink on a dark map — and in light mode
   * that is near-black on near-black. Focus is a property of the screen, so the
   * screen's root is where it has to be stated.
   */
  focused: boolean;
  setFocused: (focused: boolean) => void;
  /** Register an open, dismissable layer. Returns an unregister function. */
  registerLayer: (entry: LayerEntry) => () => void;
};

const noop = () => {};

const ChromeContext = createContext<ChromeApi>({
  hidden: false,
  setHidden: noop,
  focused: false,
  setFocused: noop,
  registerLayer: () => noop,
});

/** True when the event came from somewhere the operator is typing. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/** The key that takes the chrome away and brings it back. */
const HIDE_CHROME_KEY = ".";

export function OverlayChromeProvider({ children }: { children: ReactNode }) {
  const [hidden, setHidden] = useState(false);
  const [focused, setFocused] = useState(false);
  const layersRef = useRef(new Set<LayerEntry>());

  const registerLayer = useCallback((entry: LayerEntry) => {
    layersRef.current.add(entry);
    return () => {
      layersRef.current.delete(entry);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      // A modifier means the key belongs to the platform or to a shortcut we
      // did not define, not to us.
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === "Escape") {
        // Typing is not an exception here: Escape while the composer has focus
        // is exactly how someone closes the spotlight they are typing in.
        const layers = [...layersRef.current];
        if (!layers.length) {
          // Nothing to dismiss, so Escape means the other thing it could mean.
          if (hidden) setHidden(false);
          return;
        }
        const top = layers.reduce((best, entry) =>
          entry.rank > best.rank ? entry : best,
        );
        event.preventDefault();
        top.dismiss();
        return;
      }

      if (event.key === HIDE_CHROME_KEY && !isTypingTarget(event.target)) {
        event.preventDefault();
        setHidden((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hidden]);

  const api = useMemo<ChromeApi>(
    () => ({ hidden, setHidden, focused, setFocused, registerLayer }),
    [focused, hidden, registerLayer],
  );

  return (
    <ChromeContext.Provider value={api}>{children}</ChromeContext.Provider>
  );
}

export function useOverlayChrome(): ChromeApi {
  return useContext(ChromeContext);
}

/**
 * Declare that an overlay is open and how to close it.
 *
 * `dismiss` is read through a ref, so a layer may pass a fresh closure every
 * render without re-registering — and without `Escape` ever calling a stale one
 * that closes something already closed.
 */
export function useDismissableLayer(
  open: boolean,
  rank: OverlayRank,
  dismiss: () => void,
) {
  const { registerLayer } = useOverlayChrome();
  const dismissRef = useRef(dismiss);
  dismissRef.current = dismiss;

  useEffect(() => {
    if (!open) return;
    return registerLayer({ rank, dismiss: () => dismissRef.current() });
  }, [open, rank, registerLayer]);
}

/**
 * The class every chrome cluster carries.
 *
 * A function rather than a bare string so a cluster cannot half-adopt the
 * system by spelling the class itself and missing the modifier.
 */
export function chromeClass(...extra: Array<string | false | undefined>) {
  return ["chrome", ...extra.filter(Boolean)].join(" ");
}
