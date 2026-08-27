import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { EdgeKind } from "../../shared/edges/types";

type FieldUiValue = {
  reducedMotion: boolean;
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  focusedEdgeId: string | null;
  setFocusedEdgeId: (id: string | null) => void;
  provisionalPreviewId: string | null;
  setProvisionalPreviewId: (id: string | null) => void;
  highlightId: string | null;
  setHighlightId: (id: string | null) => void;
  markRead: (id: string) => void;
  pendingConnect: {
    sourceId: string;
    targetId: string;
  } | null;
  setPendingConnect: (
    v: { sourceId: string; targetId: string } | null,
  ) => void;
  defaultEdgeKind: EdgeKind;
};

const FieldUiContext = createContext<FieldUiValue | null>(null);

type FieldUiProviderProps = {
  children: ReactNode;
  reducedMotion: boolean;
  onMarkRead: (id: string) => void;
};

export function FieldUiProvider({
  children,
  reducedMotion,
  onMarkRead,
}: FieldUiProviderProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusedEdgeId, setFocusedEdgeId] = useState<string | null>(null);
  const [provisionalPreviewId, setProvisionalPreviewId] = useState<
    string | null
  >(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [pendingConnect, setPendingConnect] = useState<{
    sourceId: string;
    targetId: string;
  } | null>(null);

  const markRead = useCallback(
    (id: string) => {
      onMarkRead(id);
    },
    [onMarkRead],
  );

  const value = useMemo(
    () => ({
      reducedMotion,
      selectedId,
      setSelectedId,
      focusedEdgeId,
      setFocusedEdgeId,
      provisionalPreviewId,
      setProvisionalPreviewId,
      highlightId,
      setHighlightId,
      markRead,
      pendingConnect,
      setPendingConnect,
      defaultEdgeKind: "CONTAINS" as EdgeKind,
    }),
    [
      reducedMotion,
      selectedId,
      focusedEdgeId,
      provisionalPreviewId,
      highlightId,
      markRead,
      pendingConnect,
    ],
  );

  return (
    <FieldUiContext.Provider value={value}>{children}</FieldUiContext.Provider>
  );
}

export function useFieldUi(): FieldUiValue {
  const ctx = useContext(FieldUiContext);
  if (!ctx) throw new Error("useFieldUi must be used within FieldUiProvider");
  return ctx;
}
