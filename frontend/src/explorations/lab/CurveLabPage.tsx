import { useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_DILATE_PRESET,
  DILATE_PRESETS,
  evaluateDilateCurve,
  sampleDilateCurve,
  useDilatePlayback,
  type DilateCurveParams,
} from "../../shared/motion/dilateCurve";
import "./CurveLabPage.css";

const GRAPH_W = 320;
const GRAPH_H = 190;
const PAD_X = 18;
const PAD_Y = 18;

function mapX(t: number) {
  return PAD_X + t * (GRAPH_W - PAD_X * 2);
}

function mapY(v: number, vMin: number, vMax: number) {
  const span = vMax - vMin || 1;
  return GRAPH_H - PAD_Y - ((v - vMin) / span) * (GRAPH_H - PAD_Y * 2);
}

export function CurveLabPage() {
  const [presetId, setPresetId] = useState(DEFAULT_DILATE_PRESET.id);
  const [params, setParams] = useState<DilateCurveParams>({
    ...DEFAULT_DILATE_PRESET.params,
  });
  const [durationMs, setDurationMs] = useState(900);
  const [loop, setLoop] = useState(false);
  const [copied, setCopied] = useState(false);
  const { t, setT, playing, play, stop } = useDilatePlayback(durationMs);
  const prevPlayingRef = useRef(false);
  const overshotRef = useRef(false);

  useEffect(() => {
    if (prevPlayingRef.current && !playing && loop) {
      play();
    }
    prevPlayingRef.current = playing;
  }, [playing, loop, play]);

  function selectPreset(id: string) {
    const preset = DILATE_PRESETS.find((p) => p.id === id) ?? DEFAULT_DILATE_PRESET;
    stop();
    setT(0);
    setPresetId(id);
    setParams({ ...preset.params });
  }

  function resetToPreset() {
    const preset = DILATE_PRESETS.find((p) => p.id === presetId) ?? DEFAULT_DILATE_PRESET;
    setParams({ ...preset.params });
  }

  function setKind(kind: DilateCurveParams["kind"]) {
    setParams((p) => ({ ...p, kind }));
  }

  const value = evaluateDilateCurve(t, params);

  // "Shiver" only reads as a wobble once the curve has actually crossed its
  // rest point once — the initial 0→1 rise is the dilation itself, not the
  // vulnerable settle-back afterward.
  useEffect(() => {
    if (t <= 0.001) overshotRef.current = false;
    else if (value >= 0.98) overshotRef.current = true;
  }, [t, value]);
  const overshoot = overshotRef.current ? value - 1 : 0;

  const samples = useMemo(() => sampleDilateCurve(params, 160), [params]);
  const vMin = Math.min(0, ...samples.map((s) => s.v)) - 0.05;
  const vMax = Math.max(1, ...samples.map((s) => s.v)) + 0.08;

  const curvePath = samples
    .map((s, i) => `${i === 0 ? "M" : "L"} ${mapX(s.t).toFixed(2)},${mapY(s.v, vMin, vMax).toFixed(2)}`)
    .join(" ");
  const linearPath = `M ${mapX(0)},${mapY(0, vMin, vMax)} L ${mapX(1)},${mapY(1, vMin, vMax)}`;
  const gridV1Y = mapY(1, vMin, vMax);
  const gridV0Y = mapY(0, vMin, vMax);
  const dotX = mapX(t);
  const dotY = mapY(value, vMin, vMax);

  const pupilR = 10 + Math.max(0, value) * 24;
  const strokeW = 1 + Math.max(0, value) * 13;
  const revealOpacity = Math.min(1, Math.max(0, value));
  const revealScale = 0.7 + 0.3 * revealOpacity;
  const shiverY = overshoot * 9;
  const shiverRot = overshoot * 16;

  async function copyParams() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(params, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // clipboard unavailable — silently ignore, params are still visible below
    }
  }

  return (
    <div className="curve-lab">
      <header className="curve-lab__chrome">
        <p className="curve-lab__eyebrow">Design lab</p>
        <h1 className="curve-lab__title">Curve lab</h1>
        <p className="curve-lab__lede">
          One shared curve model, tunable. It's a damped-spring step
          response, not a smooth ease: <strong>hesitation</strong> holds a
          beat of tension before anything moves, <strong>damping</strong>{" "}
          below 1 lets the release overshoot past the target and settle back
          — that overshoot is the vulnerability — and <strong>tension</strong>{" "}
          is how fast it all happens. Edge dilate and future reveals should
          pull from the same presets below.
        </p>
        <p className="curve-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/edge-dilate">Edge dilate</a>
          <span aria-hidden> · </span>
          <a href="#/">Field</a>
        </p>
      </header>

      <div className="curve-lab__body">
        <section className="curve-lab__controls">
          <div className="curve-lab__control-group">
            <span className="curve-lab__control-label">Preset</span>
            <div className="curve-lab__preset-row">
              {DILATE_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  title={p.hint}
                  className={
                    "curve-lab__preset-btn" +
                    (p.id === presetId ? " curve-lab__preset-btn--active" : "")
                  }
                  onClick={() => selectPreset(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="curve-lab__hint">
              {DILATE_PRESETS.find((p) => p.id === presetId)?.hint}
            </p>
          </div>

          <div className="curve-lab__control-group">
            <span className="curve-lab__control-label">Curve kind</span>
            <div className="curve-lab__preset-row">
              {(["spring", "easeOutPow", "linear"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  className={
                    "curve-lab__preset-btn" +
                    (params.kind === k ? " curve-lab__preset-btn--active" : "")
                  }
                  onClick={() => setKind(k)}
                >
                  {k === "spring" ? "Spring" : k === "easeOutPow" ? "Old ease" : "Linear"}
                </button>
              ))}
            </div>
          </div>

          {params.kind === "spring" && (
            <>
              <label className="curve-lab__slider">
                <span>
                  Hesitation <em>{params.hesitation.toFixed(2)}</em>
                </span>
                <input
                  type="range"
                  min={0}
                  max={0.4}
                  step={0.01}
                  value={params.hesitation}
                  onChange={(e) =>
                    setParams((p) => ({ ...p, hesitation: Number(e.target.value) }))
                  }
                />
              </label>
              <label className="curve-lab__slider">
                <span>
                  Tension (ω) <em>{params.tension.toFixed(1)}</em>
                </span>
                <input
                  type="range"
                  min={3}
                  max={16}
                  step={0.1}
                  value={params.tension}
                  onChange={(e) =>
                    setParams((p) => ({ ...p, tension: Number(e.target.value) }))
                  }
                />
              </label>
              <label className="curve-lab__slider">
                <span>
                  Damping (ζ) <em>{params.damping.toFixed(2)}</em>
                </span>
                <input
                  type="range"
                  min={0.15}
                  max={1.3}
                  step={0.01}
                  value={params.damping}
                  onChange={(e) =>
                    setParams((p) => ({ ...p, damping: Number(e.target.value) }))
                  }
                />
              </label>
            </>
          )}

          {params.kind === "easeOutPow" && (
            <label className="curve-lab__slider">
              <span>
                Power <em>{params.power.toFixed(1)}</em>
              </span>
              <input
                type="range"
                min={1}
                max={5}
                step={0.1}
                value={params.power}
                onChange={(e) =>
                  setParams((p) => ({ ...p, power: Number(e.target.value) }))
                }
              />
            </label>
          )}

          <label className="curve-lab__slider">
            <span>
              Duration <em>{durationMs}ms</em>
            </span>
            <input
              type="range"
              min={300}
              max={1600}
              step={20}
              value={durationMs}
              onChange={(e) => setDurationMs(Number(e.target.value))}
            />
          </label>

          <label className="curve-lab__slider">
            <span>
              Scrub <em>t = {t.toFixed(3)}</em>
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.001}
              value={t}
              disabled={playing}
              onChange={(e) => setT(Number(e.target.value))}
            />
          </label>

          <div className="curve-lab__buttons">
            <button type="button" onClick={() => play()} disabled={playing}>
              {playing ? "Playing…" : "Play"}
            </button>
            <label className="curve-lab__loop">
              <input
                type="checkbox"
                checked={loop}
                onChange={(e) => setLoop(e.target.checked)}
              />
              Loop
            </label>
            <button type="button" onClick={resetToPreset}>
              Reset to preset
            </button>
            <button type="button" onClick={copyParams}>
              {copied ? "Copied!" : "Copy params"}
            </button>
          </div>
        </section>

        <section className="curve-lab__previews">
          <div className="curve-lab__panel curve-lab__panel--graph">
            <h3>Curve</h3>
            <svg viewBox={`0 0 ${GRAPH_W} ${GRAPH_H}`} width="100%" height={GRAPH_H}>
              <line
                x1={PAD_X}
                x2={GRAPH_W - PAD_X}
                y1={gridV1Y}
                y2={gridV1Y}
                className="curve-lab__grid"
              />
              <line
                x1={PAD_X}
                x2={GRAPH_W - PAD_X}
                y1={gridV0Y}
                y2={gridV0Y}
                className="curve-lab__grid"
              />
              <path d={linearPath} className="curve-lab__ref-path" />
              <path d={curvePath} className="curve-lab__curve-path" />
              <circle cx={dotX} cy={dotY} r={4.5} className="curve-lab__dot" />
            </svg>
            <p className="curve-lab__readout">
              t {t.toFixed(3)} → v {value.toFixed(3)}
              {overshoot > 0.01 && (
                <span className="curve-lab__overshoot"> (+{(overshoot * 100).toFixed(0)}%)</span>
              )}
            </p>
          </div>

          <div className="curve-lab__panel curve-lab__panel--pupil">
            <h3>Pupil</h3>
            <svg viewBox="0 0 120 120" width="100%" height={140}>
              <circle cx={60} cy={60} r={46} className="curve-lab__iris" />
              <circle cx={60} cy={60} r={pupilR} className="curve-lab__pupil-disc" />
            </svg>
          </div>

          <div className="curve-lab__panel curve-lab__panel--stroke">
            <h3>Stroke width</h3>
            <svg viewBox="0 0 220 80" width="100%" height={80}>
              <line
                x1={20}
                x2={200}
                y1={40}
                y2={40}
                strokeWidth={strokeW}
                className="curve-lab__stroke-line"
              />
            </svg>
          </div>

          <div className="curve-lab__panel curve-lab__panel--opacity">
            <h3>Reveal (opacity + scale)</h3>
            <div className="curve-lab__reveal-box">
              <div
                className="curve-lab__reveal-disc"
                style={{
                  opacity: revealOpacity,
                  transform: `scale(${revealScale})`,
                }}
              />
            </div>
          </div>

          <div className="curve-lab__panel curve-lab__panel--shiver">
            <h3>Shiver (overshoot as motion)</h3>
            <div className="curve-lab__shiver-box">
              <div
                className="curve-lab__shiver-chip"
                style={{
                  transform: `translateY(${shiverY}px) rotate(${shiverRot}deg)`,
                }}
              />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
