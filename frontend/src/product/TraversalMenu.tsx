/**
 * Centered traversal palette.
 *
 * Fixed two-column sheet in a spotlight: catalogue on the left, reader on
 * the right. Portals onto `.product-shell` so GRAPH_DNA_CHROME applies.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  runNamedTraversal,
  type GraphMap,
  type MapNode,
  type NamedTraversalResult,
  type TraversalParameterSpec,
  type TraversalSummary,
} from "../api/graph";
import { NoticeCard, faultOf } from "./Notice";
import NodeFinder from "./NodeFinder";
import { OVERLAY_RANK, useDismissableLayer } from "./overlayChrome";
import { usePresence } from "../styles/usePresence";
import { Swap } from "../styles/Swap";
import "../styles/presence.css";
import "./TraversalMenu.css";

function asTag(value: string): string {
  return value.trim().replaceAll("_", " ").toLowerCase();
}

/** Node-id parameters are stored as `from_id`; the operator sees "from". */
function paramRole(name: string, type?: string): string {
  const stem =
    type === "node_id" && name.endsWith("_id") ? name.slice(0, -3) : name;
  return asTag(stem);
}

function kindMatches(node: MapNode | null, kinds?: string[]): boolean {
  if (!node) return false;
  if (!kinds?.length) return true;
  const kind = (node.kind || "").toLowerCase();
  if (!kind) return false;
  return kinds.some((allowed) => kind === allowed.toLowerCase());
}

function nodeParams(
  spec: TraversalSummary,
): Array<[string, TraversalParameterSpec]> {
  return Object.entries(spec.parameters ?? {}).filter(
    ([, parameter]) => parameter.type === "node_id",
  );
}

function otherParams(
  spec: TraversalSummary,
): Array<[string, TraversalParameterSpec]> {
  return Object.entries(spec.parameters ?? {}).filter(
    ([, parameter]) => parameter.type !== "node_id",
  );
}

function initialNodePicks(
  spec: TraversalSummary,
  inspected: MapNode | null,
): Record<string, MapNode> {
  const bound: Record<string, MapNode> = {};
  const params = nodeParams(spec);
  for (const [param, paramSpec] of params) {
    if (inspected && kindMatches(inspected, paramSpec.kinds)) {
      bound[param] = inspected;
      break;
    }
  }
  return bound;
}

function canRun(
  spec: TraversalSummary,
  bound: Record<string, MapNode>,
  extra: Record<string, string>,
): boolean {
  for (const [param, parameter] of Object.entries(spec.parameters ?? {})) {
    if (parameter.required === false) continue;
    if (parameter.type === "node_id") {
      if (!bound[param]) return false;
    } else if (!extra[param]?.trim()) {
      return false;
    }
  }
  return true;
}

function overlayHost(): HTMLElement {
  return document.querySelector(".product-shell") ?? document.body;
}

export function TraversalMenu({
  traversals,
  map,
  inspected,
  graphId,
  graphVersion,
  open,
  onOpenChange,
  onResult,
}: {
  traversals: Record<string, TraversalSummary>;
  map: GraphMap | null;
  inspected: MapNode | null;
  graphId: string;
  graphVersion?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResult: (result: NamedTraversalResult) => void;
}) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLOListElement | null>(null);
  const presence = usePresence(open);

  const [activeIndex, setActiveIndex] = useState(0);
  const [picks, setPicks] = useState<Record<string, MapNode>>({});
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const recipes = useMemo(
    () =>
      Object.entries(traversals).sort(([left], [right]) =>
        left.localeCompare(right),
      ),
    [traversals],
  );

  const safeActiveIndex = Math.min(
    Math.max(0, activeIndex),
    Math.max(0, recipes.length - 1),
  );

  const activeEntry = recipes[safeActiveIndex];
  const activeName = activeEntry ? activeEntry[0] : null;
  const activeSpec = activeEntry ? activeEntry[1] : null;

  useDismissableLayer(open, OVERLAY_RANK.spotlight, () => onOpenChange(false));

  useEffect(() => {
    if (!open) {
      setActiveIndex(0);
      setPicks({});
      setExtra({});
      setError("");
      return;
    }
    const timer = setTimeout(() => {
      const current = listRef.current?.querySelector<HTMLButtonElement>(
        ".traversal-modal__row.is-current",
      );
      (current ?? sheetRef.current)?.focus();
    }, 40);
    return () => clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open || !activeSpec) return;
    setPicks(initialNodePicks(activeSpec, inspected));
    setExtra({});
  }, [open, activeName, activeSpec, inspected]);

  useEffect(() => {
    if (recipes.length === 0 && open) onOpenChange(false);
  }, [open, onOpenChange, recipes.length]);

  const execute = async (
    name: string,
    boundPicks: Record<string, MapNode>,
    extraParams: Record<string, string>,
  ) => {
    const spec = traversals[name];
    if (!spec || running) return;

    const parameters: Record<string, string> = {};
    for (const [param, parameter] of Object.entries(spec.parameters ?? {})) {
      if (parameter.type === "node_id") {
        const node = boundPicks[param];
        if (node) parameters[param] = node.id;
      } else if (extraParams[param]?.trim()) {
        parameters[param] = extraParams[param].trim();
      }
    }

    setRunning(true);
    setError("");

    try {
      const result = await runNamedTraversal(graphId, name, parameters, {
        version: spec.version,
        graphVersion,
      });

      const honest = ["FOUND", "EMPTY", "EXACT_MISS"].includes(result.outcome);
      if (
        result.kind === "INVALID_TRAVERSAL" ||
        result.kind === "TRAVERSAL_FAILED" ||
        result.kind === "STALE_GRAPH" ||
        !honest
      ) {
        setError(
          result.kind === "STALE_GRAPH"
            ? "The graph has changed since this map was drawn. Refresh, then run again."
            : result.errors?.map(String).join("; ") ||
                "The traversal could not run.",
        );
        return;
      }

      onResult(result);
      onOpenChange(false);
    } catch (cause: unknown) {
      const fault = faultOf(cause, "The traversal could not run.");
      setError(fault?.body || "The traversal could not run.");
    } finally {
      setRunning(false);
    }
  };

  const moveTo = (index: number) => {
    if (!recipes.length) return;
    const next = (index + recipes.length) % recipes.length;
    setActiveIndex(next);
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>(
      ".traversal-modal__row",
    );
    const button = buttons?.[next];
    button?.focus();
    button?.scrollIntoView({ block: "nearest" });
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onOpenChange(false);
      return;
    }

    const typing =
      event.target instanceof HTMLInputElement ||
      event.target instanceof HTMLTextAreaElement;
    if (typing) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveTo(safeActiveIndex + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveTo(safeActiveIndex - 1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      moveTo(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      moveTo(recipes.length - 1);
      return;
    }
    if (event.key === "Enter" && activeName && activeSpec) {
      if (!canRun(activeSpec, picks, extra) || running) return;
      event.preventDefault();
      void execute(activeName, picks, extra);
    }
  };

  const isReady = activeSpec ? canRun(activeSpec, picks, extra) : false;
  const titleKinds = activeSpec
    ? [
        ...new Set(
          nodeParams(activeSpec).flatMap(([, parameter]) => parameter.kinds ?? []),
        ),
      ]
    : [];

  if (recipes.length === 0) return null;

  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-pressed={open}
        onClick={() => onOpenChange(!open)}
      >
        Traverse
      </button>

      {presence.mounted
        ? createPortal(
            <div
              className={`traversal-modal__backdrop motion-layer motion-layer--fade${presence.shown ? " is-in" : ""}`}
              onPointerDown={(event) => {
                if (event.target === event.currentTarget) onOpenChange(false);
              }}
            >
              <div
                ref={sheetRef}
                className={`traversal-modal motion-layer motion-layer--rise${presence.shown ? " is-in" : ""}`}
                role="dialog"
                aria-modal="true"
                aria-labelledby="traversal-modal-title"
                tabIndex={-1}
                onKeyDown={onKeyDown}
              >
                <div className="traversal-modal__menu">
                    <ol
                      ref={listRef}
                      className="traversal-modal__list"
                      role="listbox"
                      aria-label="Traversals"
                    >
                      {recipes.map(([name, item], index) => {
                        const isCurrent = index === safeActiveIndex;
                        const requiredKinds = [
                          ...new Set(
                            nodeParams(item).flatMap(
                              ([, parameter]) => parameter.kinds ?? [],
                            ),
                          ),
                        ];

                        return (
                          <li key={name}>
                            <button
                              type="button"
                              className={
                                isCurrent
                                  ? "traversal-modal__row is-current"
                                  : "traversal-modal__row"
                              }
                              role="option"
                              aria-selected={isCurrent}
                              tabIndex={isCurrent ? 0 : -1}
                              onClick={() => setActiveIndex(index)}
                              onKeyDown={(event) => {
                                if (event.key === "ArrowDown") {
                                  event.preventDefault();
                                  moveTo(index + 1);
                                } else if (event.key === "ArrowUp") {
                                  event.preventDefault();
                                  moveTo(index - 1);
                                } else if (event.key === "Home") {
                                  event.preventDefault();
                                  moveTo(0);
                                } else if (event.key === "End") {
                                  event.preventDefault();
                                  moveTo(recipes.length - 1);
                                }
                              }}
                            >
                              <span
                                className="traversal-modal__row-index"
                                aria-hidden="true"
                              >
                                {index + 1}
                              </span>
                              <span className="traversal-modal__row-name">
                                {asTag(name)}
                              </span>
                              {requiredKinds.length ? (
                                <span className="traversal-modal__row-rel">
                                  {requiredKinds.map(asTag).join(" · ")}
                                </span>
                              ) : null}
                            </button>
                          </li>
                        );
                      })}
                    </ol>
                </div>

                {activeName && activeSpec ? (
                  <Swap id={activeName}>
                  <div className="traversal-modal__inspector">
                    <div className="traversal-modal__header">
                      <h2 id="traversal-modal-title">{asTag(activeName)}</h2>
                      {titleKinds.map((kind) => (
                        <span key={kind} className="traversal-modal__kind">
                          {asTag(kind)}
                        </span>
                      ))}
                    </div>

                    <div className="traversal-modal__body">
                      {activeSpec.purpose ? (
                        <p className="traversal-modal__purpose">
                          {activeSpec.purpose}
                        </p>
                      ) : null}

                      {nodeParams(activeSpec).map(([param, parameter]) => {
                        const boundNode = picks[param];
                        const role = paramRole(param, parameter.type);

                        if (boundNode) {
                          return (
                            <button
                              key={param}
                              type="button"
                              className="traversal-modal__bind"
                              aria-label={`Change ${role}`}
                              onClick={() =>
                                setPicks((current) => {
                                  const next = { ...current };
                                  delete next[param];
                                  return next;
                                })
                              }
                            >
                              <span className="traversal-modal__field">
                                <span className="traversal-modal__bind-name">
                                  {boundNode.label || boundNode.id}
                                </span>
                                <span className="traversal-modal__row-rel">
                                  {role}
                                </span>
                              </span>
                            </button>
                          );
                        }

                        return (
                          <div key={param} className="traversal-modal__bind">
                            <div className="traversal-modal__field">
                              <div className="traversal-modal__finder">
                                <NodeFinder
                                  map={map}
                                  kinds={parameter.kinds}
                                  wide
                                  onPick={(node) =>
                                    setPicks((current) => ({
                                      ...current,
                                      [param]: node,
                                    }))
                                  }
                                />
                              </div>
                              <span className="traversal-modal__row-rel">
                                {role}
                              </span>
                            </div>
                          </div>
                        );
                      })}

                      {otherParams(activeSpec).map(([param]) => (
                        <label key={param} className="traversal-modal__bind">
                          <span className="traversal-modal__field">
                            <input
                              className="traversal-modal__input"
                              value={extra[param] ?? ""}
                              placeholder=""
                              aria-label={asTag(param)}
                              onChange={(event) =>
                                setExtra((current) => ({
                                  ...current,
                                  [param]: event.target.value,
                                }))
                              }
                            />
                            <span className="traversal-modal__row-rel">
                              {asTag(param)}
                            </span>
                          </span>
                        </label>
                      ))}

                      {Object.keys(activeSpec.parameters ?? {}).length === 0 ? (
                        <p className="traversal-modal__status">
                          This traversal runs without parameters.
                        </p>
                      ) : null}

                      {error ? (
                        <NoticeCard
                          kind="fault"
                          body={error}
                          onDismiss={() => setError("")}
                          dismissible
                        />
                      ) : null}
                    </div>

                    <div className="traversal-modal__foot">
                      <button
                        type="button"
                        className="traversal-modal__run"
                        disabled={running || !isReady}
                        onClick={() => void execute(activeName, picks, extra)}
                      >
                        {running ? "Running…" : "Run"}
                      </button>
                    </div>
                  </div>
                  </Swap>
                ) : null}
              </div>
            </div>,
            overlayHost(),
          )
        : null}
    </>
  );
}
