import type { GraphData } from "@antv/g6";

/**
 * SST edge kinds used by the lens lab (includes CONTAINS, which the smaller
 * G6 edgeKinds helper does not yet).
 */
export type LensEdgeKind = "contains" | "leadsto" | "expresses" | "nearto";

export const LENS_FOCUS_NODE = "platform";

/**
 * ~20-node knowledge graph: a product knowledge base with containment
 * nesting, causal LEADSTO chains, EXPRESSES mappings, and NEARTO kinship.
 * Built so each lens has a recognizable structure to reveal.
 */
export function createLensLabGraph(): GraphData {
  return {
    nodes: [
      { id: "platform", data: { label: "Platform" } },
      { id: "auth-domain", data: { label: "Auth" } },
      { id: "docs-domain", data: { label: "Docs" } },
      { id: "search-domain", data: { label: "Search" } },
      { id: "session", data: { label: "Session" } },
      { id: "token", data: { label: "Token" } },
      { id: "policy", data: { label: "Policy" } },
      { id: "gate", data: { label: "Gate" } },
      { id: "article", data: { label: "Article" } },
      { id: "draft", data: { label: "Draft" } },
      { id: "publish", data: { label: "Publish" } },
      { id: "index", data: { label: "Index" } },
      { id: "query", data: { label: "Query" } },
      { id: "rank", data: { label: "Rank" } },
      { id: "claim-secure", data: { label: "Secure by default" } },
      { id: "claim-discover", data: { label: "Discoverable" } },
      { id: "symbol-lock", data: { label: "Lock" } },
      { id: "symbol-lens", data: { label: "Lens" } },
      { id: "neighbor-audit", data: { label: "Audit trail" } },
      { id: "neighbor-cache", data: { label: "Cache" } },
    ],
    edges: [
      // CONTAINS — platform nests domains; domains nest concepts
      { id: "c1", source: "platform", target: "auth-domain", data: { kind: "contains" } },
      { id: "c2", source: "platform", target: "docs-domain", data: { kind: "contains" } },
      { id: "c3", source: "platform", target: "search-domain", data: { kind: "contains" } },
      { id: "c4", source: "auth-domain", target: "session", data: { kind: "contains" } },
      { id: "c5", source: "auth-domain", target: "token", data: { kind: "contains" } },
      { id: "c6", source: "auth-domain", target: "policy", data: { kind: "contains" } },
      { id: "c7", source: "auth-domain", target: "gate", data: { kind: "contains" } },
      { id: "c8", source: "docs-domain", target: "article", data: { kind: "contains" } },
      { id: "c9", source: "docs-domain", target: "draft", data: { kind: "contains" } },
      { id: "c10", source: "docs-domain", target: "publish", data: { kind: "contains" } },
      { id: "c11", source: "search-domain", target: "index", data: { kind: "contains" } },
      { id: "c12", source: "search-domain", target: "query", data: { kind: "contains" } },
      { id: "c13", source: "search-domain", target: "rank", data: { kind: "contains" } },

      // LEADSTO — causal / sequential flows
      { id: "l1", source: "policy", target: "gate", data: { kind: "leadsto" } },
      { id: "l2", source: "token", target: "session", data: { kind: "leadsto" } },
      { id: "l3", source: "session", target: "gate", data: { kind: "leadsto" } },
      { id: "l4", source: "draft", target: "article", data: { kind: "leadsto" } },
      { id: "l5", source: "article", target: "publish", data: { kind: "leadsto" } },
      { id: "l6", source: "publish", target: "index", data: { kind: "leadsto" } },
      { id: "l7", source: "query", target: "rank", data: { kind: "leadsto" } },
      { id: "l8", source: "index", target: "rank", data: { kind: "leadsto" } },
      { id: "l9", source: "gate", target: "claim-secure", data: { kind: "leadsto" } },
      { id: "l10", source: "rank", target: "claim-discover", data: { kind: "leadsto" } },

      // EXPRESSES — claims map onto symbols / metaphors
      { id: "x1", source: "claim-secure", target: "symbol-lock", data: { kind: "expresses" } },
      { id: "x2", source: "claim-discover", target: "symbol-lens", data: { kind: "expresses" } },
      { id: "x3", source: "gate", target: "symbol-lock", data: { kind: "expresses" } },
      { id: "x4", source: "query", target: "symbol-lens", data: { kind: "expresses" } },
      { id: "x5", source: "platform", target: "claim-secure", data: { kind: "expresses" } },

      // NEARTO — kinship / proximity without hierarchy
      { id: "n1", source: "session", target: "token", data: { kind: "nearto" } },
      { id: "n2", source: "gate", target: "neighbor-audit", data: { kind: "nearto" } },
      { id: "n3", source: "index", target: "neighbor-cache", data: { kind: "nearto" } },
      { id: "n4", source: "query", target: "neighbor-cache", data: { kind: "nearto" } },
      { id: "n5", source: "article", target: "draft", data: { kind: "nearto" } },
      { id: "n6", source: "symbol-lock", target: "symbol-lens", data: { kind: "nearto" } },
      { id: "n7", source: "neighbor-audit", target: "policy", data: { kind: "nearto" } },
      { id: "n8", source: "publish", target: "claim-discover", data: { kind: "nearto" } },
    ],
  };
}
