/**
 * Thin fetch wrapper over the local operator plane.
 *
 * The browser gets no new authority (v1 scope): it sends a bearer token the
 * operator already gates on and reads what the server chooses to return. It
 * never talks to a model provider and never holds a provider key.
 */

import { readApiConfig } from "./config";

export type FaultKind =
  | "not_found"
  | "invalid"
  | "conflict"
  | "unauthorized"
  | "unavailable"
  | "fault";

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  /** Backend envelope kind. Absent when the host never spoke (status 0). */
  readonly kind: FaultKind | null;

  constructor(
    status: number,
    body: unknown,
    message: string,
    kind: FaultKind | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.kind = kind;
  }

  /** The operator plane did not answer. The client authored this sentence. */
  get hostUnreachable(): boolean {
    return this.status === 0;
  }
}

const FAULT_KINDS = new Set<FaultKind>([
  "not_found",
  "invalid",
  "conflict",
  "unauthorized",
  "unavailable",
  "fault",
]);

function kindFrom(body: unknown): FaultKind | null {
  if (!body || typeof body !== "object" || !("kind" in body)) return null;
  const kind = (body as { kind: unknown }).kind;
  return typeof kind === "string" && FAULT_KINDS.has(kind as FaultKind)
    ? (kind as FaultKind)
    : null;
}

function messageFrom(status: number, body: unknown, path: string): string {
  if (body && typeof body === "object" && "error" in body) {
    const err = (body as { error: unknown }).error;
    if (typeof err === "string" && err) return err;
  }
  if (status === 401) return "This host did not accept the token.";
  if (status === 404) return `Not found: ${path}`;
  return `${path} failed (${status})`;
}

async function apiFetch<T>(
  path: string,
  init: RequestInit & { signal?: AbortSignal } = {},
): Promise<T> {
  const { baseUrl, token } = readApiConfig();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, { ...init, headers });
  } catch (cause) {
    if (init.signal?.aborted) throw cause; // caller cancelled — not a failure
    throw new ApiError(
      0,
      null,
      `Cannot reach the host at ${baseUrl || "this origin"}. Is it running?`,
    );
  }

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      body,
      messageFrom(response.status, body, path),
      kindFrom(body),
    );
  }
  return body as T;
}

export function postJson<T>(path: string, payload: unknown, signal?: AbortSignal) {
  return apiFetch<T>(path, {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  });
}

export function getJson<T>(path: string, signal?: AbortSignal) {
  return apiFetch<T>(path, { method: "GET", signal });
}
