import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { motion, AnimatePresence } from "motion/react";
import type { CSSProperties } from "react";
import type { TrialMassData } from "../data/trialGraph";
import { MASS_NODE_RADIUS, MASS_NODE_SIZE } from "../data/trialGraph";
import { membraneStatus } from "../../lab/membrane/membraneDefaults";
import { useTrialUi } from "../TrialUiContext";
import { NoiseMassBody } from "./NoiseMassBody";
import "./MassNode.css";

export type MassFlowNode = Node<TrialMassData, "mass">;

function VerdictMark({
  verdict,
}: {
  verdict: TrialMassData["verdict"];
}) {
  // CONFORMS is the quiet default — no special graph mark
  if (!verdict || verdict === "CONFORMS") return null;

  // UNGOVERNED: empty firm square (flat absence of rule)
  // INSUFFICIENT: incomplete open path (poised / can't tell) — must stay distinct
  return (
    <svg className="mass-node__verdict" viewBox="0 0 24 24" aria-hidden>
      {verdict === "VIOLATES" && (
        <path
          d="M6 6 L18 18 M18 6 L6 18"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="square"
        />
      )}
      {verdict === "UNGOVERNED" && (
        <rect
          x="5"
          y="5"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      )}
      {verdict === "INSUFFICIENT" && (
        <path
          d="M5 7 L5 17 L12 17"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="square"
        />
      )}
    </svg>
  );
}

/**
 * Centre of mass + certainty field + captured orbiters.
 */
export function MassNode({ id, data }: NodeProps<MassFlowNode>) {
  const { reducedMotion, accretingOrbiterId, onAccretionDone } = useTrialUi();
  const lifecycle = data.lifecycle ?? "alive";
  const show = lifecycle !== "dying";
  const status = membraneStatus(data.certainty);
  const uncertain = status !== "settled";

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="mass-node"
          data-node-id={id}
          style={{ width: MASS_NODE_SIZE, height: MASS_NODE_SIZE }}
          initial={
            lifecycle === "birthing"
              ? { scale: 0.15, opacity: 0 }
              : false
          }
          animate={{ scale: 1, opacity: 1 }}
          exit={
            reducedMotion
              ? { opacity: 0 }
              : { opacity: 0, scale: 0.12 }
          }
          transition={
            reducedMotion
              ? { duration: 0 }
              : { type: "spring", stiffness: 160, damping: 20 }
          }
        >
          <Handle
            type="target"
            position={Position.Left}
            id={`central-target-${id}`}
            className="mass-node__handle"
            style={centerHandleStyle}
          />

          {/* No drawn orbit rings — belonging is proximity only (refined orbiter rule) */}

          <div className="mass-node__orbiters">
            {(data.orbiters ?? []).map((o) => {
              const accreting = accretingOrbiterId === o.id;
              if (accreting) {
                return (
                  <motion.div
                    key={o.id}
                    className="mass-node__orbiter mass-node__orbiter--accreting"
                    initial={{
                      x: Math.cos((o.angle * Math.PI) / 180) * o.radius,
                      y: Math.sin((o.angle * Math.PI) / 180) * o.radius,
                      scale: 1,
                      opacity: 1,
                    }}
                    animate={{ x: 0, y: 0, scale: 0.3, opacity: 0 }}
                    transition={
                      reducedMotion
                        ? { duration: 0 }
                        : { type: "spring", stiffness: 110, damping: 16 }
                    }
                    onAnimationComplete={() => onAccretionDone(o.id)}
                  />
                );
              }

              if (reducedMotion) {
                const x = Math.cos((o.angle * Math.PI) / 180) * o.radius;
                const y = Math.sin((o.angle * Math.PI) / 180) * o.radius;
                return (
                  <div
                    key={o.id}
                    className="mass-node__orbiter"
                    style={{ transform: `translate(${x}px, ${y}px)` }}
                    title={o.label}
                  />
                );
              }

              const duration = Math.max(4, Math.abs(360 / o.speed));
              return (
                <div
                  key={o.id}
                  className="mass-node__orbit-track"
                  style={{
                    width: o.radius * 2,
                    height: o.radius * 2,
                    marginLeft: -o.radius,
                    marginTop: -o.radius,
                    animationDuration: `${duration}s`,
                    animationDirection: o.speed < 0 ? "reverse" : "normal",
                  }}
                >
                  <div
                    className="mass-node__orbiter"
                    style={{ transform: `translate(${o.radius}px, 0)` }}
                    title={o.label}
                  />
                </div>
              );
            })}
          </div>

          {uncertain && (
            <NoiseMassBody
              nodeId={id}
              certainty={data.certainty}
              radius={MASS_NODE_RADIUS}
              reducedMotion={reducedMotion}
            />
          )}

          <div
            className={
              uncertain
                ? "mass-node__face mass-node__face--noise"
                : "mass-node__face"
            }
          >
            <p className="mass-node__label">{data.label}</p>
            <VerdictMark verdict={data.verdict} />
          </div>

          <Handle
            type="source"
            position={Position.Right}
            id={`central-source-${id}`}
            className="mass-node__handle"
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
