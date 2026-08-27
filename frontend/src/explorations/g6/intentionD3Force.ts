import {
  D3ForceLayout,
  type D3ForceLayoutOptions,
  type EdgeData,
  type GraphData,
  type NodeData,
} from "@antv/layout";
import { ExtensionCategory, register } from "@antv/g6";

type LayoutNode = {
  id: string | number;
  style?: { fx?: number | null; fy?: number | null };
};

/**
 * The G6 d3-force adapter normally copies only `style.x/y/z` into its layout
 * model, dropping d3's fixed-position fields. This preserves fx/fy so authored
 * placement is an explicit constraint, not merely an initial suggestion.
 */
class IntentionD3ForceLayout extends D3ForceLayout {
  // DragElementForce only recognizes layouts with id "d3-force" | "d3-force-3d".
  // Registration type stays "intention-d3-force"; runtime id must match stock.
  id = "d3-force";

  async execute(
    data: GraphData<NodeData, EdgeData>,
    options: Partial<D3ForceLayoutOptions> = {},
  ) {
    const baseNode = options.node;

    return super.execute(data, {
      ...options,
      node: (datum: NodeData) => {
        const source = datum as LayoutNode;
        const node = baseNode?.(datum) ?? { id: source.id };
        const { fx, fy } = source.style ?? {};
        return {
          ...node,
          ...(typeof fx === "number" ? { fx } : {}),
          ...(typeof fy === "number" ? { fy } : {}),
        } as ReturnType<NonNullable<D3ForceLayoutOptions["node"]>>;
      },
    });
  }
}

let registered = false;

export function ensureIntentionD3ForceRegistered() {
  if (registered) return;
  register(ExtensionCategory.LAYOUT, "intention-d3-force", IntentionD3ForceLayout);
  registered = true;
}
