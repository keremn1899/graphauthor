import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import {
  Handle,
  Position,
  useStore,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  NODE_R,
  RING_R,
  annulusClipPath,
} from "../connect-ring/constants";
import "./NoteRingNode.css";

export const NOTE_DISC_SIZE = NODE_R * 2;

export type NoteRingData = {
  label: string;
};

export type NoteRingFlowNode = Node<NoteRingData, "noteRing">;

const LONG_PRESS_MS = 400;

/**
 * Note Prototype connect model:
 * right-click / long-press → ring → annulus Handle starts RF connection.
 * Ring show/hide is instant (no fade/scale anim).
 */
export function NoteRingNode({ id, data, dragging }: NodeProps<NoteRingFlowNode>) {
  const connectionNodeId = useStore(
    useCallback((s) => s.connection?.fromHandle?.nodeId ?? null, []),
  );
  const isConnecting = !!connectionNodeId;
  const isConnectingFromMe = connectionNodeId === id;
  const isTarget = isConnecting && !isConnectingFromMe;

  const [isRightClicked, setIsRightClicked] = useState(false);
  const [isLongPressed, setIsLongPressed] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const longPressTimerRef = useRef<number | null>(null);
  const pressOrigin = useRef<{ x: number; y: number } | null>(null);

  const isRingActive = isRightClicked || isLongPressed || isConnectingFromMe;

  const wasConnectingRef = useRef(false);
  useEffect(() => {
    if (wasConnectingRef.current && !isConnectingFromMe) {
      setIsRightClicked(false);
      setIsLongPressed(false);
    }
    wasConnectingRef.current = isConnectingFromMe;
  }, [isConnectingFromMe]);

  useEffect(() => {
    if (dragging) {
      setIsRightClicked(false);
      setIsLongPressed(false);
    }
  }, [dragging]);

  useEffect(() => {
    const handler = (e: Event) => {
      if ((e as CustomEvent).detail !== id) {
        setIsRightClicked(false);
        setIsLongPressed(false);
      }
    };
    window.addEventListener("ring-activate", handler);
    return () => window.removeEventListener("ring-activate", handler);
  }, [id]);

  const clearLongPress = () => {
    if (longPressTimerRef.current != null) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    pressOrigin.current = null;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button === 2) return;
    clearLongPress();
    pressOrigin.current = { x: e.clientX, y: e.clientY };
    longPressTimerRef.current = window.setTimeout(() => {
      setIsLongPressed(true);
      window.dispatchEvent(new CustomEvent("ring-activate", { detail: id }));
    }, LONG_PRESS_MS);
  };

  const onPointerUp = () => {
    clearLongPress();
    window.setTimeout(() => setIsLongPressed(false), 300);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const o = pressOrigin.current;
    if (!o || longPressTimerRef.current == null) return;
    if (Math.hypot(e.clientX - o.x, e.clientY - o.y) > 10) {
      clearLongPress();
    }
  };

  const onPointerCancel = () => {
    clearLongPress();
    setIsLongPressed(false);
  };

  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsRightClicked((prev) => {
      const next = !prev;
      if (next) {
        window.dispatchEvent(new CustomEvent("ring-activate", { detail: id }));
      }
      return next;
    });
  };

  useEffect(() => {
    if (!isRightClicked) return;
    const dismiss = (e: MouseEvent) => {
      if (wrapperRef.current?.contains(e.target as globalThis.Node)) return;
      setIsRightClicked(false);
    };
    window.addEventListener("click", dismiss);
    return () => window.removeEventListener("click", dismiss);
  }, [isRightClicked]);

  useEffect(() => () => clearLongPress(), []);

  const ringBox = RING_R * 2;

  return (
    <div
      ref={wrapperRef}
      className={[
        "note-ring-node",
        isTarget ? "note-ring-node--target" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-node-id={id}
      style={{ width: NOTE_DISC_SIZE, height: NOTE_DISC_SIZE }}
      onContextMenu={onContextMenu}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerMove={onPointerMove}
      onPointerCancel={onPointerCancel}
    >
      <svg
        className="note-ring-node__ring"
        viewBox={`0 0 ${ringBox} ${ringBox}`}
        aria-hidden
      >
        <circle
          cx={RING_R}
          cy={RING_R}
          r={RING_R}
          className={[
            "note-ring-node__ring-circle",
            isRingActive ? "note-ring-node__ring-circle--active" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        />
        <circle
          cx={RING_R}
          cy={RING_R}
          r={NODE_R}
          fill="var(--canvas)"
          stroke="none"
        />
      </svg>

      <Handle
        type="source"
        position={Position.Right}
        id={`central-source-${id}`}
        className="note-ring-node__handle"
        style={centerHandleStyle}
        isConnectable={!!isRingActive}
      >
        <div
          className="note-ring-node__hit"
          style={{
            width: ringBox,
            height: ringBox,
            pointerEvents: isRingActive ? "all" : "none",
            clipPath: annulusClipPath(RING_R, NODE_R),
          }}
          onClick={(e) => e.stopPropagation()}
        />
      </Handle>

      <Handle
        type="target"
        position={Position.Left}
        id={`central-target-${id}`}
        className="note-ring-node__handle"
        style={{ ...centerHandleStyle, zIndex: 0 }}
        isConnectable={false}
      />

      <div className="note-ring-node__face">
        <span>{data.label}</span>
      </div>
    </div>
  );
}

const centerHandleStyle: CSSProperties = {
  position: "absolute",
  top: "50%",
  left: "50%",
  transform: "translate(-50%, -50%)",
  width: 1,
  height: 1,
  opacity: 0,
  right: "auto",
  bottom: "auto",
  borderRadius: "50%",
  pointerEvents: "none",
  zIndex: 10,
  background: "transparent",
  border: "none",
  overflow: "visible",
  minWidth: 0,
  minHeight: 0,
};
