import { useState } from "react";
import type { EdgeKind } from "../../shared/edges/types";
import {
  containsGeometry,
  expressesGeometry,
  leadstoGeometry,
  neartoGeometry,
} from "../../primitives/edge/edgeGeometry";
import {
  DILATE_PRESETS,
  evaluateDilateCurve,
  useDilatePlayback,
  type DilateCurveParams,
} from "../../shared/motion/dilateCurve";
import "./EdgeDilateLabPage.css";

const KINDS: EdgeKind[] = ["NEARTO", "LEADSTO", "EXPRESSES", "CONTAINS"];

const STAGE_W = 640;
const STAGE_H = 140;
const NODE_R = 36;
const LEFT = { x: 100, y: STAGE_H / 2 };
const RIGHT = { x: 540, y: STAGE_H / 2 };
const THIN = 0.35;
const FIRM = 1.75;
const DILATE_MS = 900;
const ORNAMENT_LAG = 0.08;

function ends() {
  const dx = RIGHT.x - LEFT.x;
  const dy = RIGHT.y - LEFT.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  return {
    sx: LEFT.x + ux * NODE_R,
    sy: LEFT.y + uy * NODE_R,
    tx: RIGHT.x - ux * NODE_R,
    ty: RIGHT.y - uy * NODE_R,
  };
}

function EdgeDilateRow({
  kind,
  curve,
}: {
  kind: EdgeKind;
  curve: DilateCurveParams;
}) {
  const { t, playing, play } = useDilatePlayback(DILATE_MS);
  const value = evaluateDilateCurve(t, curve);
  const ornamentValue = evaluateDilateCurve(Math.max(0, t - ORNAMENT_LAG), curve);

  const idle = t === 0 && !playing;
  const done = t >= 1 && !playing;
  const phase = idle ? "idle" : playing ? "dilating" : done ? "firm" : "thin";

  const width = THIN + (FIRM - THIN) * Math.min(1.3, Math.max(0, value));
  const ornament = Math.min(1, Math.max(0, ornamentValue));

  const { sx, sy, tx, ty } = ends();
  let linePath = `M ${sx},${sy} L ${tx},${ty}`;
  let parenPath: string | undefined;
  let dash: string | undefined;

  if (kind === "CONTAINS") {
    const g = containsGeometry({
      sx,
      sy,
      tx,
      ty,
      targetRadius: NODE_R,
      targetCenter: RIGHT,
    });
    linePath = g.linePath;
    parenPath = g.parenPath;
  } else if (kind === "LEADSTO") {
    linePath = leadstoGeometry({ sx, sy, tx, ty }).linePath;
  } else if (kind === "EXPRESSES") {
    const g = expressesGeometry({ sx, sy, tx, ty });
    linePath = g.linePath;
    dash = g.dash;
  } else {
    linePath = neartoGeometry({ sx, sy, tx, ty }).linePath;
  }

  const showFirmDash = phase === "firm" || ornament > 0.55;
  const markerOpacity =
    kind === "LEADSTO" ? Math.max(0, (ornament - 0.35) / 0.65) : 0;
  const parenOpacity =
    kind === "CONTAINS" ? Math.max(0, (ornament - 0.25) / 0.75) : 0;

  const markerId = `dilate-arrow-${kind}`;

  return (
    <section className="edge-dilate__row">
      <header className="edge-dilate__row-head">
        <h2>{kind}</h2>
        <button type="button" onClick={() => play()} disabled={playing}>
          {playing ? "Dilating…" : "Play dilate"}
        </button>
        <span className="edge-dilate__phase">{phase}</span>
      </header>
      <svg
        className="edge-dilate__stage"
        viewBox={`0 0 ${STAGE_W} ${STAGE_H}`}
        width="100%"
        height={STAGE_H}
        aria-hidden
      >
        <defs>
          <marker
            id={markerId}
            markerWidth="10"
            markerHeight="10"
            refX="8"
            refY="3"
            orient="auto"
            markerUnits="strokeWidth"
          >
            <path
              d="M0,0 L0,6 L9,3 z"
              fill="var(--ink)"
              opacity={markerOpacity}
            />
          </marker>
        </defs>

        <circle
          cx={LEFT.x}
          cy={LEFT.y}
          r={NODE_R}
          className="edge-dilate__disc"
        />
        <circle
          cx={RIGHT.x}
          cy={RIGHT.y}
          r={NODE_R}
          className="edge-dilate__disc"
        />
        <text x={LEFT.x} y={LEFT.y + 4} className="edge-dilate__label">
          A
        </text>
        <text x={RIGHT.x} y={RIGHT.y + 4} className="edge-dilate__label">
          B
        </text>

        <path
          d={linePath}
          fill="none"
          stroke="var(--ink)"
          strokeWidth={width}
          strokeLinecap={
            kind === "EXPRESSES" && showFirmDash ? "round" : "square"
          }
          strokeDasharray={
            kind === "EXPRESSES" && showFirmDash ? dash : undefined
          }
          markerEnd={
            kind === "LEADSTO" && markerOpacity > 0.05
              ? `url(#${markerId})`
              : undefined
          }
          opacity={idle ? 0.25 : 1}
        />

        {parenPath && (
          <path
            d={parenPath}
            fill="none"
            stroke="var(--ink)"
            strokeWidth={Math.max(THIN, width * 0.95)}
            strokeLinecap="square"
            opacity={parenOpacity}
          />
        )}
      </svg>
    </section>
  );
}

export function EdgeDilateLabPage() {
  const [presetId, setPresetId] = useState(DILATE_PRESETS[0].id);
  const preset =
    DILATE_PRESETS.find((p) => p.id === presetId) ?? DILATE_PRESETS[0];

  return (
    <div className="edge-dilate">
      <header className="edge-dilate__chrome">
        <p className="edge-dilate__eyebrow">Design lab</p>
        <h1 className="edge-dilate__title">Edge dilate</h1>
        <p className="edge-dilate__lede">
          Drag-connection look as a hairline, then a dilation into each typed
          edge — a held beat of tension, then a release that slightly
          overshoots the final weight before settling. Ornaments (arrow,
          dots, CONTAINS paren) bloom on the same curve, lagged.
        </p>
        <div className="edge-dilate__presets">
          {DILATE_PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              className={
                "edge-dilate__preset-btn" +
                (p.id === presetId ? " edge-dilate__preset-btn--active" : "")
              }
              onClick={() => setPresetId(p.id)}
              title={p.hint}
            >
              {p.label}
            </button>
          ))}
        </div>
        <p className="edge-dilate__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/curve-lab">Curve lab</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/edges">Edge forms</a>
          <span aria-hidden> · </span>
          <a href="#/">Field</a>
        </p>
      </header>

      {KINDS.map((kind) => (
        <EdgeDilateRow key={kind} kind={kind} curve={preset.params} />
      ))}
    </div>
  );
}
