import type { ReactNode } from "react";
import type { GapVariation } from "../primitives/gap/types";
import "./VariationPanel.css";

type VariationPanelProps = {
  variation: GapVariation;
  children: ReactNode;
};

export function VariationPanel({ variation, children }: VariationPanelProps) {
  return (
    <article className="variation-panel">
      <header className="variation-panel__header">
        <h2 className="variation-panel__id">{variation.id}</h2>
        <p className="variation-panel__thesis">{variation.thesis}</p>
        <p className="variation-panel__note">{variation.note}</p>
      </header>
      <div className="variation-panel__stage">{children}</div>
    </article>
  );
}
