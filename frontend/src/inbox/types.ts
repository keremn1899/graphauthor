export type EscalationStatus =
  | "open"
  | "resolved"
  | "dismissed"
  | "deferred"
  | "intentional";

export type EscalationProvenance = {
  actor: string;
  source: string;
  askedAt: string;
};

export type EscalationHandoff = {
  id: string;
  ungovernedPredicate: string;
  question: string;
  provenance: EscalationProvenance;
  /** Optional inference to a Field region / concept id */
  graphRegionId?: string;
  createdAt: string;
  status: EscalationStatus;
  /** Optional future engine proposal */
  proposal?: string;
  resolvedNodeId?: string;
};
