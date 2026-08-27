import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import type { EdgeKind } from "../../../primitives/edge/types";
import {
  containsGeometry,
  leadstoGeometry,
  expressesGeometry,
  neartoGeometry,
} from "../../../primitives/edge/edgeGeometry";
import { TypePicker } from "./TypePicker";
import {
  LONG_PRESS_MS,
  type GesturePhase,
  type InitMode,
  type TypeTiming,
} from "./types";
import "./ConnectStage.css";

type Point = { x: number; y: number };

type ConnectStageProps = {
  initMode: InitMode;
  typeTiming: TypeTiming;
  reducedMotion: boolean;
  onLog: (msg: string) => void;
};

const NODE_R = 52;
const REACH_LEN = 112;

function nodeCenter(
  stage: DOMRect,
  el: HTMLElement | null,
): Point | null {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {
    x: r.left - stage.left + r.width / 2,
    y: r.top - stage.top + r.height / 2,
  };
}

function dist(a: Point, b: Point) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function unitToward(from: Point, to: Point) {
  const d = dist(from, to) || 1;
  return { ux: (to.x - from.x) / d, uy: (to.y - from.y) / d };
}

/** Smooth slack bridge from A toward B (uncertainty = unsettled path). */
function wobblyPath(
  a: Point,
  b: Point,
  t: number,
  reducedMotion: boolean,
): string {
  if (reducedMotion) {
    return `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
  }
  const { ux, uy } = unitToward(a, b);
  const px = -uy;
  const py = ux;
  const amp = 6 * Math.sin(t / 170);
  const amp2 = 4 * Math.sin(t / 130 + 1.4);
  const c1 = {
    x: a.x + (b.x - a.x) * 0.34 + px * amp,
    y: a.y + (b.y - a.y) * 0.34 + py * amp,
  };
  const c2 = {
    x: a.x + (b.x - a.x) * 0.68 - px * amp2,
    y: a.y + (b.y - a.y) * 0.68 - py * amp2,
  };
  return `M ${a.x} ${a.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${b.x} ${b.y}`;
}

function boundaryPoint(center: Point, toward: Point, radius = NODE_R): Point {
  const { ux, uy } = unitToward(center, toward);
  return { x: center.x + ux * radius, y: center.y + uy * radius };
}

export function ConnectStage({
  initMode,
  typeTiming,
  reducedMotion,
  onLog,
}: ConnectStageProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLDivElement>(null);
  const decoyRef = useRef<HTMLDivElement>(null);

  const [phase, setPhase] = useState<GesturePhase>("idle");
  const [pointer, setPointer] = useState<Point | null>(null);
  const [sourcePt, setSourcePt] = useState<Point | null>(null);
  const [hoverValid, setHoverValid] = useState(false);
  const [firmEdge, setFirmEdge] = useState<{
    a: Point;
    b: Point;
    kind: EdgeKind | null;
  } | null>(null);
  const [preType, setPreType] = useState<EdgeKind | null>(null);
  const [tick, setTick] = useState(0);

  const pressTimer = useRef<number | null>(null);
  const activePointer = useRef<number | null>(null);
  const pressStart = useRef<Point | null>(null);

  useEffect(() => {
    if (phase !== "reaching" && phase !== "dragging" && phase !== "hover-valid") {
      return;
    }
    if (reducedMotion) return;
    let raf = 0;
    const loop = (t: number) => {
      setTick(t);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [phase, reducedMotion]);

  const clearPress = () => {
    if (pressTimer.current) {
      window.clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
  };

  const beginReach = useCallback(
    (origin: Point) => {
      setSourcePt(origin);
      setPointer({
        x: origin.x + REACH_LEN,
        y: origin.y,
      });
      setPhase("reaching");
      setFirmEdge(null);
      onLog("Reach extended — uncertain bridge (wobbly). Drag toward a mass.");
    },
    [onLog],
  );

  const tryInitiate = useCallback(
    (clientX: number, clientY: number, from: "press" | "context") => {
      const stage = stageRef.current?.getBoundingClientRect();
      const src = sourceRef.current;
      if (!stage || !src) return;

      const center = nodeCenter(stage, src);
      if (!center) return;

      const local = { x: clientX - stage.left, y: clientY - stage.top };
      const d = dist(local, center);

      if (initMode === "on-node") {
        if (d > NODE_R + 8) {
          onLog("On-node mode: initiate on the source mass.");
          return;
        }
      } else {
        // near-node: directional reach zone outside the source's east boundary
        if (
          local.x < center.x + NODE_R - 8 ||
          local.x > center.x + NODE_R + 72 ||
          Math.abs(local.y - center.y) > 48
        ) {
          onLog("Near-node mode: initiate from the reach zone beside the source.");
          return;
        }
      }

      if (typeTiming === "before-drag" && !preType) {
        onLog("Pre-select an edge type, then initiate the reach.");
        return;
      }

      beginReach(center);
      onLog(
        from === "context"
          ? "Right-click reach (desktop). Prefer long-press on touch."
          : "Long-press reach — field extending outward (not an orbit).",
      );
    },
    [beginReach, initMode, onLog, preType, typeTiming],
  );

  const onSourcePointerDown = (e: React.PointerEvent) => {
    if (e.button === 2) return; // contextmenu handles right-click
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    activePointer.current = e.pointerId;
    pressStart.current = { x: e.clientX, y: e.clientY };
    clearPress();
    pressTimer.current = window.setTimeout(() => {
      tryInitiate(e.clientX, e.clientY, "press");
    }, LONG_PRESS_MS);
  };

  const onNearRingPointerDown = (e: React.PointerEvent) => {
    if (initMode !== "near-node") return;
    e.stopPropagation();
    activePointer.current = e.pointerId;
    pressStart.current = { x: e.clientX, y: e.clientY };
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    clearPress();
    pressTimer.current = window.setTimeout(() => {
      tryInitiate(e.clientX, e.clientY, "press");
    }, LONG_PRESS_MS);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (pressTimer.current && activePointer.current === e.pointerId) {
      const start = pressStart.current;
      if (
        start &&
        Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10
      ) {
        clearPress();
        pressStart.current = null;
        activePointer.current = null;
      }
    }

    if (
      phase !== "reaching" &&
      phase !== "dragging" &&
      phase !== "hover-valid"
    ) {
      return;
    }

    const stage = stageRef.current?.getBoundingClientRect();
    if (!stage) return;
    const p = { x: e.clientX - stage.left, y: e.clientY - stage.top };
    setPointer(p);
    setPhase("dragging");

    const target = nodeCenter(stage, targetRef.current);
    const decoy = nodeCenter(stage, decoyRef.current);
    let valid = false;
    if (target && dist(p, target) < NODE_R + 28) valid = true;
    if (decoy && dist(p, decoy) < NODE_R + 28) valid = false; // decoy never valid
    setHoverValid(valid);
    setPhase(valid ? "hover-valid" : "dragging");
  };

  const onPointerUp = (e: React.PointerEvent) => {
    clearPress();
    pressStart.current = null;
    if (
      phase !== "reaching" &&
      phase !== "dragging" &&
      phase !== "hover-valid"
    ) {
      activePointer.current = null;
      return;
    }

    const stage = stageRef.current?.getBoundingClientRect();
    if (!stage || !sourcePt) {
      setPhase("idle");
      return;
    }

    const p = { x: e.clientX - stage.left, y: e.clientY - stage.top };
    const target = nodeCenter(stage, targetRef.current);
    const decoy = nodeCenter(stage, decoyRef.current);

    if (decoy && dist(p, decoy) < NODE_R + 28) {
      onLog("Invalid target — no field response. Bridge cancelled.");
      setPhase("idle");
      setPointer(null);
      setHoverValid(false);
      return;
    }

    if (target && dist(p, target) < NODE_R + 28) {
      // Land on circumference toward source
      const { ux, uy } = unitToward(target, sourcePt);
      const land: Point = {
        x: target.x + ux * NODE_R,
        y: target.y + uy * NODE_R,
      };
      const from: Point = {
        x: sourcePt.x - ux * NODE_R,
        y: sourcePt.y - uy * NODE_R,
      };

      if (typeTiming === "before-drag" && preType) {
        setFirmEdge({ a: from, b: land, kind: preType });
        setPhase("landed");
        onLog(`Landed taut — ${preType}. Uncertain → certain.`);
      } else {
        setFirmEdge({ a: from, b: land, kind: null });
        setPhase("picking-type");
        onLog("Landed. Pick the edge type (after-landing).");
      }
      setPointer(null);
      setHoverValid(false);
      return;
    }

    onLog("Released in empty space — reach withdrew.");
    setPhase("idle");
    setPointer(null);
    setHoverValid(false);
  };

  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    tryInitiate(e.clientX, e.clientY, "context");
  };

  const onPickType = (kind: EdgeKind) => {
    if (phase === "picking-type" && firmEdge) {
      setFirmEdge({ ...firmEdge, kind });
      setPhase("landed");
      onLog(`Type resolved — ${kind}. Bridge is certain.`);
      return;
    }
    if (typeTiming === "before-drag") {
      setPreType(kind);
      onLog(`Pre-selected ${kind}. Long-press to reach.`);
    }
  };

  const reset = () => {
    clearPress();
    pressStart.current = null;
    setPhase("idle");
    setPointer(null);
    setSourcePt(null);
    setHoverValid(false);
    setFirmEdge(null);
    onLog("Reset.");
  };

  // Reach tip when idle-reaching (before drag)
  const reachTip =
    sourcePt && phase === "reaching" && pointer
      ? pointer
      : sourcePt
        ? {
            x: sourcePt.x + REACH_LEN,
            y: sourcePt.y,
          }
        : null;

  const dragEnd = pointer;
  const showWobble =
    sourcePt &&
    (phase === "reaching" ||
      phase === "dragging" ||
      phase === "hover-valid") &&
    (dragEnd || reachTip);

  const wobbleEnd =
    phase === "reaching" ? reachTip : dragEnd;
  const wobbleStart =
    sourcePt && wobbleEnd ? boundaryPoint(sourcePt, wobbleEnd) : null;
  const pickerPoint = firmEdge
    ? {
        x: (firmEdge.a.x + firmEdge.b.x) / 2,
        y: (firmEdge.a.y + firmEdge.b.y) / 2 + 68,
      }
    : null;
  const grabPoint =
    phase === "reaching"
      ? reachTip
      : phase === "dragging" || phase === "hover-valid"
        ? pointer
        : null;

  return (
    <div
      ref={stageRef}
      className="connect-stage"
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => {
        clearPress();
      }}
    >
      {/* Directional initiation zone: field reaching outward, never an orbit */}
      {initMode === "near-node" && phase === "idle" && (
        <div
          className="connect-stage__near-ring"
          onPointerDown={onNearRingPointerDown}
          onContextMenu={onContextMenu}
          aria-label="Near-node reach zone"
        >
          <span aria-hidden />
        </div>
      )}

      <div
        ref={sourceRef}
        className={[
          "connect-stage__node",
          "connect-stage__node--source",
          phase !== "idle" ? "connect-stage__node--active" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        onPointerDown={
          initMode === "on-node" ? onSourcePointerDown : undefined
        }
        onContextMenu={initMode === "on-node" ? onContextMenu : undefined}
        onPointerUp={clearPress}
        onPointerLeave={clearPress}
      >
        <span>Source</span>
      </div>

      <div
        ref={targetRef}
        className={[
          "connect-stage__node",
          "connect-stage__node--target",
          hoverValid ? "connect-stage__node--receiving" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <span>Target</span>
        {hoverValid && (
          <svg
            className="connect-stage__receive-ring"
            viewBox="0 0 120 120"
            aria-hidden
          >
            <path
              d="M 26 18 C 4 38, 4 82, 26 102"
              fill="none"
              stroke="var(--ink)"
              strokeWidth="2"
              opacity="0.72"
            />
          </svg>
        )}
      </div>

      <div ref={decoyRef} className="connect-stage__node connect-stage__node--decoy">
        <span>Invalid</span>
      </div>

      <svg className="connect-stage__svg" aria-hidden>
        {showWobble && wobbleStart && wobbleEnd && (
          <path
            d={wobblyPath(wobbleStart, wobbleEnd, tick, reducedMotion)}
            fill="none"
            stroke="var(--ink)"
            strokeWidth={1.75}
            strokeLinecap="square"
            opacity={reducedMotion ? 0.55 : 0.85}
          />
        )}

        {firmEdge && (
          <FirmEdge a={firmEdge.a} b={firmEdge.b} kind={firmEdge.kind} />
        )}
      </svg>

      {/* Large finger grab tip while reaching */}
      {grabPoint && (
        <motion.div
          className="connect-stage__grab"
          style={{ left: grabPoint.x, top: grabPoint.y }}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            setPhase("dragging");
          }}
        />
      )}

      {(phase === "picking-type" ||
        (typeTiming === "before-drag" && phase === "idle")) && (
        <div
          className={
            phase === "picking-type"
              ? "connect-stage__picker"
              : "connect-stage__picker connect-stage__picker--pre"
          }
          style={
            phase === "picking-type" && pickerPoint
              ? { left: pickerPoint.x, top: pickerPoint.y }
              : undefined
          }
        >
          <TypePicker onPick={onPickType} preselected={preType} />
        </div>
      )}

      <button type="button" className="connect-stage__reset" onClick={reset}>
        Reset
      </button>
    </div>
  );
}

function FirmEdge({
  a,
  b,
  kind,
}: {
  a: Point;
  b: Point;
  kind: EdgeKind | null;
}) {
  const sx = a.x;
  const sy = a.y;
  const tx = b.x;
  const ty = b.y;

  if (!kind) {
    return (
      <motion.path
        d={`M ${sx} ${sy} L ${tx} ${ty}`}
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.75}
        initial={{ pathLength: 0.84, opacity: 0.45 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.22, ease: "easeOut" }}
      />
    );
  }

  if (kind === "CONTAINS") {
    const g = containsGeometry({ sx, sy, tx, ty });
    return (
      <g>
        <path d={g.linePath} fill="none" stroke="var(--ink)" strokeWidth={1.75} />
        <path d={g.parenPath} fill="none" stroke="var(--ink)" strokeWidth={1.75} strokeLinecap="square" />
      </g>
    );
  }
  if (kind === "EXPRESSES") {
    const g = expressesGeometry({ sx, sy, tx, ty });
    return (
      <path
        d={g.linePath}
        fill="none"
        stroke="var(--ink)"
        strokeWidth={1.75}
        strokeDasharray={g.dash}
        strokeLinecap="round"
      />
    );
  }
  if (kind === "LEADSTO") {
    const g = leadstoGeometry({ sx, sy, tx, ty });
    const { ux, uy } = unitToward(a, b);
    const px = -uy;
    const py = ux;
    const ah = 10;
    const tip = { x: tx, y: ty };
    const base = { x: tx - ux * ah, y: ty - uy * ah };
    const arrow = `M ${tip.x} ${tip.y} L ${base.x + px * 5} ${base.y + py * 5} L ${base.x - px * 5} ${base.y - py * 5} Z`;
    return (
      <g>
        <path d={g.linePath} fill="none" stroke="var(--ink)" strokeWidth={1.75} />
        <path d={arrow} fill="var(--ink)" />
      </g>
    );
  }
  const g = neartoGeometry({ sx, sy, tx, ty });
  return (
    <path d={g.linePath} fill="none" stroke="var(--ink)" strokeWidth={1.75} />
  );
}
