import type { EdgeKind } from "../../shared/edges/types";
import { EDGE_KINDS } from "../../shared/edges/types";
import "./TypePicker.css";

type TypePickerProps = {
  onPick: (kind: EdgeKind) => void;
  onCancel: () => void;
};

export function TypePicker({ onPick, onCancel }: TypePickerProps) {
  return (
    <div className="field-type-picker" role="dialog" aria-label="Edge type">
      <p className="field-type-picker__label">Relation type</p>
      <div className="field-type-picker__choices">
        {EDGE_KINDS.map((k) => (
          <button key={k} type="button" onClick={() => onPick(k)}>
            {k}
          </button>
        ))}
      </div>
      <button type="button" className="field-type-picker__cancel" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}
