import { useEffect, useMemo, useRef, useState } from "react";
import MDEditor from "@uiw/react-md-editor";
import "@uiw/react-md-editor/markdown-editor.css";
import "@uiw/react-markdown-preview/markdown.css";
import {
  fetchNode,
  fetchNodeSources,
  prefetchNodeContent,
  readNodeContent,
  type GraphMap,
  type GraphNodeBody,
  type MapNode,
  type NodeSources,
} from "../api/graph";
import { surfaceError } from "../api/resource";
import { edgeDisplayLabel } from "../shared/protocolVocabulary";
import type { ThemeMode } from "../styles/graphDna";
import { NoticeCard } from "./Notice";
import "./NodeReaderPanel.css";

type Connection = {
  key: string;
  id: string;
  title: string;
  relation: string;
  direction: "outgoing" | "incoming";
};

function asTag(value: string): string {
  return value.trim().replaceAll("_", " ").toLowerCase();
}

type NodeReaderPanelProps = {
  node: MapNode;
  graphId?: string;
  map: GraphMap;
  theme?: ThemeMode;
  onSelectNode: (nodeId: string) => void;
  /** Indicate a neighbour on the map without selecting it. */
  onPreviewNode?: (nodeId: string | null) => void;
};

/**
 * Node bodies are often authored as `# Label` plus the paragraph. The reader
 * already names the node, so that heading is a second title — and the preview
 * turns it into a fragment link that rewrites `#/graph?…`.
 */
function dropRepeatedTitle(markdown: string, title: string): string {
  const name = title.trim().toLowerCase();
  if (!name) return markdown;
  return markdown.replace(
    /^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*(?:\n+|$)/,
    (full, heading: string) =>
      heading.trim().toLowerCase() === name ? "" : full,
  );
}

function unwrapHeadingAutolink(
  node: unknown,
  _index: number | undefined,
  parent?: unknown,
) {
  if (!node || typeof node !== "object") return;
  if (!parent || typeof parent !== "object") return;
  const current = node as { tagName?: string; children?: unknown[] };
  const owner = parent as { tagName?: string; children?: unknown[] };
  if (current.tagName !== "a" || !owner.tagName) return;
  if (!/^h[1-6]$/.test(owner.tagName)) return;
  const siblings = owner.children;
  if (!Array.isArray(siblings)) return;
  const at = siblings.indexOf(node);
  if (at < 0) return;
  const inner = Array.isArray(current.children) ? current.children : [];
  owner.children = [...siblings.slice(0, at), ...inner, ...siblings.slice(at + 1)];
}

function keepProductHash(event: { target: EventTarget | null; preventDefault: () => void }) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const link = target.closest("a");
  if (!link) return;
  const href = link.getAttribute("href") || "";
  if (href.startsWith("#") && !href.startsWith("#/")) event.preventDefault();
}

function connectionsFor(nodeId: string, map: GraphMap): Connection[] {
  const of = new Map(map.nodes.map((n) => [n.id, n]));
  return map.edges.flatMap((edge, index) => {
    if (edge.source !== nodeId && edge.target !== nodeId) return [];
    const outgoing = edge.source === nodeId;
    const linkedId = outgoing ? edge.target : edge.source;
    const linked = of.get(linkedId);
    return [
      {
        key: `${edge.type}:${edge.source}->${edge.target}:${index}`,
        id: linkedId,
        title: linked?.label || linkedId,
        relation: edgeDisplayLabel(edge.type, edge.label),
        direction: outgoing ? ("outgoing" as const) : ("incoming" as const),
      },
    ];
  });
}

/**
 * Neighbours of the open node. A three-row strip that scrolls like any
 * list. Tab lands once; arrows move; Enter jumps. Hover or focus lights
 * the joining edge on the map — only the most recent of the two.
 */
function NeighbourList({
  connections,
  onSelectNode,
  onPreviewNode,
  onPrefetchNode,
}: {
  connections: Connection[];
  onSelectNode: (nodeId: string) => void;
  onPreviewNode?: (nodeId: string | null) => void;
  onPrefetchNode?: (nodeId: string) => void;
}) {
  const listRef = useRef<HTMLOListElement>(null);
  const preview = useRef(onPreviewNode);
  preview.current = onPreviewNode;
  const prefetch = useRef(onPrefetchNode);
  prefetch.current = onPrefetchNode;
  const hoverIndex = useRef<number | null>(null);
  const ignoreHover = useRef<number | null>(null);
  const [active, setActive] = useState(0);
  const [shown, setShown] = useState<number | null>(null);

  const publish = (id: string | null) => {
    preview.current?.(id);
    // Hovering a neighbour warms its body + sources, so hopping the strip is
    // instant — the click that follows finds the cache already filled.
    if (id) prefetch.current?.(id);
  };

  const show = (index: number | null) => {
    setShown(index);
    publish(index === null ? null : (connections[index]?.id ?? null));
  };

  const buttons = () =>
    listRef.current
      ? [
          ...listRef.current.querySelectorAll<HTMLButtonElement>(
            ".node-reader__link",
          ),
        ]
      : [];

  const moveTo = (index: number) => {
    const next = Math.max(0, Math.min(connections.length - 1, index));
    ignoreHover.current = hoverIndex.current;
    setActive(next);
    show(next);
    const button = buttons()[next];
    button?.focus();
    button?.scrollIntoView({ block: "nearest" });
  };

  useEffect(() => {
    hoverIndex.current = null;
    ignoreHover.current = null;
    setActive(0);
    setShown(null);
    publish(null);
  }, [connections]);

  return (
    <div className="node-reader__menu">
      <ol
        ref={listRef}
        className="node-reader__connections"
        aria-label="Linked nodes"
        onMouseLeave={() => {
          hoverIndex.current = null;
          ignoreHover.current = null;
          if (listRef.current?.contains(document.activeElement)) {
            show(active);
          } else {
            show(null);
          }
        }}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            if (hoverIndex.current === null) show(null);
          }
        }}
      >
        {connections.map((connection, index) => (
          <li key={connection.key}>
            <button
              type="button"
              className={
                shown === index
                  ? "node-reader__link is-current"
                  : "node-reader__link"
              }
              tabIndex={index === active ? 0 : -1}
              onClick={() => onSelectNode(connection.id)}
              onFocus={() => {
                setActive(index);
                ignoreHover.current = hoverIndex.current;
                show(index);
              }}
              onMouseEnter={() => {
                hoverIndex.current = index;
                if (ignoreHover.current === index) return;
                ignoreHover.current = null;
                show(index);
              }}
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
                  moveTo(connections.length - 1);
                }
              }}
            >
              <span className="node-reader__link-index" aria-hidden="true">
                {index + 1}
              </span>
              <span className="node-reader__link-name">{connection.title}</span>
              <span className="node-reader__link-rel">
                {connection.direction === "incoming" ? "← " : ""}
                {asTag(connection.relation)}
                {connection.direction === "outgoing" ? " →" : ""}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}


/**
 * What this node was built from.
 *
 * The graph stores atom *ids*; the passage text lives in a sidecar written
 * beside the graph at materialization. Three states, and they are three
 * different facts that must not be shown as one:
 *
 *   - passages resolved       — here is the source
 *   - no sidecar              — this graph cannot resolve its source ids
 *   - sidecar, nothing cited  — this node was not built from a source
 *
 * The middle one is every graph built before sidecars existed, so it is the
 * common case rather than the edge case. Rendering it as "no source" would
 * tell the reader something false about the node.
 */
function SourceBlock({
  nodeId,
  graphId,
  topology,
}: {
  nodeId: string;
  graphId?: string;
  topology: string;
}) {
  const cached =
    graphId && topology
      ? (readNodeContent(graphId, nodeId, topology)?.sources ?? null)
      : null;
  const [fetched, setFetched] = useState<NodeSources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const data = cached ?? fetched;

  useEffect(() => {
    setFetched(null);
    setError(null);
    if (graphId && topology) {
      const hit = readNodeContent(graphId, nodeId, topology)?.sources;
      if (hit) return;
    }
    const abort = new AbortController();
    fetchNodeSources(nodeId, graphId, abort.signal)
      .then((payload) => {
        if (abort.signal.aborted) return;
        setFetched(payload);
      })
      .catch((err: unknown) => {
        if (abort.signal.aborted) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(surfaceError(err, "Could not read this node's source.") || null);
      });
    return () => abort.abort();
  }, [graphId, nodeId, topology]);

  if (error) {
    return (
      <p className="node-reader__source-error" role="status">
        {error}
      </p>
    );
  }
  if (!data) return null;

  if (!data.available) {
    return (
      <details className="node-reader__source">
        <summary>
          <span>Source</span>
          <span className="node-reader__source-count">not recorded</span>
        </summary>
        <p className="node-reader__source-absent">
          This graph has no source sidecar, so the passages behind its nodes
          cannot be resolved. It was built before sidecars, or by a path that
          does not write one.
        </p>
      </details>
    );
  }

  const units = data.units ?? [];
  const unresolved = data.unresolved_unit_ids ?? [];
  if (!units.length && !unresolved.length) {
    return (
      <details className="node-reader__source">
        <summary>
          <span>Source</span>
          <span className="node-reader__source-count">none cited</span>
        </summary>
        <p className="node-reader__source-absent">
          This node records no source unit. It was authored rather than built
          from a passage.
        </p>
      </details>
    );
  }

  return (
    <details className="node-reader__source">
      <summary>
        <span>Source</span>
        <span className="node-reader__source-count">
          {units.length === 1 ? "1 passage" : `${units.length} passages`}
        </span>
      </summary>

      {units.map((unit) => (
        <figure className="node-reader__passage" key={unit.atom_id}>
          {unit.heading_path.length || unit.locator ? (
            <figcaption>
              {unit.heading_path.length ? (
                <span className="node-reader__passage-heading">
                  {unit.heading_path.join(" › ")}
                </span>
              ) : null}
              {unit.locator ? (
                <span className="node-reader__passage-locator">{unit.locator}</span>
              ) : null}
            </figcaption>
          ) : null}
          <blockquote>{unit.excerpt}</blockquote>
          {unit.truncated ? (
            /* A silently cut excerpt reads as the whole passage. */
            <p className="node-reader__passage-more">
              Excerpt — the unit continues in the source.
            </p>
          ) : null}
        </figure>
      ))}

      {unresolved.length ? (
        <p className="node-reader__passage-missing">
          {unresolved.length === 1
            ? "1 cited unit is not in this graph's sidecar"
            : `${unresolved.length} cited units are not in this graph's sidecar`}
          : {unresolved.join(", ")}
        </p>
      ) : null}
    </details>
  );
}

/**
 * Neighbours, then the name and the body.
 * The dock has no side tab — that tab would only repeat the name.
 */
export function NodeReaderPanel({
  node,
  graphId,
  map,
  theme = "light",
  onSelectNode,
  onPreviewNode,
}: NodeReaderPanelProps) {
  const topology = map.topology_version ?? "";
  const initial = graphId && topology
    ? readNodeContent(graphId, node.id, topology)
    : null;
  const [body, setBody] = useState<GraphNodeBody | null>(
    () => initial?.body ?? null,
  );
  const [loading, setLoading] = useState(() => !initial?.body);
  const [error, setError] = useState<string | null>(null);

  const connections = useMemo(
    () => connectionsFor(node.id, map),
    [node.id, map],
  );

  useEffect(() => {
    const abort = new AbortController();
    const cached =
      graphId && topology
        ? readNodeContent(graphId, node.id, topology)
        : null;
    if (cached?.body) {
      setBody(cached.body);
      setLoading(false);
      setError(null);
      return () => abort.abort();
    }
    setLoading(true);
    setError(null);
    setBody(null);
    fetchNode(node.id, graphId, abort.signal)
      .then((payload) => {
        if (abort.signal.aborted) return;
        setBody(payload);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (abort.signal.aborted) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(surfaceError(err, "Could not load node body") || null);
        setLoading(false);
      });
    return () => abort.abort();
  }, [graphId, node.id, topology]);

  const title = body?.label || node.label;
  const markdown = dropRepeatedTitle(
    (body?.text_content ?? "").trim(),
    title,
  );
  const formatKind = String(body?.kind || node.kind || "");

  return (
    <div
      className="node-reader"
      data-color-mode={theme === "dark" ? "dark" : "light"}
    >
      {connections.length ? (
        <NeighbourList
          connections={connections}
          onSelectNode={onSelectNode}
          onPreviewNode={onPreviewNode}
          onPrefetchNode={(nodeId) => {
            if (graphId && map.topology_version) {
              prefetchNodeContent(nodeId, graphId, map.topology_version);
            }
          }}
        />
      ) : null}

      <div className="node-reader__header">
        <h2 title={title}>{title}</h2>
        {formatKind ? (
          <span className="node-reader__kind">{asTag(formatKind)}</span>
        ) : null}
      </div>

      <div className="node-reader__body">
        {loading ? (
          <p className="node-reader__status">Reading body…</p>
        ) : error ? (
          <NoticeCard kind="unavailable" body={error} />
        ) : markdown ? (
          <MDEditor.Markdown
            source={markdown}
            rehypeRewrite={unwrapHeadingAutolink}
            wrapperElement={{ onClick: keepProductHash }}
          />
        ) : (
          <p className="node-reader__status">No body on this node.</p>
        )}
      </div>

      <SourceBlock nodeId={node.id} graphId={graphId} topology={topology} />
    </div>
  );
}
