/**
 * Find a node by name, and put the map around it.
 *
 * The map is deliberately uncapped — a 416-node corpus renders in full — which
 * makes "where is the thing I am thinking of" the first question an operator
 * has, and until now there was no way to ask it. Panning a 400-node graph
 * hunting for a label is not browsing, it is searching by hand.
 *
 * A hit is one node. Picking it is the same jump the neighbour strip already
 * does: select the disc and fly the camera. Incident filaments fan around it
 * because selection does that; search does not invert the map into a
 * neighbourhood overlay.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";

import type { GraphMap, MapNode } from "../api/graph";
import { usePresence } from "../styles/usePresence";
import "../styles/presence.css";
import "./NodeFinder.css";

/** Results shown at once. A display cap — never a cap on what is searched. */
const VISIBLE_RESULTS = 10;

type Props = {
  map: GraphMap | null;
  /** The node to inspect and fly to — same jump as a neighbour-strip row. */
  onPick: (node: MapNode) => void;
  /** Restrict hits to these user-format kinds. Empty means the whole map. */
  kinds?: string[];
  placeholder?: string;
  /** Fill the available width — the traversal menu, not the instrument cell. */
  wide?: boolean;
};

function kindAllowed(node: MapNode, kinds?: string[]): boolean {
  if (!kinds?.length) return true;
  const kind = (node.kind || "").toLowerCase();
  if (!kind) return false;
  return kinds.some((allowed) => kind === allowed.toLowerCase());
}

/**
 * Rank a node against a query, or `null` for no match.
 *
 * Ordered by how *deliberate* the match is: someone who typed an exact id meant
 * that node, someone whose text starts a label probably means that one, and an
 * anchor hit is a guess worth offering last. Ties break on the shorter label,
 * so `Cookie` outranks `Cookie attribute handling` for the query "cookie".
 */
function rank(node: MapNode, query: string): number | null {
  const id = node.id.toLowerCase();
  const label = (node.label || "").toLowerCase();
  const anchor = (node.semantic_anchor || "").toLowerCase();

  const kind = (node.kind || "").toLowerCase();

  if (id === query || label === query) return 0;
  if (label.startsWith(query)) return 1;
  if (id.startsWith(query)) return 2;
  if (kind === query) return 3;
  if (label.includes(query)) return 4;
  if (id.includes(query)) return 5;
  if (kind.includes(query)) return 6;
  if (anchor.includes(query)) return 7;
  return null;
}

export default function NodeFinder({
  map,
  onPick,
  kinds,
  placeholder = "Find a node…",
  wide = false,
}: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const listId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);

  const results = useMemo(() => {
    if (!map) return [];
    const pool = kinds?.length
      ? map.nodes.filter((node) => kindAllowed(node, kinds))
      : map.nodes;
    const needle = query.trim().toLowerCase();
    if (!needle) {
      if (!kinds?.length) return [];
      return [...pool]
        .sort((a, b) =>
          (a.label || a.id).localeCompare(b.label || b.id),
        )
        .slice(0, VISIBLE_RESULTS);
    }
    const scored: Array<{ node: MapNode; score: number }> = [];
    for (const node of pool) {
      const score = rank(node, needle);
      if (score !== null) scored.push({ node, score });
    }
    scored.sort(
      (a, b) =>
        a.score - b.score ||
        (a.node.label || a.node.id).length - (b.node.label || b.node.id).length ||
        a.node.id.localeCompare(b.node.id),
    );
    return scored.slice(0, VISIBLE_RESULTS).map((row) => row.node);
  }, [kinds, map, query]);

  // Reset the cursor whenever the candidate set changes, or the highlight
  // survives onto a different row and Enter picks something never looked at.
  useEffect(() => setActive(0), [query]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const pick = (node: MapNode) => {
    setQuery("");
    setOpen(false);
    rootRef.current?.querySelector("input")?.blur();
    onPick(node);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (open || query) {
        event.stopPropagation();
        event.preventDefault();
        setQuery("");
        setOpen(false);
      }
      return;
    }
    if (!results.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => (index + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => (index - 1 + results.length) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const chosen = results[active];
      if (chosen) pick(chosen);
    }
  };

  const showList = open && (Boolean(query.trim()) || Boolean(kinds?.length));
  const listPresence = usePresence(showList);

  return (
    <div className={wide ? "nodefind nodefind--wide" : "nodefind"} ref={rootRef}>
      <input
        className="nodefind__input"
        type="text"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          showList && results[active] ? `${listId}-${active}` : undefined
        }
        placeholder={placeholder}
        value={query}
        disabled={!map}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {listPresence.mounted ? (
        <ul
          className={`nodefind__list motion-layer motion-layer--fade${listPresence.shown ? " is-in" : ""}`}
          id={listId}
          role="listbox"
        >
          {results.length ? (
            results.map((node, index) => (
              <li
                key={node.id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                className={
                  index === active
                    ? "nodefind__row nodefind__row--active"
                    : "nodefind__row"
                }
                // `mousedown` rather than `click`: the input's blur would tear
                // the list down before a click ever landed.
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(node);
                }}
                onMouseEnter={() => setActive(index)}
              >
                <span className="nodefind__label">{node.label || node.id}</span>
                {node.kind ? (
                  <span className="nodefind__anchor">{node.kind.toLowerCase()}</span>
                ) : node.semantic_anchor ? (
                  <span className="nodefind__anchor">{node.semantic_anchor}</span>
                ) : null}
              </li>
            ))
          ) : (
            <li className="nodefind__row nodefind__row--empty">
              nothing on this map matches
            </li>
          )}
        </ul>
      ) : null}
    </div>
  );
}
