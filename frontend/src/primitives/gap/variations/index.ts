import type { GapVariation } from "../types";
import { v01MembraneVsLesion } from "./v01-membrane-vs-lesion";
import { v02ClosedVsIncomplete } from "./v02-closed-vs-incomplete";
import { v03VacuoleVsReaching } from "./v03-vacuole-vs-reaching";
import { v04CornerAuthorityVsDissolution } from "./v04-corner-authority-vs-dissolution";

/** Constraint-passing Gap variations only — see review.md for rejects. */
export const gapVariations: GapVariation[] = [
  v01MembraneVsLesion,
  v02ClosedVsIncomplete,
  v03VacuoleVsReaching,
  v04CornerAuthorityVsDissolution,
];
