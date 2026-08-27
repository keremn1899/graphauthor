import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { EdgeKind } from "../shared/edges/types";
import type { ConceptData, SimLink, SimNode } from "../field/data/fieldGraph";
import {
  createInitialFieldLinks,
  createInitialFieldNodes,
} from "../field/data/fieldGraph";
import type { EscalationHandoff } from "../inbox/types";
import { createInitialEscalations } from "../inbox/data/escalations";

export type GraphWritePayload = {
  label: string;
  /** Optional parent to CONTAINS / LEADSTO into */
  attachToId?: string;
  edgeKind?: EdgeKind;
  fromEscalationId?: string;
};

type GraphControllerValue = {
  simNodes: SimNode[];
  setSimNodes: React.Dispatch<React.SetStateAction<SimNode[]>>;
  simLinks: SimLink[];
  setSimLinks: React.Dispatch<React.SetStateAction<SimLink[]>>;
  escalations: EscalationHandoff[];
  setEscalations: React.Dispatch<React.SetStateAction<EscalationHandoff[]>>;
  applyWrite: (payload: GraphWritePayload) => string;
  markNodeRead: (id: string) => void;
  requestFlyTo: (id: string | null) => void;
  flyToId: string | null;
  clearFlyTo: () => void;
};

const GraphControllerContext = createContext<GraphControllerValue | null>(
  null,
);

export function GraphControllerProvider({ children }: { children: ReactNode }) {
  const [simNodes, setSimNodes] = useState(createInitialFieldNodes);
  const [simLinks, setSimLinks] = useState(createInitialFieldLinks);
  const [escalations, setEscalations] = useState(createInitialEscalations);
  const [flyToId, setFlyToId] = useState<string | null>(null);
  const pulseSeq = useMemo(() => ({ n: 1 }), []);

  const markNodeRead = useCallback((id: string) => {
    setSimNodes((list) =>
      list.map((n) =>
        n.id === id
          ? { ...n, concept: { ...n.concept, unread: false } }
          : n,
      ),
    );
  }, []);

  const applyWrite = useCallback((payload: GraphWritePayload) => {
    const id = `n-${Date.now().toString(36)}`;
    const attach = payload.attachToId
      ? simNodes.find((n) => n.id === payload.attachToId)
      : undefined;
    const x = attach ? attach.x + 120 : 560 + (Math.random() - 0.5) * 80;
    const y = attach ? attach.y + 80 : 320 + (Math.random() - 0.5) * 80;
    pulseSeq.n += 1;

    const concept: ConceptData = {
      label: payload.label,
      lifecycle: "birthing",
      unread: true,
      pulseToken: pulseSeq.n,
    };

    setSimNodes((list) => [
      ...list,
      { id, x, y, fx: x, fy: y, concept },
    ]);

    if (payload.attachToId) {
      const kind = payload.edgeKind ?? "CONTAINS";
      setSimLinks((links) => [
        ...links,
        {
          id: `e-${id}`,
          source: payload.attachToId!,
          target: id,
          kind,
        },
      ]);
    }

    window.setTimeout(() => {
      setSimNodes((list) =>
        list.map((n) =>
          n.id === id
            ? {
                ...n,
                concept: { ...n.concept, lifecycle: "alive" },
              }
            : n,
        ),
      );
    }, 500);

    if (payload.fromEscalationId) {
      setEscalations((list) =>
        list.map((e) =>
          e.id === payload.fromEscalationId
            ? { ...e, status: "resolved", resolvedNodeId: id }
            : e,
        ),
      );
    }

    setFlyToId(id);
    return id;
  }, [pulseSeq, simNodes]);

  const requestFlyTo = useCallback((id: string | null) => {
    setFlyToId(id);
  }, []);

  const clearFlyTo = useCallback(() => setFlyToId(null), []);

  const value = useMemo(
    () => ({
      simNodes,
      setSimNodes,
      simLinks,
      setSimLinks,
      escalations,
      setEscalations,
      applyWrite,
      markNodeRead,
      requestFlyTo,
      flyToId,
      clearFlyTo,
    }),
    [
      simNodes,
      simLinks,
      escalations,
      applyWrite,
      markNodeRead,
      requestFlyTo,
      flyToId,
      clearFlyTo,
    ],
  );

  return (
    <GraphControllerContext.Provider value={value}>
      {children}
    </GraphControllerContext.Provider>
  );
}

export function useGraphController(): GraphControllerValue {
  const ctx = useContext(GraphControllerContext);
  if (!ctx) {
    throw new Error("useGraphController must be used within provider");
  }
  return ctx;
}
