/**
 * Optional runtime DNA overrides for the product canvas.
 *
 * The Graph DNA workbench mounts the real Graph page under this provider so
 * knobs update the same canvas/overlays the product uses. Outside the
 * workbench the canvas falls back to `styles/graphDna` constants.
 */

import { createContext, useContext } from "react";
import type { DnaParams } from "../explorations/dnaParamsStore";

export type GraphDnaRuntime = {
  params: DnaParams;
  labelFontFamily: string;
  labelFontWeight: number;
};

const GraphDnaRuntimeContext = createContext<GraphDnaRuntime | null>(null);

export function GraphDnaRuntimeProvider({
  value,
  children,
}: {
  value: GraphDnaRuntime;
  children: React.ReactNode;
}) {
  return (
    <GraphDnaRuntimeContext.Provider value={value}>
      {children}
    </GraphDnaRuntimeContext.Provider>
  );
}

export function useGraphDnaRuntime() {
  return useContext(GraphDnaRuntimeContext);
}
