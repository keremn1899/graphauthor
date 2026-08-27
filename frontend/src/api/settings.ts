/**
 * `/operator/settings` — the account plane.
 *
 * Until now the only way to give this product a provider key was to write
 * `.env` and restart the backend, which meant the product could not be started
 * by anyone who was not also its developer. The backend has had the whole path
 * for a while (`mcp_server/account.py`): validated on entry, encrypted at rest,
 * applied to the running process so the next model-backed operation uses it without a restart.
 *
 * The key is write-only across this boundary. Every response carries status —
 * `set`, `valid`, a fingerprint and a mask — and never the secret, so there is
 * no client code that could leak it because there is no client code that holds
 * it.
 *
 * Backend authority: `mcp_server/operator_http.py`, `mcp_server/account.py`.
 */

import { ApiError, getJson, postJson } from "./client";

/** What an agent should do when the graph gives it no answer. Advisory. */
export type PostureAction = "escalate" | "propose" | "stop" | "proceed";

export const POSTURE_ACTIONS: PostureAction[] = [
  "escalate",
  "propose",
  "stop",
  "proceed",
];

export type Posture = {
  on_ungoverned: PostureAction;
  on_insufficient_evidence: PostureAction;
  on_violates: PostureAction;
  max_claim_level: "L0" | "L1";
  notes: string;
};

/** Key METADATA. The key itself never crosses this boundary. */
export type KeyStatus = {
  set: boolean;
  valid: boolean;
  last_validated: string;
  fingerprint: string;
  masked: string;
  /** Present on a refusal — the validator's verdict, e.g. `http_401`. */
  detail?: string;
};

export type AccountSettings = {
  account_id: string;
  actor: string;
  posture: Posture;
  subscription: { active: boolean; plan: string; since: string; updated?: string };
  model_prefs: Record<string, unknown>;
  key: KeyStatus;
};

export type Entitlement = {
  entitled: boolean;
  active?: boolean;
  plan?: string;
  since?: string;
};

export function fetchSettings(signal?: AbortSignal) {
  return getJson<AccountSettings>("/operator/settings", signal);
}

export function fetchEntitlement(signal?: AbortSignal) {
  return getJson<Entitlement>("/operator/entitlement", signal);
}

/** RSS + the Python-side tracemalloc top. Read-only; surfaced only in Settings. */
export type MemorySnapshot = {
  pid: number;
  uptime_s: number;
  rss_bytes: number;
  peak_rss_bytes: number;
  python_traced_bytes: number;
  python_peak_bytes: number;
  tracing: boolean;
  gc: number[];
  ladybug_opens: number;
  python_top: { size: number; count: number; file: string; line: number }[];
  log: string;
  ts: number;
};

export function fetchMemory(signal?: AbortSignal) {
  return getJson<MemorySnapshot>("/operator/memory", signal);
}

/**
 * The validator's verdict, said in words. `detail` is a protocol token — an
 * operator who pasted the wrong key needs to be told that, not shown `http_401`.
 */
function providerKeyRefusal(detail: string): string {
  if (detail === "http_401" || detail === "http_403") {
    return "OpenRouter rejected that key. It has not been stored.";
  }
  if (detail.startsWith("unreachable")) {
    return "Could not reach OpenRouter to check the key. Check the connection, or save it without validating.";
  }
  if (detail.startsWith("http_")) {
    return `OpenRouter answered ${detail.slice(5)} when checking the key. It has not been stored.`;
  }
  return "That key was refused and has not been stored.";
}

/**
 * Store the operator's own OpenRouter key.
 *
 * `validate` sends a cheap authenticated ping first; a key that fails is
 * refused rather than stored, so a typo cannot sit in the account file looking
 * configured until the next build fails. Validation needs the network — turn it
 * off to store a key while offline.
 */
export async function setProviderKey(
  key: string,
  validate = true,
): Promise<KeyStatus> {
  try {
    return await postJson<KeyStatus>("/operator/settings/key", { key, validate });
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 400) {
      const body = cause.body as { detail?: string } | null;
      throw new Error(providerKeyRefusal(String(body?.detail ?? "")));
    }
    throw cause;
  }
}

/** Drops the stored key *and* the running process's copy of it. */
export function clearProviderKey() {
  return postJson<KeyStatus>("/operator/settings/key/clear", {});
}

/** Who the ledger records as having acted. */
export function setActor(actor: string) {
  return postJson<{ actor: string }>("/operator/settings/actor", { actor });
}

/**
 * Posture is instruction to agents, not permission: the write path decides what
 * is allowed, and loosening posture cannot grant an agent authority it does not
 * already have. The backend refuses unknown fields rather than silently
 * discarding them, so a typo surfaces as an error instead of a policy the
 * operator believes they set.
 */
export function savePosture(patch: Partial<Posture>) {
  return postJson<{ posture: Posture }>("/operator/settings/posture", patch);
}
