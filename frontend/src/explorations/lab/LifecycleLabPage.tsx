import { useCallback, useEffect, useRef, useState } from "react";
import "./LifecycleLabPage.css";

type LifeNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  /** UI phase for enter / exit transitions */
  phase: "entering" | "alive" | "exiting";
};

const STAGE_W = 720;
const STAGE_H = 440;
const R = 40;

function randomPoint(existing: LifeNode[]): { x: number; y: number } {
  for (let i = 0; i < 24; i++) {
    const x = 80 + Math.random() * (STAGE_W - 160);
    const y = 70 + Math.random() * (STAGE_H - 140);
    if (
      existing.every((n) => Math.hypot(n.x - x, n.y - y) > R * 2.4)
    ) {
      return { x, y };
    }
  }
  return { x: STAGE_W / 2, y: STAGE_H / 2 };
}

export function LifecycleLabPage() {
  const [nodes, setNodes] = useState<LifeNode[]>(() => [
    { id: "a", label: "Seed", x: 220, y: 220, phase: "alive" },
    { id: "b", label: "Seed", x: 480, y: 220, phase: "alive" },
  ]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [log, setLog] = useState("Birth adds a node; select then Delete exits.");
  const seq = useRef(0);
  const exitTimers = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    return () => {
      for (const t of exitTimers.current.values()) window.clearTimeout(t);
    };
  }, []);

  const birth = useCallback(() => {
    seq.current += 1;
    const id = `n${seq.current}-${Date.now().toString(36)}`;
    const pos = randomPoint(nodes.filter((n) => n.phase !== "exiting"));
    const label = `N${seq.current}`;
    setNodes((list) => [
      ...list,
      { id, label, x: pos.x, y: pos.y, phase: "entering" },
    ]);
    setSelectedId(id);
    setLog(`Birth ${label} — enter (scale 0 → 1).`);
    window.setTimeout(() => {
      setNodes((list) =>
        list.map((n) =>
          n.id === id && n.phase === "entering" ? { ...n, phase: "alive" } : n,
        ),
      );
    }, 420);
  }, [nodes]);

  const kill = useCallback((id: string) => {
    setNodes((list) =>
      list.map((n) => (n.id === id ? { ...n, phase: "exiting" } : n)),
    );
    setLog(`Death ${id} — exit (scale → 0), then remove.`);
    setSelectedId((cur) => (cur === id ? null : cur));
    const prev = exitTimers.current.get(id);
    if (prev) window.clearTimeout(prev);
    exitTimers.current.set(
      id,
      window.setTimeout(() => {
        setNodes((list) => list.filter((n) => n.id !== id));
        exitTimers.current.delete(id);
      }, 420),
    );
  }, []);

  const deleteSelected = () => {
    if (!selectedId) {
      setLog("Select a node first.");
      return;
    }
    kill(selectedId);
  };

  return (
    <div className="lifecycle-lab">
      <header className="lifecycle-lab__chrome">
        <p className="lifecycle-lab__eyebrow">Design lab</p>
        <h1 className="lifecycle-lab__title">Node lifecycle</h1>
        <p className="lifecycle-lab__lede">
          Births and deletions isolated from connect / Field. Enter = grow from
          a point; exit = shrink then drop from the model — the same join
          pattern d3 uses with force layouts.
        </p>
        <p className="lifecycle-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/trial">Trial</a>
          <span aria-hidden> · </span>
          <a href="#/">Field</a>
        </p>

        <div className="lifecycle-lab__actions">
          <button type="button" onClick={birth}>
            Birth node
          </button>
          <button type="button" onClick={deleteSelected} disabled={!selectedId}>
            Delete selected
          </button>
        </div>

        <p className="lifecycle-lab__log" role="status">
          {log}
        </p>
      </header>

      <div
        className="lifecycle-lab__stage"
        onClick={() => setSelectedId(null)}
      >
        {nodes.map((n) => (
          <button
            key={n.id}
            type="button"
            className={[
              "lifecycle-lab__disc",
              `lifecycle-lab__disc--${n.phase}`,
              selectedId === n.id ? "lifecycle-lab__disc--selected" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            style={{
              left: n.x - R,
              top: n.y - R,
              width: R * 2,
              height: R * 2,
            }}
            onClick={(e) => {
              e.stopPropagation();
              if (n.phase === "exiting") return;
              setSelectedId(n.id);
            }}
          >
            <span>{n.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
