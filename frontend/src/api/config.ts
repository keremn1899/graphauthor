/**
 * Runtime connect config — "point the UI at a local MCP host" and nothing more
 * (v1 scope caps onboarding there).
 *
 * Default mode is `fixture`: every lab page must stay runnable with no server.
 * Switch a page to the real backend with `?api=live` in the URL; the choice and
 * any host/token given alongside it persist to localStorage so a reload keeps
 * it. `?api=fixture` switches back.
 */

export type ApiMode = "fixture" | "live";

const LS_MODE = "graphauthor.apiMode";
const LS_BASE = "graphauthor.apiBase";
const LS_TOKEN = "graphauthor.apiToken";

function readLocal(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return ""; // private mode / storage disabled — fall through to defaults
  }
}

function writeLocal(key: string, value: string) {
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    /* non-fatal */
  }
}

/**
 * Query params live after the hash route (`#/graph?api=live`),
 * so `window.location.search` is usually empty — read both.
 */
function urlParams(): URLSearchParams {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  const fromHash = q >= 0 ? hash.slice(q + 1) : "";
  const merged = [window.location.search.replace(/^\?/, ""), fromHash]
    .filter(Boolean)
    .join("&");
  return new URLSearchParams(merged);
}

export type ApiConfig = {
  mode: ApiMode;
  /** Empty = same origin, which the vite dev proxy forwards to the local host. */
  baseUrl: string;
  token: string;
};

export function readApiConfig(): ApiConfig {
  const params = urlParams();

  const urlMode = params.get("api");
  if (urlMode === "live" || urlMode === "fixture") writeLocal(LS_MODE, urlMode);
  const urlBase = params.get("apiBase");
  if (urlBase !== null) writeLocal(LS_BASE, urlBase);
  const urlToken = params.get("apiToken");
  if (urlToken !== null) writeLocal(LS_TOKEN, urlToken);

  const stored = readLocal(LS_MODE);
  const envMode = import.meta.env.VITE_API_MODE as string | undefined;
  const mode: ApiMode =
    stored === "live" || stored === "fixture"
      ? stored
      : envMode === "live"
        ? "live"
        : "fixture";

  return {
    mode,
    baseUrl:
      readLocal(LS_BASE) ||
      (import.meta.env.VITE_API_BASE as string | undefined) ||
      "",
    token:
      readLocal(LS_TOKEN) ||
      (import.meta.env.VITE_API_TOKEN as string | undefined) ||
      "",
  };
}

/**
 * URL params are re-applied on every `readApiConfig()`, so a credential stored
 * afterwards would be reverted by the address bar on the very next request.
 * Once a credential is stored, drop it from the URL: the stored value is the
 * one that governs, and a token left in a URL outlives the session in history.
 *
 * `api=` is deliberately left alone — the mode is a route convention the
 * product's own links carry, not a credential.
 */
function stripUrlCredentials(names: string[]) {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  if (q < 0) return;
  const params = new URLSearchParams(hash.slice(q + 1));
  if (!names.some((name) => params.has(name))) return;
  for (const name of names) params.delete(name);
  const suffix = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${hash.slice(0, q)}${
      suffix ? `?${suffix}` : ""
    }`,
  );
}

export function setApiConfig(patch: Partial<ApiConfig>) {
  if (patch.mode) writeLocal(LS_MODE, patch.mode);
  if (patch.baseUrl !== undefined) writeLocal(LS_BASE, patch.baseUrl);
  if (patch.token !== undefined) writeLocal(LS_TOKEN, patch.token);
  const stripped: string[] = [];
  if (patch.baseUrl !== undefined) stripped.push("apiBase");
  if (patch.token !== undefined) stripped.push("apiToken");
  if (stripped.length) stripUrlCredentials(stripped);
}
