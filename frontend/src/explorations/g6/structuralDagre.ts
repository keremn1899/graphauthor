import { AntVDagreLayout } from "@antv/layout";
import type {
  AntVDagreLayoutOptions,
  EdgeData as LayoutEdgeData,
  GraphData as LayoutGraphData,
  NodeData as LayoutNodeData,
} from "@antv/layout";
import { ExtensionCategory, register } from "@antv/g6";

/**
 * Feeding every SST edge kind into antv-dagre's ranker produces messy,
 * crossing lines: kinds like NEARTO/EXPRESSES carry no hierarchy, but
 * dagre treats every edge as a ranking constraint. This wraps antv-dagre so
 * the ranking algorithm only "sees" one chosen edge kind (the one with a
 * real characteristic hierarchy), while G6 still renders every edge in the
 * graph's actual data untouched — nothing is filtered from view.
 */
function makeKindFilteredDagreLayout(keepKind: string) {
  return class KindFilteredDagreLayout extends AntVDagreLayout {
    async execute(
      data: LayoutGraphData<LayoutNodeData, LayoutEdgeData>,
      options: Partial<AntVDagreLayoutOptions> = {},
    ) {
      const structural = (data.edges ?? []).filter(
        (e) => (e.data as { kind?: string } | undefined)?.kind === keepKind,
      );
      return super.execute({ ...data, edges: structural }, options);
    }
  };
}

export const LENS_DAGRE_CONTAINS = "lens-dagre-contains";
export const LENS_DAGRE_LEADSTO = "lens-dagre-leadsto";

let registered = false;

export function ensureStructuralDagreRegistered() {
  if (registered) return;
  register(
    ExtensionCategory.LAYOUT,
    LENS_DAGRE_CONTAINS,
    makeKindFilteredDagreLayout("contains"),
  );
  register(
    ExtensionCategory.LAYOUT,
    LENS_DAGRE_LEADSTO,
    makeKindFilteredDagreLayout("leadsto"),
  );
  registered = true;
}
