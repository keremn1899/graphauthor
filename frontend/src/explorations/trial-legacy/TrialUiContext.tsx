import { createContext, useContext } from "react";
import type { EdgeKind } from "../../primitives/edge/types";

export type TrialUiState = {
  reducedMotion: boolean;
  lens: EdgeKind;
  accretingOrbiterId: string | null;
  onAccretionDone: (orbiterId: string) => void;
};

const TrialUiContext = createContext<TrialUiState>({
  reducedMotion: false,
  lens: "CONTAINS",
  accretingOrbiterId: null,
  onAccretionDone: () => undefined,
});

export const TrialUiProvider = TrialUiContext.Provider;

export function useTrialUi() {
  return useContext(TrialUiContext);
}
