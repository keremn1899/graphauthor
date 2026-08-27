import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { motion, AnimatePresence } from "motion/react";
import type { CSSProperties } from "react";
import type { ConceptData } from "../data/fieldGraph";
import { CONCEPT_NODE_SIZE } from "../data/fieldGraph";
import { useFieldUi } from "../state/FieldUiContext";
import "./ConceptNode.css";

export type ConceptFlowNode = Node<ConceptData, "concept">;

export function ConceptNode({ id, data }: NodeProps<ConceptFlowNode>) {
  const { reducedMotion, selectedId, provisionalPreviewId, markRead } =
    useFieldUi();
  const lifecycle = data.lifecycle ?? "alive";
  const show = lifecycle !== "dying";
  const selected = selectedId === id;
  const provisional = provisionalPreviewId === id;
  const unread = !!data.unread;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className={[
            "concept-node",
            selected ? "concept-node--selected" : "",
            provisional ? "concept-node--provisional" : "",
            unread ? "concept-node--unread" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          data-node-id={id}
          style={{ width: CONCEPT_NODE_SIZE, height: CONCEPT_NODE_SIZE }}
          initial={
            lifecycle === "birthing"
              ? { scale: 0.12, opacity: 0 }
              : false
          }
          animate={
            data.pulseToken
              ? { scale: [1, 1.08, 1], opacity: 1 }
              : { scale: 1, opacity: 1 }
          }
          exit={
            reducedMotion
              ? { opacity: 0 }
              : { opacity: 0, scale: 0.12 }
          }
          transition={
            reducedMotion
              ? { duration: 0 }
              : data.pulseToken
                ? { duration: 0.45, times: [0, 0.4, 1] }
                : { type: "spring", stiffness: 160, damping: 20 }
          }
          key={data.pulseToken ? `pulse-${data.pulseToken}` : id}
        >
          <Handle
            type="target"
            position={Position.Left}
            id={`central-target-${id}`}
            className="concept-node__handle"
            style={centerHandleStyle}
          />

          <div
            className="concept-node__body"
            onDoubleClick={(e) => {
              e.stopPropagation();
              if (unread) markRead(id);
            }}
          >
            {provisional && (
              <span className="concept-node__concentric" aria-hidden />
            )}
            <p className="concept-node__label">{data.label}</p>
            {unread && (
              <button
                type="button"
                className="concept-node__unread"
                aria-label="Mark as read"
                onClick={(e) => {
                  e.stopPropagation();
                  markRead(id);
                }}
              />
            )}
          </div>

          <Handle
            type="source"
            position={Position.Right}
            id={`central-source-${id}`}
            className="concept-node__handle"
            style={centerHandleStyle}
          />
        </motion.div>
      )}
    </AnimatePresence>
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
  pointerEvents: "none",
  border: "none",
  minWidth: 0,
  minHeight: 0,
};
