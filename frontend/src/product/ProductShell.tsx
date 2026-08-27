import {
  createContext,
  type CSSProperties,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { createMotionPlans, motionCssVariables } from "../styles/motion";
import { usePresence } from "../styles/usePresence";
import "../styles/presence.css";
import {
  chromeCssVariables,
  focusCssVariables,
  GRAPH_DNA_PROVISIONAL_CHROME,
  GRAPH_DNA_STATUS,
  radixValue,
  statusCssVariables,
  type ThemeMode,
} from "../styles/graphDna";
import {
  chromeForTheme,
  DNA_PARAM_DEFAULTS,
} from "../explorations/dnaParamsStore";
import { readApiConfig } from "../api/config";
import { fetchOperatorHealth } from "../api/ledger";
import { useResource } from "../api/resource";
import { NoticeProvider, useNotice } from "./Notice";
import { SettingsPanel } from "./SettingsPanel";
import { useGraphDnaRuntime } from "./graphDnaRuntime";
import {
  monoFamily,
  onGraphPrefsChange,
  readGraphPrefs,
} from "./graphPrefs";
import {
  chromeClass,
  OverlayChromeProvider,
  useOverlayChrome,
} from "./overlayChrome";
import "./ProductShell.css";

export type ProductSurface = "graph" | "log" | "construct";

const NAV: { id: ProductSurface; label: string; href: string }[] = [
  { id: "graph", label: "Graph", href: "#/graph?api=live" },
  { id: "log", label: "Logs", href: "#/log?api=live" },
];

/**
 * How often the shell asks whether the host is still answering.
 *
 * Slower than a surface's own polling on purpose: this is ambient, and a write
 * made anywhere in the product invalidates `operator` and refreshes it at once,
 * so the interval only has to catch a host that went away from outside.
 */
const DEMAND_POLL_MS = 15_000;

function useOperatorSignal(): {
  hostUnreachable: boolean;
  hostMessage: string;
} {
  // The Lab renders this shell in fixture mode, where there is no operator to
  // ask. Guarded rather than allowed to fail quietly, so a lab page does not
  // fire a live request per mount against a host that may not be there.
  const live = useMemo(() => readApiConfig().mode === "live", []);
  const health = useResource((signal) => fetchOperatorHealth(signal), {
    enabled: live,
    pollMs: DEMAND_POLL_MS,
    pollWhileHidden: true,
    watch: "operator",
  });
  return {
    hostUnreachable: health.hostUnreachable,
    hostMessage: health.hostUnreachable ? health.error : "",
  };
}

function useDocumentTitle(active: ProductSurface) {
  useEffect(() => {
    const where =
      NAV.find((item) => item.id === active)?.label ??
      (active === "construct" ? "Construct" : "Graph");
    document.title = where;
  }, [active]);
}

const ProductThemeContext = createContext<{
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
}>({
  theme: "light",
  setTheme: () => {},
});

export function useProductTheme() {
  return useContext(ProductThemeContext).theme;
}

/** Flip or set the product appearance. Writes `graphauthor.productTheme`. */
export function useSetProductTheme() {
  return useContext(ProductThemeContext).setTheme;
}

/**
 * Whether the surface is showing a graph nobody has published.
 *
 * Set by the surface, applied by the shell, for the reason the focus palette
 * is applied here: chrome tokens are written as an **inline style** on the
 * shell element, and an inline style beats any stylesheet. A
 * `.is-provisional` CSS rule looked correct, applied to the right element, and
 * changed nothing.
 *
 * It is the surface that knows: publication is a property of the open graph,
 * not of the page, and the graph on screen after you publish it is the same
 * graph. A shell that keyed on the route would have kept the whole product
 * dimmed for as long as you stayed there.
 */
const ProvisionalContext = createContext<{
  provisional: boolean;
  setProvisional: (value: boolean) => void;
}>({ provisional: false, setProvisional: () => {} });

export function useProvisionalSurface() {
  return useContext(ProvisionalContext);
}

/**
 * Where a surface's own controls go.
 *
 * The shell owns *where* the instrument band is; the surface owns *what is in
 * it*. Passing the contents down as a prop would mean lifting every control's
 * state — the node finder's query, the lens selection, the queue's filter — out
 * of the page and into the shell, which is a large amount of plumbing to make
 * one bar render in one place. A portal keeps the state exactly where it
 * already lives and only moves the pixels.
 *
 * `null` until the shell has mounted its slot, so `Instrument` renders nothing
 * on the first frame rather than guessing at a container.
 */
const InstrumentSlotContext = createContext<HTMLElement | null>(null);

export function useInstrumentSlot() {
  return useContext(InstrumentSlotContext);
}

/**
 * A cell in the identity bar, filled by the open surface.
 *
 * Publish / Return lives here so it sits on the same baseline as Graph, Logs
 * and Settings rather than floating over the map.
 */
const ShellActionSlotContext = createContext<HTMLElement | null>(null);
const ActiveSurfaceContext = createContext<ProductSurface>("graph");
const OwningSurfaceContext = createContext<ProductSurface | null>(null);

export function useActiveSurface() {
  return useContext(ActiveSurfaceContext);
}

/**
 * Mark a kept-alive scene as belonging to one product surface. Instruments
 * and shell actions only portal while that surface is the one on screen, so a
 * Graph that stays mounted under Logs cannot keep Find in the band.
 */
export function SurfaceLayer({
  surface,
  children,
}: {
  surface: ProductSurface;
  children: ReactNode;
}) {
  return (
    <OwningSurfaceContext.Provider value={surface}>
      {children}
    </OwningSurfaceContext.Provider>
  );
}

function useSurfacePortals() {
  const owning = useContext(OwningSurfaceContext);
  const active = useContext(ActiveSurfaceContext);
  return owning == null || owning === active;
}

export function ShellAction({ children }: { children: ReactNode }) {
  const slot = useContext(ShellActionSlotContext);
  const open = useSurfacePortals();
  if (!slot || !open) return null;
  return createPortal(children, slot);
}

/**
 * The surface's own controls, rendered into the shell's instrument band.
 *
 * Every surface gets exactly one of these, and everything in it is a verb that
 * acts on *this* surface. Anything that is about the product rather than the
 * surface belongs in identity, at the top — see `chrome-constraints.md` §3, the
 * two-chromes test.
 */
export function Instrument({ children }: { children: ReactNode }) {
  const slot = useContext(InstrumentSlotContext);
  const open = useSurfacePortals();
  if (!slot || !open) return null;
  return createPortal(
    <div className={chromeClass("instrument")}>{children}</div>,
    slot,
  );
}

/** A cluster of cells inside the instrument — the identity bar's geometry. */
export function InstrumentGroup({
  label,
  present,
  children,
}: {
  label: string;
  /** When set, the cluster emits in and absorbs out instead of mounting as a cut. */
  present?: boolean;
  children: ReactNode;
}) {
  if (present === undefined) {
    return (
      <div className="instrument__group" role="group" aria-label={label}>
        {children}
      </div>
    );
  }
  return (
    <PresentInstrumentCluster
      className="instrument__group"
      label={label}
      open={present}
    >
      {children}
    </PresentInstrumentCluster>
  );
}

/**
 * Facts about the surface — lettering only, no bordered strip.
 *
 * Verbs live in `InstrumentGroup`. Readings that share that box look like
 * controls (same rule, same cell padding, same hover language). Keep them
 * here so information and interaction stay two different objects.
 */
export function InstrumentReadings({
  label,
  present,
  children,
}: {
  label: string;
  present?: boolean;
  children: ReactNode;
}) {
  if (present === undefined) {
    return (
      <div className="instrument__readings" role="status" aria-label={label}>
        {children}
      </div>
    );
  }
  return (
    <PresentInstrumentCluster
      className="instrument__readings"
      label={label}
      open={present}
      role="status"
    >
      {children}
    </PresentInstrumentCluster>
  );
}

function PresentInstrumentCluster({
  className,
  label,
  open,
  role = "group",
  children,
}: {
  className: string;
  label: string;
  open: boolean;
  role?: "group" | "status";
  children: ReactNode;
}) {
  const presence = usePresence(open);
  if (!presence.mounted) return null;
  return (
    <div
      className={`${className} motion-layer motion-layer--fade${presence.shown ? " is-in" : ""}`}
      role={role}
      aria-label={label}
    >
      {children}
    </div>
  );
}

function RestoreChrome({
  hidden,
  onRestore,
}: {
  hidden: boolean;
  onRestore: () => void;
}) {
  const presence = usePresence(hidden);
  if (!presence.mounted) return null;
  return (
    <button
      type="button"
      className={`product-shell__restore motion-layer motion-layer--fade${presence.shown ? " is-in" : ""}`}
      onClick={onRestore}
      aria-label="Show the controls"
      title="Show the controls · ."
    >
      ⋯
    </button>
  );
}

function initialTheme(): ThemeMode {
  return localStorage.getItem("graphauthor.productTheme") === "dark"
    ? "dark"
    : "light";
}

export function ProductShell(props: {
  active: ProductSurface;
  chromeInsetLeft?: string;
  children: ReactNode;
}) {
  const [provisional, setProvisional] = useState(false);
  const provisionalValue = useMemo(
    () => ({ provisional, setProvisional }),
    [provisional],
  );
  return (
    <OverlayChromeProvider>
      <NoticeProvider>
        <ProvisionalContext.Provider value={provisionalValue}>
          <ProductShellBody {...props} provisional={provisional} />
        </ProvisionalContext.Provider>
      </NoticeProvider>
    </OverlayChromeProvider>
  );
}

function HostNotice({
  unreachable,
  message,
  onOpenSettings,
}: {
  unreachable: boolean;
  message: string;
  onOpenSettings: () => void;
}) {
  const { raise, clear } = useNotice();
  useEffect(() => {
    if (!unreachable) {
      clear("host");
      return;
    }
    raise({
      id: "host",
      slot: "block",
      kind: "host",
      title: "The host is not answering",
      body: message || "Cannot reach the host. Is it running?",
      action: { label: "Open Settings", onClick: onOpenSettings },
    });
    return () => clear("host");
  }, [clear, message, onOpenSettings, raise, unreachable]);
  return null;
}

function ProductShellBody({
  active,
  chromeInsetLeft = "",
  provisional = false,
  children,
}: {
  active: ProductSurface;
  /** The open graph is unpublished — quieten the whole surface. */
  provisional?: boolean;
  /**
   * A CSS length the floating chrome must stay clear of on the left, for
   * surfaces that put something of their own against that edge — the DNA
   * workbench docks a parameter rail there. Without it the nav floats over the
   * rail's own heading and takes the pointer events meant for it.
   */
  chromeInsetLeft?: string;
  children: ReactNode;
}) {
  const [instrumentSlot, setInstrumentSlot] = useState<HTMLElement | null>(null);
  const [actionSlot, setActionSlot] = useState<HTMLElement | null>(null);
  const [theme, setTheme] = useState<ThemeMode>(initialTheme);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const openSettings = useCallback(() => setSettingsOpen(true), []);
  const motion = useMemo(() => createMotionPlans(), []);
  const dnaRuntime = useGraphDnaRuntime();
  const [graphPrefs, setGraphPrefs] = useState(() => readGraphPrefs());
  useEffect(() => onGraphPrefsChange(setGraphPrefs), []);
  const { hostUnreachable, hostMessage } = useOperatorSignal();
  useDocumentTitle(active);
  const { hidden: chromeHidden, setHidden: setChromeHidden, focused } =
    useOverlayChrome();

  // Chrome tokens are applied on every render, not only under the workbench.
  // They used to be hex in the stylesheet with the workbench overriding them,
  // which meant two sources for one value — and they had already drifted apart
  // (see `GRAPH_DNA_CHROME`). One source, read by the product, tuned by the
  // workbench: a knob that does not move the shipping look is worse than no
  // knob, because it reports a change that did not happen.
  const shellStyle = useMemo(() => {
    const chrome = provisional
      ? GRAPH_DNA_PROVISIONAL_CHROME[theme]
      : chromeForTheme(dnaRuntime?.params ?? DNA_PARAM_DEFAULTS, theme);
    const focusPalette = dnaRuntime?.params.focus ?? DNA_PARAM_DEFAULTS.focus;
    const focusVars = focusCssVariables(focusPalette);
    const style: Record<string, string> = {
      ...(motionCssVariables(motion) as Record<string, string>),
      ...chromeCssVariables(chrome),
      // The focus palette reaches the DOM too, so the Ask spotlight fogs the
      // map in the same ink the canvas uses when it enters focus.
      ...focusVars,
      // Status is theme-varying like everything else here. Not a workbench
      // knob: what the three colours *mean* is fixed, and the workbench tunes
      // how the product looks, not what it is allowed to say.
      ...statusCssVariables(GRAPH_DNA_STATUS[theme]),
    };

    /**
     * In focus, the chrome tokens *become* the focus palette.
     *
     * This has to happen here rather than as a `.product-shell.is-focus` rule,
     * and the reason is the same one that bit `--chrome-opacity`: these tokens
     * are written as an inline style on this element, and an inline style beats
     * any stylesheet. A CSS rule looked correct, applied to the right element,
     * and changed nothing.
     *
     * One palette, not a second theme. Focus means "one subject is lit, the
     * rest of the graph is context" — the same claim whether the operator keeps
     * the product light or dark — so it deliberately has no light variant. The
     * theme decides what ambient looks like; focus overrides it wholesale.
     */
    if (focused) {
      style["--canvas"] = focusVars["--focus-field"];
      style["--panel"] = focusVars["--focus-field"];
      style["--ink"] = focusVars["--focus-ink"];
      style["--ink-muted"] = focusVars["--focus-ink-muted"];
      style["--rule"] = focusVars["--focus-rule"];
      style["--matter-surface"] = focusVars["--focus-field"];
      style["--matter-canvas"] = focusVars["--focus-field"];
    } else {
      // Matter tokens used to be set only under the DNA workbench. Outside it
      // they stayed at the `@property` initial `#f0f0f0`, so dark mode flipped
      // chrome and left the map field light. Always author them from the theme.
      const matter = (dnaRuntime?.params ?? DNA_PARAM_DEFAULTS)[theme];
      style["--matter-surface"] = radixValue(matter.surface);
      style["--matter-canvas"] = radixValue(matter.canvas);
    }
    if (chromeInsetLeft) style["--shell-inset-left"] = chromeInsetLeft;
    if (dnaRuntime) {
      style["--ov-preferred-width"] = `${dnaRuntime.params.overlayWidth}px`;
      style["--node-reader-width"] = `${dnaRuntime.params.readerWidth}px`;
      style["--chrome-opacity"] = String(dnaRuntime.params.chromeOpacity);
    }
    style["--font-mono"] = monoFamily(graphPrefs.mono);
    return style as CSSProperties;
  }, [chromeInsetLeft, dnaRuntime, focused, graphPrefs.mono, motion, theme]);

  /* The shell no longer reads the graph catalogue.

     It kept a `listGraphs` resource, an `announced` override and two effects
     alive for one purpose: printing the open graph's name in the header. With
     that cell gone the whole chain is dead, and a network read per shell mount
     that nothing renders is worse than no read. The `graphauthor:workspace` event is
     still dispatched by the pages that switch workspaces — the library rail
     listens for its own reasons — it simply has no listener here any more. */

  useEffect(() => {
    localStorage.setItem("graphauthor.productTheme", theme);
  }, [theme]);

  const [motionReady, setMotionReady] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setMotionReady(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <ProductThemeContext.Provider value={{ theme, setTheme }}>
    <ActiveSurfaceContext.Provider value={active}>
    <div
      className={`product-shell${theme === "dark" ? " is-dark" : ""}${
        chromeHidden ? " is-chrome-hidden" : ""
      }${focused ? " is-focus" : ""}${motionReady ? " is-motion-ready" : ""}`}
      style={shellStyle}
    >
      {/* Identity: who this is, where you are, and how to leave.
 
          One geometry on every surface. It used to fork on `bleed` — a floating
          strip on Graph, a full-width band on Review and Construct — with
          identical contents in both, which is chrome announcing a change that
          did not happen (`chrome-constraints.md` §2.4).
 
          Nothing surface-specific lives here any more. `Hide` was the last
          holdout: it is a verb about the map, so it went to the map's own
          instrument, and the `bleed ? ... : null` around it went with it.
 
          Low weight on purpose: it is the least important thing on screen. */}
      <header className={chromeClass("product-shell__top")}>
        <div className="product-shell__bar">
          <nav className="product-shell__nav" aria-label="Product">
            {NAV.map((item) => (
              <a
                key={item.id}
                href={item.href}
                aria-current={active === item.id ? "page" : undefined}
              >
                {item.label}
              </a>
            ))}
          </nav>
          <div className="product-shell__utils">
            {/* The open graph's name and a `LOCAL` chip used to sit here.
                Neither is identity: the graph is a fact about *this surface*,
                and the library drawer already names it whenever it is open —
                over the map it was a permanent caption on a picture that has
                one. `LOCAL` reported a condition nobody acts on. Both were
                cells the operator read past on every screen. */}
            <button
              type="button"
              className="product-shell__theme"
              onClick={() =>
                setTheme((value) => (value === "light" ? "dark" : "light"))
              }
              aria-label={`Use ${theme === "light" ? "dark" : "light"} appearance`}
            >
              {theme === "light" ? "Dark" : "Light"}
            </button>
            <button
              type="button"
              className="product-shell__theme"
              aria-haspopup="dialog"
              aria-expanded={settingsOpen}
              onClick={() => setSettingsOpen(true)}
            >
              Settings
            </button>
            <div className="product-shell__action" ref={setActionSlot} />
          </div>
        </div>
      </header>
      {/* The way back.

          Hiding the chrome sets `visibility: hidden` on every cluster, which
          includes the control that did the hiding — so without this, the only
          exits are two keystrokes nobody can see a prompt for, and on a touch
          screen there is no keyboard at all. Deliberately *not* `.chrome`: it
          is the one thing that must survive the state it belongs to. One small
          mark in a corner no panel claims, at the same ink chrome rests at. */}
      <RestoreChrome
        hidden={chromeHidden}
        onRestore={() => setChromeHidden(false)}
      />
      <ShellActionSlotContext.Provider value={actionSlot}>
      <InstrumentSlotContext.Provider value={instrumentSlot}>
        <div className="product-shell__body">{children}</div>
      </InstrumentSlotContext.Provider>
      </ShellActionSlotContext.Provider>
      {/* The instrument band. Empty until a surface portals into it, and
          `:empty` hides it, so a surface with no verbs costs no band. */}
      <div
        className="product-shell__instrument"
        ref={setInstrumentSlot}
        aria-label="Surface controls"
      />
      <HostNotice
        unreachable={hostUnreachable}
        message={hostMessage}
        onOpenSettings={openSettings}
      />
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
    </ActiveSurfaceContext.Provider>
    </ProductThemeContext.Provider>
  );
}
