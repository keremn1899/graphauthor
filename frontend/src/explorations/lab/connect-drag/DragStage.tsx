import { useCallback, useEffect, useRef, useState } from "react";
import { ReachTether } from "../../../field/gestures/ReachTether";
import {
  NODE_R,
  TAUT_DRIVE_MS,
  boundaryPoint,
  chordEnds,
  inDisc,
} from "../connect-ring/constants";
import "./DragStage.css";

type Point = { x: number; y: number };

type LabNode = {
  id: string;
  label: string;
  x: number;
  y: number;
};

type FirmEdge = {
  id: string;
  sourceId: string;
  targetId: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

type Phase = "idle" | "reaching" | "landing";

const NODES: LabNode[] = [
  { id: "a", label: "Source A", x: 220, y: 260 },
  { id: "b", label: "Target B", x: 520, y: 180 },
  { id: "c", label: "Target C", x: 520, y: 360 },
];

type DragStageProps = {
  reducedMotion: boolean;
  onLog: (msg: string) => void;
};

/**
 * No ring. Right-click a disc to start a reach (line follows cursor).
 * Left-click another disc to land; click empty space to cancel.
 * Target hover: inset selection wash on the node itself.
 */
export function DragStage({ reducedMotion, onLog }: DragStageProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [hoverTargetId, setHoverTargetId] = useState<string | null>(null);
  const [pointer, setPointer] = useState<Point | null>(null);
  const [firmEdges, setFirmEdges] = useState<FirmEdge[]>([]);
  const [landing, setLanding] = useState<{
    sourceId: string;
    targetId: string;
    from: Point;
    to: Point;
  } | null>(null);
  const [landSlack, setLandSlack] = useState(0);
  const [sourceId, setSourceId] = useState<string | null>(null);

  const sourceIdRef = useRef<string | null>(null);
  const landRaf = useRef<number | null>(null);
  const fallbackTimer = useRef<number | null>(null);
  const landingRef = useRef(landing);
  const landSlackRef = useRef(landSlack);
  const awaitingRestRef = useRef(false);
  const lockedRef = useRef(false);

  landingRef.current = landing;
  landSlackRef.current = landSlack;
  sourceIdRef.current = sourceId;

  const cancelLandAnim = useCallback(() => {
    if (landRaf.current != null) {
      cancelAnimationFrame(landRaf.current);
      landRaf.current = null;
    }
    if (fallbackTimer.current != null) {
      window.clearTimeout(fallbackTimer.current);
      fallbackTimer.current = null;
    }
    awaitingRestRef.current = false;
    lockedRef.current = false;
  }, []);

  const localPoint = useCallback((clientX: number, clientY: number): Point => {
    const rect = stageRef.current!.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }, []);

  const findDisc = useCallback((p: Point, exclude?: string) => {
    for (const n of NODES) {
      if (n.id === exclude) continue;
      if (inDisc({ x: n.x, y: n.y }, p, NODE_R + 4)) return n;
    }
    return null;
  }, []);

  const findDiscIncluding = useCallback((p: Point) => {
    for (const n of NODES) {
      if (inDisc({ x: n.x, y: n.y }, p, NODE_R + 4)) return n;
    }
    return null;
  }, []);

  const disengage = useCallback(() => {
    cancelLandAnim();
    setPhase("idle");
    setHoverTargetId(null);
    setPointer(null);
    setSourceId(null);
    sourceIdRef.current = null;
    setLanding(null);
    setLandSlack(0);
    onLog("Disengaged.");
  }, [cancelLandAnim, onLog]);

  const commitFirm = useCallback(
    (srcId: string, targetId: string, from: Point, to: Point) => {
      if (lockedRef.current) return;
      lockedRef.current = true;
      awaitingRestRef.current = false;
      if (fallbackTimer.current != null) {
        window.clearTimeout(fallbackTimer.current);
        fallbackTimer.current = null;
      }

      setFirmEdges((list) => [
        ...list,
        {
          id: `e-${srcId}-${targetId}-${Date.now().toString(36)}`,
          sourceId: srcId,
          targetId,
          x1: from.x,
          y1: from.y,
          x2: to.x,
          y2: to.y,
        },
      ]);
      setLandSlack(0);

      requestAnimationFrame(() => {
        setLanding(null);
        setPointer(null);
        setHoverTargetId(null);
        setSourceId(null);
        sourceIdRef.current = null;
        setPhase("idle");
        onLog(`Firm edge ${srcId} → ${targetId}.`);
      });
    },
    [onLog],
  );

  const beginReach = (nodeId: string, clientX: number, clientY: number) => {
    if (phase === "landing") return;
    cancelLandAnim();
    lockedRef.current = false;
    sourceIdRef.current = nodeId;
    setSourceId(nodeId);
    setPhase("reaching");
    setPointer(localPoint(clientX, clientY));
    setHoverTargetId(null);
    setLanding(null);
    onLog(`Reaching from ${nodeId} — left-click a disc to land, empty to cancel.`);
  };

  const landOn = useCallback(
    (targetId: string) => {
      const srcId = sourceIdRef.current;
      if (!srcId || srcId === targetId) return;
      const src = NODES.find((n) => n.id === srcId)!;
      const target = NODES.find((n) => n.id === targetId)!;

      const { from, to } = chordEnds(
        { x: src.x, y: src.y },
        { x: target.x, y: target.y },
      );

      cancelLandAnim();
      lockedRef.current = false;
      awaitingRestRef.current = false;
      setLanding({ sourceId: srcId, targetId: target.id, from, to });
      setPointer(to);
      setHoverTargetId(target.id);
      setPhase("landing");
      onLog(`Landed ${srcId} → ${target.id} — taut.`);

      if (reducedMotion) {
        setLandSlack(0);
        commitFirm(srcId, target.id, from, to);
        return;
      }

      const t0 = performance.now();
      const amp = 0.72;
      const omega = Math.PI * 2 * 2.0;
      const decay = 3.6;
      const phase0 = Math.PI / 2;

      const tick = (now: number) => {
        const t = (now - t0) / 1000;
        const s = amp * Math.exp(-decay * t) * Math.sin(omega * t + phase0);
        const next = Math.abs(s) < 0.012 ? 0 : s;
        setLandSlack(next);
        if (t * 1000 < TAUT_DRIVE_MS) {
          landRaf.current = requestAnimationFrame(tick);
        } else {
          landRaf.current = null;
          setLandSlack(0);
          awaitingRestRef.current = true;
          fallbackTimer.current = window.setTimeout(() => {
            const land = landingRef.current;
            if (land) {
              commitFirm(land.sourceId, land.targetId, land.from, land.to);
            }
          }, 140);
        }
      };
      setLandSlack(amp);
      landRaf.current = requestAnimationFrame(tick);
    },
    [cancelLandAnim, commitFirm, onLog, reducedMotion],
  );

  const onTetherRest = useCallback(() => {
    if (!awaitingRestRef.current || lockedRef.current) return;
    if (Math.abs(landSlackRef.current) > 0.02) return;
    const land = landingRef.current;
    if (!land) return;
    commitFirm(land.sourceId, land.targetId, land.from, land.to);
  }, [commitFirm]);

  const onDiscContextMenu = (nodeId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    beginReach(nodeId, e.clientX, e.clientY);
  };

  const onDiscClick = (nodeId: string, e: React.MouseEvent) => {
    if (e.button !== 0) return;
    if (phase !== "reaching") return;
    e.preventDefault();
    e.stopPropagation();
    if (nodeId === sourceIdRef.current) {
      disengage();
      return;
    }
    landOn(nodeId);
  };

  const onStagePointerMove = (e: React.PointerEvent) => {
    if (phase !== "reaching") return;
    const p = localPoint(e.clientX, e.clientY);
    setPointer(p);
    const src = sourceIdRef.current;
    if (!src) return;
    setHoverTargetId(findDisc(p, src)?.id ?? null);
  };

  const onStagePointerDown = (e: React.PointerEvent) => {
    if (phase !== "reaching") return;
    if (e.button !== 0) return;
    const p = localPoint(e.clientX, e.clientY);
    const hit = findDiscIncluding(p);
    if (!hit) {
      e.preventDefault();
      disengage();
    }
    // Disc clicks handled on the button (stopPropagation)
  };

  useEffect(
    () => () => {
      cancelLandAnim();
    },
    [cancelLandAnim],
  );

  const tetherSource =
    phase === "reaching" || phase === "landing"
      ? NODES.find((n) => n.id === (sourceIdRef.current ?? landing?.sourceId))
      : null;

  let tetherFrom: Point | null = null;
  let tetherTo: Point | null = null;
  let slack = 0;
  let tetherImmediate = false;

  if (phase === "landing" && landing) {
    tetherFrom = landing.from;
    tetherTo = landing.to;
    slack = landSlack;
  } else if (phase === "reaching" && tetherSource && pointer) {
    const hover = hoverTargetId
      ? NODES.find((n) => n.id === hoverTargetId)
      : null;
    if (hover) {
      const chord = chordEnds(
        { x: tetherSource.x, y: tetherSource.y },
        { x: hover.x, y: hover.y },
      );
      tetherFrom = chord.from;
      tetherTo = chord.to;
    } else {
      tetherFrom = boundaryPoint(
        { x: tetherSource.x, y: tetherSource.y },
        pointer,
      );
      tetherTo = pointer;
    }
    slack = 0;
    tetherImmediate = true;
  }

  const activeSource =
    sourceId ?? (landing ? landing.sourceId : null);
  const activeTarget =
    hoverTargetId ?? (landing ? landing.targetId : null);

  return (
    <div
      ref={stageRef}
      className={`drag-stage${phase === "reaching" ? " drag-stage--reaching" : ""}`}
      onPointerMove={onStagePointerMove}
      onPointerDown={onStagePointerDown}
      onContextMenu={(e) => e.preventDefault()}
    >
      <svg className="drag-stage__edges" aria-hidden>
        {firmEdges.map((e) => (
          <line
            key={e.id}
            x1={e.x1}
            y1={e.y1}
            x2={e.x2}
            y2={e.y2}
            className="drag-stage__firm"
          />
        ))}
      </svg>

      {tetherFrom && tetherTo && (
        <div className="drag-stage__tether">
          <ReachTether
            x1={tetherFrom.x}
            y1={tetherFrom.y}
            x2={tetherTo.x}
            y2={tetherTo.y}
            slack={slack}
            reducedMotion={reducedMotion}
            immediate={tetherImmediate}
            onRest={phase === "landing" ? onTetherRest : undefined}
          />
        </div>
      )}

      {NODES.map((n) => {
        const isSource = activeSource === n.id;
        const isTarget = activeTarget === n.id && !isSource;
        let role: "idle" | "source" | "target" = "idle";
        if (isSource) role = "source";
        else if (isTarget) role = "target";

        return (
          <button
            key={n.id}
            type="button"
            className={`drag-stage__disc drag-stage__disc--${role}`}
            style={{
              left: n.x - NODE_R,
              top: n.y - NODE_R,
              width: NODE_R * 2,
              height: NODE_R * 2,
            }}
            data-node-id={n.id}
            aria-label={n.label}
            onContextMenu={(e) => onDiscContextMenu(n.id, e)}
            onClick={(e) => onDiscClick(n.id, e)}
          >
            <span>{n.label}</span>
          </button>
        );
      })}

      <p className="drag-stage__hint">
        Right-click a disc to start — line follows the cursor. Left-click
        another disc to land; click empty space to cancel.
      </p>
    </div>
  );
}
