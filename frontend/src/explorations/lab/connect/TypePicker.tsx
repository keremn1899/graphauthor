import type { EdgeKind } from "../../../primitives/edge/types";
import { EDGE_KINDS } from "./types";
import "./TypePicker.css";

type TypePickerProps = {
  onPick: (kind: EdgeKind) => void;
  preselected?: EdgeKind | null;
};

export function TypePicker({ onPick, preselected }: TypePickerProps) {
  return (
    <div className="type-picker" role="group" aria-label="Edge type">
      {EDGE_KINDS.map((k) => (
        <button
          key={k}
          type="button"
          className={
            preselected === k
              ? "type-picker__opt type-picker__opt--on"
              : "type-picker__opt"
          }
          onClick={() => onPick(k)}
        >
          {k}
        </button>
      ))}
    </div>
  );
}
