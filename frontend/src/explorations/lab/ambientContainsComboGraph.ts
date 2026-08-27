import type { ComboData, EdgeData, GraphData, NodeData } from "@antv/g6";
import { createAmbientLodGraph, labelOf } from "./ambientLodData";
import { lensVisualKindOf } from "../g6/lensEdgeOptions";

/**
 * Rebuild the ambient fixture so CONTAINS is G6 combo membership instead of
 * edges — but only for leaf-bearing parents (e.g. Commerce → leaves).
 *
 * Umbrella parents that only contain other parents (Platform Core → regions)
 * stay as normal nodes. A giant nested outer hull is the main pan-cost; one
 * region-sized rect per area is enough for the experiment.
 */
/**
 * `base` defaults to the fixture, but any graph in the same shape works — the
 * combos are derived from CONTAINS edges, not from anything fixture-specific,
 * so a real committed graph gets hulls on the same terms.
 */
export function createAmbientContainsComboGraph(base: GraphData = createAmbientLodGraph()): GraphData {
  const nodesIn = (base.nodes ?? []) as NodeData[];
  const edgesIn = (base.edges ?? []) as EdgeData[];

  const byId = new Map(nodesIn.map((n) => [String(n.id), n]));
  const contains: { source: string; target: string }[] = [];
  for (const edge of edgesIn) {
    if (lensVisualKindOf(edge) !== "contains") continue;
    contains.push({
      source: String(edge.source),
      target: String(edge.target),
    });
  }

  const parentIds = new Set(contains.map((e) => e.source));
  // Only parents that own at least one non-parent child become combos.
  const comboIds = new Set(
    [...parentIds].filter((id) =>
      contains.some((e) => e.source === id && !parentIds.has(e.target)),
    ),
  );

  const parentOf = new Map<string, string>();
  const memberCount = new Map<string, number>();
  for (const { source, target } of contains) {
    if (!comboIds.has(source)) continue;
    parentOf.set(target, source);
    if (!comboIds.has(target)) {
      memberCount.set(source, (memberCount.get(source) ?? 0) + 1);
    }
  }

  const combos: ComboData[] = [...comboIds].map((id) => {
    const node = byId.get(id);
    return {
      id,
      data: {
        label: node ? labelOf(node) : id,
        kind: node?.data?.kind,
        is_landmark: Boolean(node?.data?.is_landmark),
        memberCount: memberCount.get(id) ?? 0,
      },
    };
  });

  const nodes: NodeData[] = nodesIn
    .filter((n) => !comboIds.has(String(n.id)))
    .map((n) => {
      const id = String(n.id);
      const parent = parentOf.get(id);
      // Don't assign combo membership to another combo id (none here, but safe).
      if (parent && !comboIds.has(id)) {
        return { ...n, combo: parent };
      }
      return { ...n };
    });

  const edges: EdgeData[] = edgesIn.filter((edge) => {
    const kind = lensVisualKindOf(edge);
    if (kind !== "contains") return true;
    const s = String(edge.source);
    const t = String(edge.target);
    // Membership inside a leaf-bearing combo — drop the edge.
    if (comboIds.has(s)) return false;
    // Umbrella node → region combo: keep so Platform Core still links out.
    if (comboIds.has(t)) return true;
    return true;
  });

  return { nodes, edges, combos };
}
