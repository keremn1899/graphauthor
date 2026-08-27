import type { WriteCheckpoint } from "../api/ledger";
import { Swap } from "../styles/Swap";
import { chromeClass } from "./overlayChrome";
import "./WriteTimeline.css";

function shortVersion(version: string) {
  if (!version) return "—";
  return version.length > 16 ? `${version.slice(0, 8)}…${version.slice(-4)}` : version;
}

export function WriteTimeline({
  checkpoints,
  selectedId,
  liveVersion,
  provisional,
  diffFrom,
  diffTo,
  onSelect,
}: {
  checkpoints: WriteCheckpoint[];
  selectedId: string | null;
  liveVersion: string;
  /** The open graph is a construction — not yet published. */
  provisional?: boolean;
  diffFrom?: string;
  diffTo?: string;
  onSelect: (checkpoint: WriteCheckpoint) => void;
}) {
  const version = liveVersion || checkpoints.at(-1)?.to || "";
  if (!version && !checkpoints.length) return null;

  const selectedIndex = checkpoints.findIndex((row) => row.id === selectedId);
  const cursor = selectedIndex >= 0 ? selectedIndex : Math.max(0, checkpoints.length - 1);
  const showSteps = checkpoints.length >= 1;
  const showingDiff = Boolean(diffFrom && diffTo);
  const label = showingDiff
    ? `${shortVersion(diffFrom ?? "")} → ${shortVersion(diffTo ?? "")}`
    : shortVersion(version);
  const title = showingDiff ? `${diffFrom} → ${diffTo}` : version;

  return (
    <div className={chromeClass("write-timeline")} role="group" aria-label="Graph version">
      {provisional ? (
        <span className="write-timeline__state">construction</span>
      ) : null}
      {showSteps ? (
        <button
          type="button"
          className="write-timeline__step"
          onClick={() => onSelect(checkpoints[Math.max(0, cursor - 1)]!)}
          disabled={cursor <= 0}
          aria-label="Older write"
        >
          ←
        </button>
      ) : null}
      <span className="write-timeline__hash" title={title}>
        <Swap id={label}>{label}</Swap>
      </span>
      {showSteps ? (
        <button
          type="button"
          className="write-timeline__step"
          onClick={() =>
            onSelect(checkpoints[Math.min(checkpoints.length - 1, cursor + 1)]!)
          }
          disabled={cursor >= checkpoints.length - 1}
          aria-label="Newer write"
        >
          →
        </button>
      ) : null}
    </div>
  );
}
