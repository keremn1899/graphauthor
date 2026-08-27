/**
 * Graph DNA — same product graph surface (shell, overlays, Ask, Graphs) with a
 * side panel that authors look parameters. Motion stays on the motion lab.
 */

import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useMemo,
  useState,
} from "react";
import "@fontsource/archivo/latin-500.css";
import "@fontsource/archivo/latin-600.css";
import "@fontsource/archivo-narrow/latin-500.css";
import "@fontsource/archivo-narrow/latin-600.css";
import "@fontsource/asap/latin-500.css";
import "@fontsource/asap/latin-600.css";
import "@fontsource/asap-condensed/latin-500.css";
import "@fontsource/asap-condensed/latin-600.css";
import "@fontsource/cabin/latin-500.css";
import "@fontsource/cabin/latin-600.css";
import "@fontsource/chivo/latin-500.css";
import "@fontsource/chivo/latin-600.css";
import "@fontsource/dm-sans/latin-500.css";
import "@fontsource/dm-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans-condensed/latin-500.css";
import "@fontsource/ibm-plex-sans-condensed/latin-600.css";
import "@fontsource/josefin-sans/latin-500.css";
import "@fontsource/josefin-sans/latin-600.css";
import {
  CIRCLE_NODE_FONT_IDS,
  NODE_FONTS,
} from "./g6/graphOptions";
import {
  type GraphDnaFocusTheme,
  type GraphDnaTheme,
  type RadixScaleId,
  type RadixToken,
  radixValue,
} from "../styles/graphDna";
import {
  DNA_PARAM_DEFAULTS,
  chromeForTheme,
  readDnaParams,
  writeDnaParams,
  type DnaChromeTheme,
  type DnaParams,
} from "./dnaParamsStore";
import { GraphWorkspace } from "../product/GraphWorkspace";
import {
  GraphDnaRuntimeProvider,
  type GraphDnaRuntime,
} from "../product/graphDnaRuntime";
import { ProductShell, useProductTheme } from "../product/ProductShell";
import "../styles/fonts.css";
import "./GraphDnaWorkbenchPage.css";

const RADIX_SCALE_IDS: readonly RadixScaleId[] = [
  "gray",
  "mauve",
  "slate",
  "sage",
  "olive",
  "sand",
  "tomato",
  "red",
  "ruby",
  "crimson",
  "pink",
  "plum",
  "purple",
  "violet",
  "iris",
  "indigo",
  "blue",
  "cyan",
  "teal",
  "jade",
  "green",
  "grass",
  "brown",
  "bronze",
  "gold",
  "sky",
  "mint",
  "lime",
  "yellow",
  "amber",
  "orange",
  "black",
  "grayDark",
  "mauveDark",
  "slateDark",
  "sageDark",
  "oliveDark",
  "sandDark",
  "tomatoDark",
  "redDark",
  "rubyDark",
  "crimsonDark",
  "pinkDark",
  "plumDark",
  "purpleDark",
  "violetDark",
  "irisDark",
  "indigoDark",
  "blueDark",
  "cyanDark",
  "tealDark",
  "jadeDark",
  "greenDark",
  "grassDark",
  "brownDark",
  "bronzeDark",
  "goldDark",
  "skyDark",
  "mintDark",
  "limeDark",
  "yellowDark",
  "amberDark",
  "orangeDark",
] as const;

const CHROME_KEYS: Array<keyof DnaChromeTheme> = [
  "canvas",
  "panel",
  "ink",
  "inkMuted",
  "rule",
];

function humanizeKey(value: string) {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
}

function RangeControl({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="gdna__range">
      <span>
        {label}
        <output>
          {value}
          {unit}
        </output>
      </span>
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function RadixControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: RadixToken;
  onChange: (value: RadixToken) => void;
}) {
  return (
    <label className="gdna__radix">
      <span>{label}</span>
      <i style={{ background: radixValue(value) }} />
      <select
        value={value.scale}
        onChange={(event) =>
          onChange({
            ...value,
            scale: event.target.value as RadixScaleId,
          })
        }
      >
        {RADIX_SCALE_IDS.map((scale) => (
          <option key={scale} value={scale}>
            {scale}
          </option>
        ))}
      </select>
      <select
        value={value.step}
        aria-label={`${label} Radix step`}
        onChange={(event) =>
          onChange({ ...value, step: Number(event.target.value) })
        }
      >
        {Array.from({ length: 12 }, (_, index) => index + 1).map((step) => (
          <option key={step} value={step}>
            {step}
          </option>
        ))}
      </select>
    </label>
  );
}

function DnaParamPanel({
  params,
  setParams,
}: {
  params: DnaParams;
  setParams: Dispatch<SetStateAction<DnaParams>>;
}) {
  const theme = useProductTheme();
  const [copied, setCopied] = useState(false);
  const palette = params[theme];
  const chrome = chromeForTheme(params, theme);

  const patch = <K extends keyof DnaParams>(key: K, value: DnaParams[K]) =>
    setParams((current) => ({ ...current, [key]: value }));

  const patchTheme = <K extends keyof GraphDnaTheme>(
    key: K,
    value: GraphDnaTheme[K],
  ) =>
    setParams((current) => ({
      ...current,
      [theme]: { ...current[theme], [key]: value },
    }));

  const patchFocus = <K extends keyof GraphDnaFocusTheme>(
    key: K,
    value: GraphDnaFocusTheme[K],
  ) =>
    setParams((current) => ({
      ...current,
      focus: { ...current.focus, [key]: value },
    }));

  const patchChrome = <K extends keyof DnaChromeTheme>(
    key: K,
    value: DnaChromeTheme[K],
  ) => {
    const field = theme === "dark" ? "chromeDark" : "chromeLight";
    setParams((current) => ({
      ...current,
      [field]: { ...current[field], [key]: value },
    }));
  };

  const copyConfig = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(params, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <aside className="gdna-mirror__panel" aria-label="Graph DNA">
      <header className="gdna-mirror__panel-head">
        <p className="gdna__nav">
          <a href="#/explorations">Explorations</a> / Graph DNA
        </p>
        <h1>Graph DNA</h1>
        <p className="gdna__hint">
          Same Graph page — overlays, Ask, Graphs — with look parameters on the
          side. Motion lives on the{" "}
          <a href="#/explorations/graph-dna-motion?api=live&apiToken=devtoken">
            motion lab
          </a>
          . Editing{" "}
          <strong>{theme}</strong> tokens (shell Light/Dark).
        </p>
        <div className="gdna-mirror__panel-actions">
          <button type="button" onClick={copyConfig}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            onClick={() => setParams(DNA_PARAM_DEFAULTS)}
          >
            Reset
          </button>
        </div>
      </header>

      {/* Two elements, not one. `gdna__controls` is shared with the motion lab,
          where it is a grid that sizes itself — and it says so with
          `height: auto !important; overflow: visible !important`. On the same
          node as the scroller those win, the pane grows past its panel, and the
          panel (overflow: hidden) clips the rest with nothing to scroll. */}
      <div className="gdna-mirror__panel-scroll">
      <div className="gdna__controls">
        <section>
          <h2>
            Chrome & overlays · {theme}
          </h2>
          <p className="gdna__hint">
            Colours for shell, Graphs sidebar, Ask, finder, bar chips, and
            reader. Open Graphs or Ask to judge them.
          </p>
          {CHROME_KEYS.map((key) => (
            <RadixControl
              key={`${theme}-chrome-${key}`}
              label={humanizeKey(key)}
              value={chrome[key]}
              onChange={(value) => patchChrome(key, value)}
            />
          ))}
          <RangeControl
            label="Floating chrome opacity"
            value={Math.round(params.chromeOpacity * 100)}
            min={60}
            max={100}
            unit="%"
            onChange={(value) => patch("chromeOpacity", value / 100)}
          />
          <p className="gdna__hint">
            Flat translucency, no blur behind it. A frosted pane implies a light
            source; a rule states an edge.
          </p>
          <RangeControl
            label="Graphs panel width"
            value={params.overlayWidth}
            min={240}
            max={520}
            step={10}
            unit="px"
            onChange={(value) => patch("overlayWidth", value)}
          />
          <RangeControl
            label="Node reader width"
            value={params.readerWidth}
            min={280}
            max={640}
            step={10}
            unit="px"
            onChange={(value) => patch("readerWidth", value)}
          />
        </section>

        <section>
          <h2>
            Graph matter · {theme} ·{" "}
            <a
              className="gdna__inline-link"
              href="https://www.radix-ui.com/colors"
              target="_blank"
              rel="noreferrer"
            >
              Radix
            </a>
          </h2>
          {(Object.keys(palette) as Array<keyof GraphDnaTheme>).map((key) => (
            <RadixControl
              key={`${theme}-${key}`}
              label={humanizeKey(key)}
              value={palette[key]}
              onChange={(value) => patchTheme(key, value)}
            />
          ))}
        </section>

        <details className="gdna__control-group">
          <summary>Focus / proposal / diff · Radix</summary>
          <section>
            {(Object.keys(params.focus) as Array<keyof GraphDnaFocusTheme>).map(
              (key) => (
                <RadixControl
                  key={key}
                  label={humanizeKey(key)}
                  value={params.focus[key]}
                  onChange={(value) => patchFocus(key, value)}
                />
              ),
            )}
          </section>
        </details>

        <section>
          <h2>Layout</h2>
          <RangeControl
            label="Spacing"
            value={Math.round(params.spacing * 100)}
            min={100}
            max={200}
            step={5}
            unit="%"
            onChange={(value) => patch("spacing", value / 100)}
          />
          <p className="gdna__hint">
            100% is “as arranged”: the collision-safe baseline for the drawn
            node size. Higher values only add room between centres.
          </p>
        </section>

        <section>
          <h2>Nodes</h2>
          <div
            className="gdna__font-chips"
            role="group"
            aria-label="Node label font"
          >
            {CIRCLE_NODE_FONT_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={params.labelFontId === id ? "is-active" : ""}
                style={{ fontFamily: NODE_FONTS[id].family }}
                title={NODE_FONTS[id].note}
                onClick={() => patch("labelFontId", id)}
              >
                {NODE_FONTS[id].label}
              </button>
            ))}
          </div>
          <RangeControl
            label="Font weight"
            value={params.labelFontWeight}
            min={400}
            max={800}
            step={100}
            onChange={(value) => patch("labelFontWeight", value)}
          />
          <RangeControl
            label="Diameter"
            value={params.nodeDiameter}
            min={42}
            max={100}
            unit="px"
            onChange={(value) => patch("nodeDiameter", value)}
          />
          <RangeControl
            label="Boundary"
            value={params.nodeLine}
            min={0.5}
            max={4}
            step={0.1}
            unit="px"
            onChange={(value) => patch("nodeLine", value)}
          />
          <RangeControl
            label="Internal label"
            value={params.labelSize}
            min={7}
            max={16}
            unit="px"
            onChange={(value) => patch("labelSize", value)}
          />
          <RangeControl
            label="Text width"
            value={params.labelMaxWidth}
            min={45}
            max={92}
            unit="%"
            onChange={(value) => patch("labelMaxWidth", value)}
          />
          <RangeControl
            label="Label baseline"
            value={params.labelBaselineNudge}
            min={-6}
            max={10}
            unit="px"
            onChange={(value) => patch("labelBaselineNudge", value)}
          />
          <RangeControl
            label="Line height"
            value={Math.round(params.labelLineHeight * 100)}
            min={90}
            max={180}
            step={5}
            unit="%"
            onChange={(value) => patch("labelLineHeight", value / 100)}
          />
          <RangeControl
            label="Label lines"
            value={params.labelMaxLines}
            min={1}
            max={4}
            onChange={(value) => patch("labelMaxLines", value)}
          />
          <p className="gdna__hint">
            A name that needs more lines than this is elided, not shrunk. One
            line reads as a tag; three turns the disc into a paragraph.
          </p>
          <RangeControl
            label="Disc opacity"
            value={Math.round(params.nodeFillOpacity * 100)}
            min={10}
            max={100}
            unit="%"
            onChange={(value) => patch("nodeFillOpacity", value / 100)}
          />
          <RangeControl
            label="Label opacity"
            value={Math.round(params.nodeLabelOpacity * 100)}
            min={20}
            max={100}
            unit="%"
            onChange={(value) => patch("nodeLabelOpacity", value / 100)}
          />
          <p className="gdna__hint">
            Independent of each other, and both multiplied by focus attenuation
            rather than replacing it — a dimmed node stays dimmed.
          </p>
        </section>

        <section>
          <h2>Relationships</h2>
          <RangeControl
            label="Resting filament"
            value={params.edgeWidth}
            min={0.4}
            max={4}
            step={0.1}
            unit="px"
            onChange={(value) => patch("edgeWidth", value)}
          />
          <RangeControl
            label="Resting opacity"
            value={Math.round(params.edgeOpacity * 100)}
            min={20}
            max={100}
            unit="%"
            onChange={(value) => patch("edgeOpacity", value / 100)}
          />
          <RangeControl
            label="Type label"
            value={params.edgeLabelSize}
            min={5}
            max={14}
            unit="px"
            onChange={(value) => patch("edgeLabelSize", value)}
          />
          <RangeControl
            label="Type label opacity"
            value={Math.round(params.edgeLabelOpacity * 100)}
            min={20}
            max={100}
            unit="%"
            onChange={(value) => patch("edgeLabelOpacity", value / 100)}
          />
          <p className="gdna__hint">
            Relation chips appear on lit edges only — hover a node or focus one
            to judge this.
          </p>
          <RangeControl
            label="Spoke opacity at rest"
            value={Math.round(params.spokeRestOpacity * 100)}
            min={5}
            max={100}
            unit="%"
            onChange={(value) => patch("spokeRestOpacity", value / 100)}
          />
          <p className="gdna__hint">
            Spokes are the edges from a packed root to its branches — the map's
            largest source of crossings. Held back at rest, lifting to full as
            the edge is lit, so asking about the root still shows them. At 100%
            the class stops existing.
          </p>
          <RangeControl
            label="Dotted gap"
            value={params.dottedGap}
            min={2}
            max={14}
            step={0.5}
            unit="px"
            onChange={(value) => patch("dottedGap", value)}
          />
        </section>

        <section>
          <h2>Drag weight</h2>
          <RangeControl
            label="Node relief"
            value={params.dragNodeRelief}
            min={0}
            max={0.8}
            step={0.05}
            unit="px"
            onChange={(value) => patch("dragNodeRelief", value)}
          />
          <RangeControl
            label="Edge load"
            value={params.dragEdgeLoad}
            min={0}
            max={1.2}
            step={0.05}
            unit="px"
            onChange={(value) => patch("dragEdgeLoad", value)}
          />
          <RangeControl
            label="Edge presence"
            value={params.dragEdgePresence}
            min={0}
            max={0.3}
            step={0.01}
            onChange={(value) => patch("dragEdgePresence", value)}
          />
        </section>

        <section>
          <h2>Selection ring</h2>
          <RangeControl
            label="Ring clearance"
            value={params.selectionClearance}
            min={2}
            max={24}
            unit="px"
            onChange={(value) => patch("selectionClearance", value)}
          />
          <RangeControl
            label="Dot spacing"
            value={params.selectionDotGap}
            min={2}
            max={12}
            step={0.5}
            unit="px"
            onChange={(value) => patch("selectionDotGap", value)}
          />
          <RangeControl
            label="Ring boundary"
            value={params.selectionLine}
            min={0.5}
            max={4}
            step={0.1}
            unit="px"
            onChange={(value) => patch("selectionLine", value)}
          />
          <p className="gdna__hint">
            Orbit animation is off here. Tune motion on the{" "}
            <a href="#/explorations/graph-dna-motion?api=live&apiToken=devtoken">
              motion lab
            </a>
            .
          </p>
        </section>
      </div>
      </div>
    </aside>
  );
}

export function GraphDnaWorkbenchPage() {
  const [params, setParams] = useState(() => readDnaParams());

  useEffect(() => {
    writeDnaParams(params);
  }, [params]);

  const runtime = useMemo<GraphDnaRuntime>(
    () => ({
      params,
      labelFontFamily: NODE_FONTS[params.labelFontId].family,
      labelFontWeight: params.labelFontWeight,
    }),
    [params],
  );

  return (
    <GraphDnaRuntimeProvider value={runtime}>
      {/* The rail owns the left edge of this page, so the shell's floating nav
          has to start after it. Matches `--gdna-rail` below; stated twice
          because one is a grid track and the other is chrome outside the grid. */}
      <ProductShell active="graph" chromeInsetLeft="var(--gdna-rail)">
        <div className="gdna-mirror">
          <DnaParamPanel params={params} setParams={setParams} />
          <div className="gdna-mirror__graph">
            <GraphWorkspace productMode />
          </div>
        </div>
      </ProductShell>
    </GraphDnaRuntimeProvider>
  );
}
