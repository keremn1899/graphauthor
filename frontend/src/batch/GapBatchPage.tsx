import { GapStage } from "../primitives/gap/GapStage";
import { gapVariations } from "../primitives/gap/variations";
import { VariationPanel } from "./VariationPanel";
import "./GapBatchPage.css";

export function GapBatchPage() {
  return (
    <main className="gap-batch">
      <header className="gap-batch__header">
        <p className="gap-batch__eyebrow">Loop 1 · Gap primitive</p>
        <h1 className="gap-batch__title">Constraint-passing variations</h1>
        <p className="gap-batch__lede">
          Within each pair: left = intended gap, right = oversight gap. Judge
          whether you can <em>feel</em> the difference from geometry and
          behavior alone — then pick a direction.
        </p>
      </header>

      <section className="gap-batch__grid" aria-label="Gap variations">
        {gapVariations.map((variation) => (
          <VariationPanel key={variation.id} variation={variation}>
            <GapStage variation={variation} />
          </VariationPanel>
        ))}
      </section>
    </main>
  );
}
