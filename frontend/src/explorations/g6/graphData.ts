import type { GraphData } from "@antv/g6";

export const CONNECT_GRAPH_DATA: GraphData = {
  nodes: [
    { id: "idea", style: { x: 140, y: 260 } },
    { id: "draft", style: { x: 320, y: 160 } },
    { id: "notes", style: { x: 520, y: 200 } },
    { id: "insight", style: { x: 380, y: 400 } },
    { id: "archive", style: { x: 580, y: 400 } },
  ],
  edges: [
    { id: "e-idea-draft", source: "idea", target: "draft", data: { kind: "leadsto" } },
    { id: "e-draft-notes", source: "draft", target: "notes", data: { kind: "leadsto" } },
    { id: "e-notes-insight", source: "notes", target: "insight", data: { kind: "expresses" } },
    { id: "e-idea-insight", source: "idea", target: "insight", data: { kind: "nearto" } },
    { id: "e-insight-archive", source: "insight", target: "archive", data: { kind: "expresses" } },
  ],
};

export const LIFECYCLE_GRAPH_DATA: GraphData = {
  nodes: [
    { id: "seed", style: { x: 120, y: 120 } },
    { id: "stem", style: { x: 220, y: 120 } },
    { id: "leaf", style: { x: 170, y: 200 } },
  ],
  edges: [
    { id: "e-seed-stem", source: "seed", target: "stem", data: { kind: "leadsto" } },
    { id: "e-stem-leaf", source: "stem", target: "leaf", data: { kind: "expresses" } },
  ],
};
