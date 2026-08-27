/**
 * Human-readable protocol vocabulary.
 *
 * The product stays close to the engine: this layer removes transport syntax
 * (`.`, `_`, enum casing) without replacing recorded operations with product
 * copy. The raw value remains the technical label everywhere it is needed for
 * audit or support.
 */

const SIMPLE_EVENT_LABELS: Record<string, string> = {
  "graph.committed": "Graph committed",
  "graph.reverted": "Graph reverted",
};

const QUALIFIED_EVENT_LABELS: Record<string, Record<string, string>> = {
  "gate.completed": {
    green: "Gate passed",
    red: "Gate failed",
    encode_failed: "Gate encoding failed",
  },
  "proposal.dispositioned": {
    rejected: "Proposal rejected",
    requeued: "Proposal requeued",
    l1_demoted: "Proposal demoted to L1",
    grain_failed: "Proposal grain check failed",
    correction_refused: "Proposal correction refused",
    edge_convention_failed: "Proposal edge convention failed",
  },
};

const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  PENDING: "Pending",
  COMMITTED: "Committed",
  REJECTED: "Rejected",
  GRAIN_FAILED: "Grain check failed",
  GATE_FAILED: "Gate failed",
  ENCODE_FAILED: "Encoding failed",
};

const VERDICT_LABELS: Record<string, string> = {
  GOVERNED: "Governed",
  UNGOVERNED: "Ungoverned",
  ABSENT: "Absent from graph",
  CONFORMS: "Conforms",
  VIOLATES: "Violates",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
  INSUFFICIENT: "Insufficient evidence",
  CONFIRMED: "Answer confirmed",
  ALTERNATIVE: "Alternative found",
  EXHAUSTED: "Graph exhausted",
  ILL_POSED: "Question ill-posed",
  UNKNOWN_TO_GRAPH: "Unknown to graph",
  UNKNOWN: "Unknown",
};

const EDGE_TYPE_LABELS: Record<string, string> = {
  LEADSTO: "Leads to",
  CONTAINS: "Contains",
  EXPRESSES: "Expresses",
  NEARTO: "Near to",
};

/**
 * Why a gate refused a change, in words.
 *
 * These are the reason an operator is being asked to intervene, so they cannot
 * stay as a JSON blob — but they are also the record, so an unrecognised kind
 * is shown verbatim rather than smoothed into a generic sentence that would
 * misreport what the gate actually found.
 */
const GATE_FINDING_LABELS: Record<string, string> = {
  movement_toward_governed:
    "The change moved a query toward “governed” that the graph does not govern.",
  movement_toward_ungoverned:
    "The change moved a governed query toward “ungoverned”.",
  distractor_captured: "The change captured a query it should have left alone.",
  right_reason_lost: "A query still answers correctly, but for a different reason.",
  flaky: "The result did not reproduce across runs.",
};

export function gateFindingLabel(kind: string): string {
  return GATE_FINDING_LABELS[kind] ?? kind.replaceAll("_", " ");
}

const CONSTRUCTION_JOB_STATUS_LABELS: Record<string, string> = {
  pending: "Waiting to start",
  running: "Constructing",
  done: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
};

function words(value: string): string {
  return value
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .toLowerCase()
    .replace(/\bl(\d+)\b/g, "L$1");
}

function sentence(value: string): string {
  const phrase = words(value);
  return phrase ? phrase[0].toUpperCase() + phrase.slice(1) : "Activity recorded";
}

/**
 * The explicit label, or null when the type would fall through to the
 * mechanical sentence-case formatter. Labs use the null to mark copy that
 * has not been written yet.
 */
export function knownEventTypeLabel(eventType: string): string | null {
  const raw = String(eventType || "").trim();
  if (!raw) return null;
  const simple = SIMPLE_EVENT_LABELS[raw];
  if (simple) return simple;
  const [base, qualifier] = raw.split(":", 2);
  if (qualifier) return QUALIFIED_EVENT_LABELS[base]?.[qualifier] ?? null;
  return null;
}

/**
 * Present a recorded event one level above its wire value.
 *
 * Known events are explicit so semantic distinctions cannot drift through a
 * clever generic formatter. Unknown extensions remain visible and get only a
 * mechanical sentence-case fallback.
 */
export function eventTypeLabel(eventType: string): string {
  const raw = String(eventType || "").trim();
  if (!raw) return "Activity recorded";
  const known = knownEventTypeLabel(raw);
  if (known) return known;

  const [base, qualifier] = raw.split(":", 2);
  if (qualifier) {
    return `${sentence(base.replace(/\./g, " "))} — ${words(qualifier)}`;
  }
  return sentence(raw.replace(/\./g, " "));
}

/**
 * The B8 structural prior on an absence, in words.
 *
 * Advisory and said as advisory — these are guesses from graph shape, and the
 * layer that computes them insists on saying so. A label that sounded like a
 * verdict would be the product asserting what it explicitly does not know.
 */
const ABSENCE_PRIOR_LABELS: Record<string, string> = {
  likely_local: "probably a local choice — the graph does not model the subject",
  likely_material:
    "probably a real gap — the graph models the subject but rules on nothing",
  possible_retrieval_miss:
    "possibly a retrieval miss — the absence was never moat-confirmed",
  already_excluded: "already declared out of scope by an earlier disposition",
  declared_open:
    "declared a known open question — a decision is owed before acting on it",
  declared_conflict:
    "contradictory declarations — the graph both excludes this and calls it open",
};

export function absencePriorLabel(prior: string): string {
  return ABSENCE_PRIOR_LABELS[prior] ?? sentence(String(prior).replace(/_/g, " "));
}


/** Display-only label; proposal logic must continue to use the raw status. */
export function proposalStatusLabel(status: string): string {
  return PROPOSAL_STATUS_LABELS[status] ?? sentence(status);
}

/**
 * Keep the product's decisive words while removing enum casing and separators.
 * The raw verdict remains available to callers for audit labels and styling.
 */
export function verdictLabel(verdict: string): string {
  const raw = String(verdict || "UNKNOWN").trim();
  return VERDICT_LABELS[raw.toUpperCase()] ?? sentence(raw);
}

/*
 * `askStatusLine` and `askClaimText` used to live here.
 *
 * Both existed to launder one server-side interpreter's output for display:
 * mapping seven verdict spellings onto three phrases, and suppressing three
 * specific stale paragraphs the old Battalion emitted when it found nothing.
 * That second job is the tell -- a display helper that has to recognise
 * particular sentences is compensating for a producer it does not control.
 *
 * Removed with the Ask panel, 2026-08-25.
 */

/** Display name for one of the four canonical graph edge types. */
function edgeTypeLabel(edgeType: string): string {
  const raw = String(edgeType || "").trim();
  return EDGE_TYPE_LABELS[raw.toUpperCase()] ?? sentence(raw);
}

/**
 * Label shown on the graph. The recorded predicate is the name of the edge;
 * SST is the stroke underneath. When `includeType` is set, both are shown.
 */
export function edgeDisplayLabel(
  edgeType: string,
  detail = "",
  options?: { includeType?: boolean },
): string {
  const type = edgeTypeLabel(edgeType);
  const recorded = String(detail || "").trim();
  const predicate =
    recorded && recorded.toUpperCase() !== String(edgeType).toUpperCase()
      ? recorded
      : "";
  if (!predicate) return type;
  if (options?.includeType) return `${predicate} · ${type}`;
  return predicate;
}

/** Node name on the map: the format kind rides beside the label when present. */
export function nodeDisplayLabel(label: string, kind?: string): string {
  const name = String(label || "").trim();
  const formatKind = String(kind || "").trim();
  if (!formatKind) return name;
  if (!name) return formatKind;
  return `${name} · ${formatKind}`;
}

/** Read an edge as a grammatical statement without hiding its direction. */
export function edgeStatement(
  edgeType: string,
  source: string,
  target: string,
  predicate = "",
): string {
  const relation = String(predicate || "").trim();
  if (relation) return `${source} ${relation} ${target}`;
  if (String(edgeType).toUpperCase() === "NEARTO") {
    return `${source} is near to ${target}`;
  }
  return `${source} ${edgeTypeLabel(edgeType).toLowerCase()} ${target}`;
}

/** Display-only label; polling logic must continue to use the raw status. */
export function constructionJobStatusLabel(status: string): string {
  return CONSTRUCTION_JOB_STATUS_LABELS[status] ?? sentence(status);
}
