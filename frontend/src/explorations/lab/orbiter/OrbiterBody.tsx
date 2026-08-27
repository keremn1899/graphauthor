import type { OrbiterForm } from "./types";
import "./OrbiterBody.css";

type OrbiterBodyProps = {
  form: OrbiterForm;
  selected?: boolean;
  reducedMotion?: boolean;
  onPointerDown?: (e: React.PointerEvent) => void;
};

/**
 * Physical bodies only — solid fill, no icons, no rectangles.
 * Wobbly uses the same border-radius motion as a provisional mass.
 */
export function OrbiterBody({
  form,
  selected,
  reducedMotion,
  onPointerDown,
}: OrbiterBodyProps) {
  return (
    <button
      type="button"
      className={[
        "orbiter-body",
        `orbiter-body--${form}`,
        selected ? "orbiter-body--selected" : "",
        reducedMotion ? "orbiter-body--still" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label={form}
      onPointerDown={onPointerDown}
    >
      {form === "crisp" && <span className="orbiter-body__crisp" />}
      {form === "wobbly" && <span className="orbiter-body__wobbly" />}
      {form === "triangle" && (
        <svg viewBox="0 0 28 28" width="28" height="28" aria-hidden>
          <path
            d="M14 5 L23 22 L5 22 Z"
            fill="var(--ink)"
            stroke="var(--ink)"
            strokeWidth="1"
            strokeLinejoin="miter"
          />
        </svg>
      )}
    </button>
  );
}
