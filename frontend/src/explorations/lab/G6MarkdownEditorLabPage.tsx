import { useEffect, useRef, useState } from "react";
import {
  Graph,
  type GraphData,
  type IElementEvent,
  type IPointerEvent,
} from "@antv/g6";
import MDEditor from "@uiw/react-md-editor";
import "./G6MarkdownEditorLabPage.css";

type NoteId = "platform" | "auth" | "search" | "docs" | "audit" | "cache";
type EditorMode = "edit" | "preview";

type Note = {
  title: string;
  markdown: string;
  type: string;
  status: "Active" | "Draft" | "Review";
  owner: string;
  createdAt: string;
  updatedAt: string;
};

const INITIAL_NOTES: Record<NoteId, Note> = {
  platform: {
    title: "Platform",
    type: "System",
    status: "Active",
    owner: "Maya Chen",
    createdAt: "2026-02-08T09:14:00Z",
    updatedAt: "2026-07-16T18:42:00Z",
    markdown: `# Platform

The shared application surface that connects **identity**, content, and discovery.

## Current direction

- Keep graph interactions direct
- Treat notes as first-class node content
- Use Markdown for portable, structured writing

> This panel is a local editing trial. Nothing is persisted yet.`,
  },
  auth: {
    title: "Authentication",
    type: "Domain",
    status: "Review",
    owner: "Noah Williams",
    createdAt: "2026-03-12T11:30:00Z",
    updatedAt: "2026-07-15T14:08:00Z",
    markdown: `# Authentication

Controls session creation and access decisions.

## Open questions

- Should sessions rotate on every privilege change?
- Where should recovery codes live?

\`\`\`ts
type Session = {
  userId: string;
  expiresAt: number;
};
\`\`\``,
  },
  search: {
    title: "Search",
    type: "Capability",
    status: "Active",
    owner: "Ari Patel",
    createdAt: "2026-04-03T08:45:00Z",
    updatedAt: "2026-07-14T16:22:00Z",
    markdown: `# Search

Turns indexed content into ranked, explainable results.

1. Parse the query
2. Retrieve candidates
3. Rank by relevance
4. Return supporting context`,
  },
  docs: {
    title: "Documentation",
    type: "Domain",
    status: "Draft",
    owner: "Elena Rossi",
    createdAt: "2026-05-19T13:05:00Z",
    updatedAt: "2026-07-16T10:17:00Z",
    markdown: `# Documentation

The authoring and publishing path for product knowledge.

**Goal:** make the useful path obvious without hiding advanced detail.`,
  },
  audit: {
    title: "Audit trail",
    type: "Capability",
    status: "Review",
    owner: "Noah Williams",
    createdAt: "2026-03-28T15:20:00Z",
    updatedAt: "2026-07-12T09:41:00Z",
    markdown: `# Audit trail

An append-only history of meaningful system actions.

| Field | Purpose |
| --- | --- |
| Actor | Who initiated it |
| Action | What changed |
| Time | When it happened |`,
  },
  cache: {
    title: "Cache",
    type: "Infrastructure",
    status: "Active",
    owner: "Sam Okafor",
    createdAt: "2026-06-01T10:00:00Z",
    updatedAt: "2026-07-16T17:56:00Z",
    markdown: `# Cache

Reduces repeated work at known boundaries.

- Short TTL for search results
- Explicit invalidation for policy changes
- Metrics before broader adoption`,
  },
};

const DATA: GraphData = {
  nodes: [
    { id: "platform", style: { x: 360, y: 245 } },
    { id: "auth", style: { x: 150, y: 100 } },
    { id: "search", style: { x: 560, y: 105 } },
    { id: "docs", style: { x: 610, y: 355 } },
    { id: "audit", style: { x: 150, y: 380 } },
    { id: "cache", style: { x: 355, y: 470 } },
  ],
  edges: [
    {
      id: "platform-auth",
      source: "platform",
      target: "auth",
      data: { relation: "contains", kind: "CONTAINS" },
    },
    {
      id: "platform-search",
      source: "platform",
      target: "search",
      data: { relation: "contains", kind: "CONTAINS" },
    },
    {
      id: "platform-docs",
      source: "platform",
      target: "docs",
      data: { relation: "contains", kind: "CONTAINS" },
    },
    {
      id: "auth-audit",
      source: "auth",
      target: "audit",
      data: { relation: "writes to", kind: "LEADSTO" },
    },
    {
      id: "search-cache",
      source: "search",
      target: "cache",
      data: { relation: "reads from", kind: "NEARTO" },
    },
    {
      id: "docs-cache",
      source: "docs",
      target: "cache",
      data: { relation: "invalidates", kind: "LEADSTO" },
    },
    {
      id: "audit-cache",
      source: "audit",
      target: "cache",
      data: { relation: "near to", kind: "NEARTO" },
    },
  ],
};

function isNoteId(id: string): id is NoteId {
  return id in INITIAL_NOTES;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function connectionsFor(id: NoteId) {
  return (DATA.edges ?? []).flatMap((edge) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (source !== id && target !== id) return [];
    const linkedId = source === id ? target : source;
    if (!isNoteId(linkedId)) return [];
    return [
      {
        id: linkedId,
        title: INITIAL_NOTES[linkedId].title,
        relation: String(edge.data?.relation ?? "linked"),
        direction: source === id ? ("outgoing" as const) : ("incoming" as const),
      },
    ];
  });
}

export function G6MarkdownEditorLabPage() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [notes, setNotes] = useState(INITIAL_NOTES);
  const [selectedId, setSelectedId] = useState<NoteId | null>(null);
  const [editorMode, setEditorMode] = useState<EditorMode>("edit");

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph({
      container: containerRef.current,
      data: DATA,
      autoFit: "view",
      padding: 70,
      node: {
        style: {
          size: 88,
          fill: "#171717",
          stroke: "#171717",
          lineWidth: 1.5,
          labelText: (datum) => INITIAL_NOTES[datum.id as NoteId]?.title ?? String(datum.id),
          labelPlacement: "center",
          labelFill: "#f7f7f7",
          labelFontFamily: '"IBM Plex Sans Condensed", sans-serif',
          labelFontSize: 11,
          labelFontWeight: 500,
          labelMaxWidth: "72%",
          labelWordWrap: true,
          labelMaxLines: 2,
          labelTextOverflow: "ellipsis",
          cursor: "pointer",
        },
        state: {
          selected: {
            lineWidth: 4,
            stroke: "#171717",
            halo: true,
            haloLineWidth: 10,
            haloStroke: "#171717",
            haloStrokeOpacity: 0.12,
          },
        },
      },
      edge: {
        style: {
          stroke: "#8b8b8b",
          lineWidth: 1.25,
          endArrow: true,
          endArrowType: "triangle",
          endArrowSize: 7,
          increasedLineWidthForHitTesting: 20,
          labelText: (datum) => String(datum.data?.relation ?? "linked"),
          labelPlacement: "center",
          labelFill: "#171717",
          labelFontFamily: '"IBM Plex Sans", sans-serif',
          labelFontSize: 10,
          labelFontWeight: 500,
          labelBackground: true,
          labelBackgroundFill: "#fff",
          labelBackgroundOpacity: 0.96,
          labelBackgroundPadding: [3, 5, 3, 5],
          labelOpacity: 0,
        },
        state: {
          active: {
            stroke: "#171717",
            lineWidth: 1.75,
            labelOpacity: 1,
          },
        },
        animation: {
          update: [
            {
              fields: ["stroke", "lineWidth"],
              shape: "key",
              duration: 280,
              easing: "cubic-bezier(0.16, 1, 0.3, 1)",
            },
            {
              fields: ["opacity"],
              shape: "label",
              duration: 360,
              easing: "cubic-bezier(0.16, 1, 0.3, 1)",
            },
          ],
        },
      },
      behaviors: [
        "drag-canvas",
        "zoom-canvas",
        "drag-element",
        "click-select",
        {
          type: "hover-activate",
          degree: 0,
          animation: true,
          enable: (event: IPointerEvent) => event.targetType === "edge",
        },
      ],
      animation: true,
    });

    graph.on("node:click", (event) => {
      const id = String((event as IElementEvent).target.id);
      if (isNoteId(id)) setSelectedId(id);
    });

    graph.render().catch(() => {});

    return () => {
      graph.destroy();
    };
  }, []);

  const selectedNote = selectedId ? notes[selectedId] : null;
  const connections = selectedId ? connectionsFor(selectedId) : [];

  return (
    <main className="md-node-lab" data-color-mode="light">
      <header className="md-node-lab__header">
        <div>
          <p className="md-node-lab__eyebrow">Interaction trial</p>
          <h1>Node content editor</h1>
          <p>
            Select a graph node to open its Markdown note. Editing is local to
            this page and intentionally has no save action yet.
          </p>
        </div>
        <a href="#/explorations">← Explorations</a>
      </header>

      <section className="md-node-lab__workspace">
        <div className="md-node-lab__graph-shell">
          <div className="md-node-lab__graph-meta">
            <span>Knowledge graph</span>
            <span>{selectedId ? `Editing ${notes[selectedId].title}` : "Choose a node"}</span>
          </div>
          <div ref={containerRef} className="md-node-lab__graph" />
        </div>

        <aside
          className={
            "md-node-lab__panel" + (selectedNote ? " md-node-lab__panel--open" : "")
          }
          aria-hidden={!selectedNote}
        >
          {selectedNote && selectedId ? (
            <>
              <div className="md-node-lab__panel-header">
                <div className="md-node-lab__panel-identity">
                  <h2>{selectedNote.title}</h2>
                  <span className={`md-node-lab__status md-node-lab__status--${selectedNote.status.toLowerCase()}`}>
                    {selectedNote.status}
                  </span>
                </div>
                <div className="md-node-lab__panel-actions">
                  <div className="md-node-lab__mode-switch" aria-label="Editor view">
                    <button
                      type="button"
                      aria-pressed={editorMode === "edit"}
                      onClick={() => setEditorMode("edit")}
                    >
                      Write
                    </button>
                    <button
                      type="button"
                      aria-pressed={editorMode === "preview"}
                      onClick={() => setEditorMode("preview")}
                    >
                      Preview
                    </button>
                  </div>
                  <button
                    className="md-node-lab__close"
                    type="button"
                    onClick={() => setSelectedId(null)}
                    aria-label="Close editor"
                  >
                    ×
                  </button>
                </div>
              </div>

              <section className="md-node-lab__information" aria-label="Node information">
                <dl className="md-node-lab__metadata">
                  <div>
                    <dt>Type</dt>
                    <dd>{selectedNote.type}</dd>
                  </div>
                  <div>
                    <dt>Owner</dt>
                    <dd>{selectedNote.owner}</dd>
                  </div>
                  <div>
                    <dt>Created</dt>
                    <dd>
                      <time dateTime={selectedNote.createdAt}>
                        {formatDate(selectedNote.createdAt)}
                      </time>
                    </dd>
                  </div>
                  <div>
                    <dt>Updated</dt>
                    <dd>
                      <time dateTime={selectedNote.updatedAt}>
                        {formatDate(selectedNote.updatedAt)}
                      </time>
                    </dd>
                  </div>
                  <div>
                    <dt>Node ID</dt>
                    <dd><code>{selectedId}</code></dd>
                  </div>
                  <div>
                    <dt>Links</dt>
                    <dd>{connections.length}</dd>
                  </div>
                </dl>

                <div className="md-node-lab__connections" aria-label="Linked nodes">
                  <ul>
                    {connections.map((connection) => (
                      <li key={`${connection.direction}-${connection.id}`}>
                        <button type="button" onClick={() => setSelectedId(connection.id)}>
                          <span>{connection.title}</span>
                          <small>
                            {connection.direction === "incoming" ? "← " : ""}
                            {connection.relation}
                            {connection.direction === "outgoing" ? " →" : ""}
                          </small>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </section>

              <div className="md-node-lab__editor">
                <MDEditor
                  value={selectedNote.markdown}
                  onChange={(value) =>
                    setNotes((current) => ({
                      ...current,
                      [selectedId]: {
                        ...current[selectedId],
                        markdown: value ?? "",
                      },
                    }))
                  }
                  height="100%"
                  preview={editorMode}
                  hideToolbar={editorMode === "preview"}
                  extraCommands={[]}
                  visibleDragbar={false}
                  textareaProps={{
                    "aria-label": `Edit ${selectedNote.title} Markdown`,
                    placeholder: "Write Markdown…",
                  }}
                />
              </div>

              <footer className="md-node-lab__panel-footer">
                <span>Markdown · live preview</span>
                <span>Unsaved trial</span>
              </footer>
            </>
          ) : null}
        </aside>
      </section>
    </main>
  );
}
