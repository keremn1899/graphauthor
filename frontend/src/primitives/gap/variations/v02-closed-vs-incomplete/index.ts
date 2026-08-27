import type { GapVariation } from "../../types";
import { Intended } from "./Intended";
import { Oversight } from "./Oversight";

export const v02ClosedVsIncomplete: GapVariation = {
  id: "v02",
  thesis: "Four walls vs missing wall",
  note: "Intended seals all sides; oversight has three firm walls and an absent fourth — stubs reach and fail.",
  Intended,
  Oversight,
};
