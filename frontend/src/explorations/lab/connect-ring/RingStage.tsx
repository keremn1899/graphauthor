import { useCallback, useEffect, useRef, useState } from "react";
import { ReachTether } from "../../../field/gestures/ReachTether";
import { ProximityRing } from "./ProximityRing";
import {
  LONG_PRESS_MS,
  NODE_R,
  RING_R,
  boundaryPoint,
  chordEnds,
  inAnnulus,
  inDisc,
} from "./constants";
import "./RingStage.css";

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
  /** Locked rim endpoints — identical to the settled tether */
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

type Phase = "idle" | "armed" | "dragging" | "landing";

const NODES: LabNode[] = [
  { id: "a", label: "Source A", x: 220, y: 260 },
  { id: "b", label: "Target B", x: 520, y: 180 },
  { id: "c", label: "Target C", x: 520, y: 360 },
];

type RingStageProps = {
  reducedMotion: boolean;
  onLog: (msg: string) => void;
};

export function RingStage({ reducedMotion, onLog }: RingStageProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [armedId, setArmedId] = useState<string | null>(null);
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

  const pressTimer = useRef<number | null>(null);
  const pressMeta = useRef<{
    nodeId: string;
    clientX: number;
    clientY: number;
  } | null>(null);
  const dragSourceId = useRef<string | null>(null);
  const landRaf = useRef<number | null>(null);
  const fallbackTimer = useRef<number | null>(null);
  const landingRef = useRef(landing);
  const landSlackRef = useRef(landSlack);
  const awaitingRestRef = useRef(false);
  const lockedRef = useRef(false);

  landingRef.current = landing;
  landSlackRef.current = landSlack;

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

  const findNodeInAnnulus = useCallback((p: Point, exclude?: string) => {
    for (const n of NODES) {
      if (n.id === exclude) continue;
      if (inAnnulus({ x: n.x, y: n.y }, p)) return n;
    }
    return null;
  }, []);

  const findValidTarget = useCallback((p: Point, exclude?: string) => {
    for (const n of NODES) {
      if (n.id === exclude) continue;
      const c = { x: n.x, y: n.y };
      if (inAnnulus(c, p) || inDisc(c, p)) return n;
    }
    return null;
  }, []);

  const clearPress = () => {
    if (pressTimer.current) {
      window.clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
    pressMeta.current = null;
  };

  const disarm = useCallback(() => {
    cancelLandAnim();
    setArmedId(null);
    setPhase("idle");
    setHoverTargetId(null);
    setPointer(null);
    dragSourceId.current = null;
    setLanding(null);
    setLandSlack(0);
  }, [cancelLandAnim]);

  const arm = useCallback(
    (nodeId: string) => {
      setArmedId(nodeId);
      setPhase("armed");
      setHoverTargetId(null);
      setLanding(null);
      onLog(
        `Armed ${nodeId} — drag from the grey ring (between ring and border).`,
      );
    },
    [onLog],
  );

  /**
   * Promote settled tether → firm edge with one-frame overlap so nothing pops.
   * Endpoints are snapshotted from the landing tether — identical pixels.
   */
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
          targetId: targetId,
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
        setPhase("idle");
        dragSourceId.current = null;
        onLog(`Firm edge ${srcId} → ${targetId} (NEARTO stub).`);
      });
    },
    [onLog],
  );

  const onStagePointerDown = (e: React.PointerEvent) => {
    if (phase === "dragging" || phase === "landing") return;
    if (e.button === 2) return;

    const p = localPoint(e.clientX, e.clientY);
    const hit = findNodeInAnnulus(p);
    if (!hit) {
      if (armedId) {
        disarm();
        onLog("Disarmed.");
      }
      return;
    }

    clearPress();
    pressMeta.current = {
      nodeId: hit.id,
      clientX: e.clientX,
      clientY: e.clientY,
    };
    pressTimer.current = window.setTimeout(() => {
      pressMeta.current = null;
      pressTimer.current = null;
      arm(hit.id);
    }, LONG_PRESS_MS);
  };

  const onStageContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    if (phase === "dragging" || phase === "landing") return;
    const p = localPoint(e.clientX, e.clientY);
    const hit = findNodeInAnnulus(p);
    if (!hit) {
      disarm();
      return;
    }
    arm(hit.id);
  };

  const onStagePointerMove = (e: React.PointerEvent) => {
    const meta = pressMeta.current;
    if (pressTimer.current && meta) {
      if (
        Math.hypot(e.clientX - meta.clientX, e.clientY - meta.clientY) > 10
      ) {
        clearPress();
      }
    }

    if (phase !== "dragging") return;
    const p = localPoint(e.clientX, e.clientY);
    setPointer(p);
    const src = dragSourceId.current;
    if (!src) return;
    setHoverTargetId(findValidTarget(p, src)?.id ?? null);
  };

  const finishDrag = useCallback(
    (clientX: number, clientY: number) => {
      const srcId = dragSourceId.current;
      if (!srcId) {
        disarm();
        return;
      }
      const src = NODES.find((n) => n.id === srcId)!;
      const p = localPoint(clientX, clientY);
      const target = findValidTarget(p, srcId);

      if (!target) {
        onLog("Miss — reach withdrew.");
        disarm();
        return;
      }

      const { from, to } = chordEnds(
        { x: src.x, y: src.y },
        { x: target.x, y: target.y },
      );

      // Instant firm edge — no land / taut animation in this lab
      cancelLandAnim();
      setArmedId(null);
      setHoverTargetId(target.id);
      onLog(`Connected ${srcId} → ${target.id}.`);
      commitFirm(srcId, target.id, from, to);
    },
    [
      cancelLandAnim,
      commitFirm,
      disarm,
      findValidTarget,
      localPoint,
      onLog,
    ],
  );

  const onAnnulusPointerDown = (nodeId: string, e: React.PointerEvent) => {
    if (e.button === 2) return;
    if (armedId !== nodeId) return;
    e.stopPropagation();
    e.preventDefault();
    clearPress();
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    dragSourceId.current = nodeId;
    setPhase("dragging");
    setPointer(localPoint(e.clientX, e.clientY));
    onLog(`Dragging from ${nodeId}…`);
  };

  useEffect(() => {
    if (phase !== "dragging") return;
    const onUp = (e: PointerEvent) => finishDrag(e.clientX, e.clientY);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [phase, finishDrag]);

  useEffect(
    () => () => {
      clearPress();
      cancelLandAnim();
    },
    [cancelLandAnim],
  );

  const tetherSource =
    phase === "dragging" || phase === "landing"
      ? NODES.find((n) => n.id === (dragSourceId.current ?? landing?.sourceId))
      : null;

  let tetherFrom: Point | null = null;
  let tetherTo: Point | null = null;
  let slack = 0;
  let tetherImmediate = false;

  if (phase === "landing" && landing) {
    tetherFrom = landing.from;
    tetherTo = landing.to;
    slack = landSlack;
    tetherImmediate = false;
  } else if (phase === "dragging" && tetherSource && pointer) {
    const hover = hoverTargetId
      ? NODES.find((n) => n.id === hoverTargetId)
      : null;
    if (hover) {
      // Snap to final rim↔rim chord while over target — land has nowhere to jump
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

  const freezeRingMotion = phase === "dragging" || phase === "landing";

  return (
    <div
      ref={stageRef}
      className="ring-stage"
      onPointerDown={onStagePointerDown}
      onPointerMove={onStagePointerMove}
      onPointerUp={() => clearPress()}
      onContextMenu={onStageContextMenu}
    >
      <svg className="ring-stage__edges" aria-hidden>
        {firmEdges.map((e) => (
          <line
            key={e.id}
            x1={e.x1}
            y1={e.y1}
            x2={e.x2}
            y2={e.y2}
            className="ring-stage__firm"
          />
        ))}
      </svg>

      {tetherFrom && tetherTo && (
        <div className="ring-stage__tether">
          <ReachTether
            x1={tetherFrom.x}
            y1={tetherFrom.y}
            x2={tetherTo.x}
            y2={tetherTo.y}
            slack={slack}
            reducedMotion={reducedMotion}
            immediate={tetherImmediate}
          />
        </div>
      )}

      {NODES.map((n) => {
        const showRing =
          armedId === n.id ||
          (phase === "dragging" && dragSourceId.current === n.id) ||
          hoverTargetId === n.id ||
          (landing &&
            (landing.sourceId === n.id || landing.targetId === n.id));
        const hitEnabled = phase === "armed" && armedId === n.id;

        return (
          <div key={n.id} className="ring-stage__node-wrap">
            <ProximityRing
              cx={n.x}
              cy={n.y}
              active={!!showRing}
              hitEnabled={hitEnabled}
              reducedMotion={reducedMotion}
              instant={freezeRingMotion}
              onAnnulusPointerDown={(e) => onAnnulusPointerDown(n.id, e)}
            />
            <div
              className="ring-stage__disc"
              style={{
                left: n.x - NODE_R,
                top: n.y - NODE_R,
                width: NODE_R * 2,
                height: NODE_R * 2,
              }}
              data-node-id={n.id}
            >
              <span>{n.label}</span>
            </div>
            <div
              className="ring-stage__near-hint"
              style={{
                left: n.x - RING_R,
                top: n.y - RING_R,
                width: RING_R * 2,
                height: RING_R * 2,
              }}
              aria-hidden
            />
          </div>
        );
      })}

      <p className="ring-stage__hint">
        Right-click (or long-press) in the band outside a disc → grey ring →
        drag from the ring band to another node&apos;s band → release.
      </p>
    </div>
  );
}
