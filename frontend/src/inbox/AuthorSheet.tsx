import { useState } from "react";
import type { EscalationHandoff } from "./types";
import "./AuthorSheet.css";

type AuthorSheetProps = {
  escalation: EscalationHandoff;
  onCommit: (label: string, body: string) => void;
  onCancel: () => void;
};

/** Blank-first authoring; proposal slot reserved for future engine prefill. */
export function AuthorSheet({
  escalation,
  onCommit,
  onCancel,
}: AuthorSheetProps) {
  const [label, setLabel] = useState(
    escalation.proposal?.slice(0, 48) ?? "",
  );
  const [body, setBody] = useState(escalation.proposal ?? "");

  return (
    <div className="author-sheet" role="dialog" aria-label="Author rule">
      <header className="author-sheet__header">
        <p className="author-sheet__eyebrow">Author rule</p>
        <h2 className="author-sheet__title">Encode from escalation</h2>
        <p className="author-sheet__pred">{escalation.ungovernedPredicate}</p>
      </header>

      <label className="author-sheet__field">
        <span>Concept label</span>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Name of the rule / concept"
          autoFocus
        />
      </label>

      <label className="author-sheet__field">
        <span>Source (markdown)</span>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={8}
          placeholder="Human-supplied primary source…"
        />
      </label>

      <div className="author-sheet__actions">
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="is-primary"
          disabled={!label.trim()}
          onClick={() => onCommit(label.trim(), body)}
        >
          Confirm encode
        </button>
      </div>
    </div>
  );
}
