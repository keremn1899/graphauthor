/**
 * Settings — the panel that lets someone who is not the developer start this
 * product.
 *
 * Everything here was already reachable from a shell: the account plane has had
 * key storage, attribution and posture for a while, and none of it had a
 * surface. That made `.env` plus a backend restart the real onboarding path.
 *
 * Two things are deliberately *not* claimed on this panel:
 *
 *   The connect token authenticates the browser to a local operator host. It is
 *   not a login, and it grants the browser nothing the host does not already
 *   allow — so it is presented as a host address, not as an identity.
 *
 *   Posture is instruction, not permission. It tells an agent what is wanted;
 *   the write path decides what is allowed. Loosening it cannot grant authority.
 *
 * A third thing is not claimed because it is not this panel's job: the
 * product's look. Light and dark sit on the identity bar. Palette, type and
 * motion live in `styles/graphDna.ts`. This panel may change how *this screen*
 * reads a map (spacing, edge-type labels, dim spokes) and nothing that would
 * let two people on one host get two products. See chrome-constraints §3.11.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { readApiConfig, setApiConfig, type ApiMode } from "../api/config";
import { actionErrorMessage, invalidate, useResource } from "../api/resource";
import {
  clearProviderKey,
  fetchEntitlement,
  fetchMemory,
  fetchSettings,
  POSTURE_ACTIONS,
  savePosture,
  setActor,
  setProviderKey,
  type Posture,
  type PostureAction,
} from "../api/settings";
import {
  readGraphPrefs,
  SPACING_RANGE,
  spacingLabel,
  writeGraphPrefs,
  MONO_FACES,
  type MonoFace,
} from "./graphPrefs";
import { NoticeCard } from "./Notice";
import { useProductTheme, useSetProductTheme } from "./ProductShell";
import { usePresence } from "../styles/usePresence";
import "../styles/presence.css";
import "./SettingsPanel.css";

const POSTURE_FIELDS: {
  id: keyof Pick<
    Posture,
    "on_ungoverned" | "on_insufficient_evidence" | "on_violates"
  >;
  label: string;
  note: string;
}[] = [
  {
    id: "on_ungoverned",
    label: "When the graph does not cover it",
    note: "A missing coverage is an answer, not a failure. Escalating puts it in front of you rather than letting an agent invent the missing rule.",
  },
  {
    id: "on_insufficient_evidence",
    label: "When the evidence is insufficient",
    note: "“I cannot tell” is the one case where guessing is worst.",
  },
  {
    id: "on_violates",
    label: "When the graph says it violates",
    note: "A decision the graph actually made.",
  },
];

const POSTURE_ACTION_LABEL: Record<PostureAction, string> = {
  escalate: "Bring it to me",
  propose: "Propose a change",
  stop: "Stop",
  proceed: "Continue",
};

function whenChecked(iso: string): string {
  if (!iso) return "not checked";
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "not checked";
  return `checked ${new Date(at).toLocaleDateString()}`;
}

function mib(bytes: number): string {
  if (!bytes) return "0 MiB";
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function SettingsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const config = readApiConfig();
  const live = config.mode === "live";
  const theme = useProductTheme();
  const setTheme = useSetProductTheme();

  const account = useResource(
    async (signal) => {
      const [settings, entitlement] = await Promise.all([
        fetchSettings(signal),
        fetchEntitlement(signal),
      ]);
      return { settings, entitlement };
    },
    {
      enabled: open && live,
      watch: "account",
      fallbackError: "Could not read settings from the host.",
    },
  );

  const memoryRead = useResource(
    (signal) => fetchMemory(signal),
    {
      enabled: open && live,
      watch: "account",
      fallbackError: "Could not read memory.",
    },
  );

  const [prefs, setPrefs] = useState(() => readGraphPrefs());
  const [keyInput, setKeyInput] = useState("");
  const [validateKey, setValidateKey] = useState(true);
  const [actor, setActorInput] = useState("");
  const [posture, setPostureDraft] = useState<Posture | null>(null);
  const [token, setToken] = useState(config.token);
  const [host, setHost] = useState(config.baseUrl);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");

  const settings = account.data?.settings;

  // Re-seed from the server after every successful read, including the reads
  // our own saves trigger — the stored record is the one that is true.
  useEffect(() => {
    if (!settings) return;
    setActorInput(settings.actor);
    setPostureDraft(settings.posture);
  }, [settings]);

  useEffect(() => {
    if (!open) return;
    setNotice("");
    setFailure("");
    setKeyInput("");
    const next = readApiConfig();
    setToken(next.token);
    setHost(next.baseUrl);
  }, [open]);

  const dialogRef = useRef<HTMLElement | null>(null);
  /** Held across renders so a new `onClose` identity cannot re-capture it. */
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  /**
   * Keyboard containment, because the panel already claims it.
   *
   * `aria-modal="true"` tells a screen reader that everything outside this
   * element is inert. It was not: Tab walked straight out of the dialog and
   * into the header and the map behind it, focus never entered the panel when
   * it opened, and closing it dropped focus onto `<body>` — so an operator who
   * opened Settings from the keyboard had to Tab back through the whole
   * product to reach the button they started from.
   *
   * A claim the markup makes and the behaviour does not keep is the same
   * defect as a label too small to read, one layer down.
   */
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    // Whoever opened it gets it back — captured once, on the way in.
    //
    // `onClose` is an inline arrow in the shell, so it has a new identity on
    // every parent render and this effect re-runs constantly. Capturing the
    // opener as a local meant re-capturing `document.activeElement` each time,
    // which by then was the close button *inside* the dialog: cleanup then
    // "restored" focus to an element React had just unmounted, and focus went
    // nowhere. Held in a ref and set only on the false→true edge.
    openerRef.current =
      openerRef.current ?? (document.activeElement as HTMLElement | null);

    const focusables = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((el) => el.offsetParent !== null);

    // The close button rather than the first field: landing on a text input
    // invites typing into a panel you have only just opened, and the first
    // thing a keyboard operator wants to know is how to leave.
    const first = dialog?.querySelector<HTMLElement>(".settings__head button");
    first?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return;
      const edge = event.shiftKey ? items[0] : items[items.length - 1];
      // Only the edges are redirected; everything between them is the
      // browser's own order, which is the one thing never worth reimplementing.
      if (document.activeElement === edge || !dialog?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? items[items.length - 1] : items[0]).focus();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      // Restore only when the close left focus nowhere.
      //
      // The obvious test — "is focus still inside the panel" — is always false
      // here: React has already unmounted the dialog by the time cleanup runs,
      // so the element is detached and focus has fallen to `<body>`. Checking
      // it silently skipped every restore, which looked like working code and
      // left the operator on body after Escape.
      //
      // Body (or nothing) means the panel took focus down with it. Anything
      // else means the operator clicked their way somewhere deliberately, and
      // dragging them back to the Settings button would be the rudest possible
      // response to that.
      const landed = document.activeElement;
      const inside =
        dialog != null &&
        landed instanceof Node &&
        dialog.contains(landed);
      if (!landed || landed === document.body || inside) {
        openerRef.current?.focus?.();
      }
      openerRef.current = null;
    };
    // Deliberately only `open`: see the opener note above. `onClose` is read
    // through a ref so its identity cannot retrigger this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const act = useCallback(
    async (name: string, run: () => Promise<unknown>, success: string) => {
      setBusy(name);
      setFailure("");
      setNotice("");
      try {
        await run();
        setNotice(success);
        invalidate("account");
      } catch (cause) {
        setFailure(actionErrorMessage(cause));
      } finally {
        setBusy("");
      }
    },
    [],
  );

  const presence = usePresence(open);

  if (!presence.mounted) return null;

  const keyStatus = settings?.key;
  const postureChanged =
    posture && settings ? JSON.stringify(posture) !== JSON.stringify(settings.posture) : false;

  return (
    <div
      className={`settings-scrim motion-layer motion-layer--fade${presence.shown ? " is-in" : ""}`}
      onMouseDown={onClose}
    >
      <aside
        ref={dialogRef}
        className={`settings motion-layer motion-layer--dock-right${presence.shown ? " is-in" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-heading"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="settings__head">
          <h2 id="settings-heading">Settings</h2>
          <button type="button" onClick={onClose} aria-label="Close settings">
            ×
          </button>
        </header>

        <section className="settings__section">
          <h3>Connect</h3>
          <p className="settings__note">
            The local host this browser talks to. It holds no credential of its
            own beyond the token that host already gates on. These settings are
            stored in this browser only.
          </p>
          <label className="settings__field">
            <span>Host address</span>
            <input
              value={host}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setHost(event.target.value)}
              placeholder="same origin — leave blank"
            />
          </label>
          <label className="settings__field">
            <span>Connect token</span>
            <input
              type="password"
              value={token}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setToken(event.target.value)}
              placeholder="the host's bearer token"
            />
          </label>
          <div className="settings__actions">
            <button
              type="button"
              disabled={token === config.token && host === config.baseUrl}
              onClick={() => {
                setApiConfig({ token, baseUrl: host });
                setNotice("Connection stored. It is used from the next request.");
                setFailure("");
                void account.refresh();
              }}
            >
              Use this connection
            </button>
          </div>
          <label className="settings__field">
            <span>Data</span>
            <select
              value={config.mode}
              onChange={(event) => {
                setApiConfig({ mode: event.target.value as ApiMode });
                window.location.reload();
              }}
            >
              <option value="live">Live — the running host</option>
              <option value="fixture">Fixture — no host needed</option>
            </select>
            <em>
              Fixture keeps the lab pages runnable with no server. Switching
              reloads the page.
            </em>
          </label>
          {!live ? (
            <p className="settings__callout">
              This page is not talking to a host. Settings need a live
              connection.
            </p>
          ) : null}
        </section>

        {live ? (
          <>
            <section className="settings__section">
              <h3>Provider key</h3>
              <p className="settings__note">
                Your own OpenRouter key, encrypted at rest by the host and
                used when a construction spends against a model. The key is
                never sent back to this browser.
              </p>
              {account.loading ? (
                <p className="settings__status">Reading account…</p>
              ) : keyStatus?.set ? (
                <p className="settings__status">
                  <code>{keyStatus.masked || "stored"}</code>
                  <span>
                    {keyStatus.valid ? "validated" : "stored, not validated"} ·{" "}
                    {whenChecked(keyStatus.last_validated)}
                  </span>
                </p>
              ) : (
                <p className="settings__status settings__status--empty">
                  No key stored. Construction cannot run without one.
                </p>
              )}
              <label className="settings__field">
                <span>{keyStatus?.set ? "Replace key" : "Key"}</span>
                <input
                  type="password"
                  value={keyInput}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => setKeyInput(event.target.value)}
                  placeholder="sk-or-v1-…"
                />
              </label>
              <label className="settings__check">
                <input
                  type="checkbox"
                  checked={validateKey}
                  onChange={(event) => setValidateKey(event.target.checked)}
                />
                <span>
                  Check the key with OpenRouter first. A key that fails is
                  refused, not stored.
                </span>
              </label>
              <div className="settings__actions">
                <button
                  type="button"
                  className="is-primary"
                  disabled={!keyInput.trim() || Boolean(busy)}
                  onClick={() =>
                    void act(
                      "key",
                      async () => {
                        await setProviderKey(keyInput.trim(), validateKey);
                        setKeyInput("");
                      },
                      validateKey ? "Key validated and stored." : "Key stored.",
                    )
                  }
                >
                  {busy === "key" ? "Storing…" : "Store key"}
                </button>
                {keyStatus?.set ? (
                  <button
                    type="button"
                    disabled={Boolean(busy)}
                    onClick={() =>
                      void act(
                        "clear",
                        clearProviderKey,
                        "Key cleared here and in the running host.",
                      )
                    }
                  >
                    {busy === "clear" ? "Clearing…" : "Clear key"}
                  </button>
                ) : null}
              </div>
            </section>

            <section className="settings__section">
              <h3>Attribution</h3>
              <p className="settings__note">
                The name recorded when you confirm, reject or acknowledge
                something.
              </p>
              <label className="settings__field">
                <span>Actor</span>
                <input
                  value={actor}
                  spellCheck={false}
                  onChange={(event) => setActorInput(event.target.value)}
                  placeholder="your name"
                />
              </label>
              <div className="settings__actions">
                <button
                  type="button"
                  disabled={
                    Boolean(busy) ||
                    !actor.trim() ||
                    actor === settings?.actor
                  }
                  onClick={() =>
                    void act(
                      "actor",
                      () => setActor(actor.trim()),
                      "Attribution saved.",
                    )
                  }
                >
                  {busy === "actor" ? "Saving…" : "Save actor"}
                </button>
              </div>
            </section>

            <section className="settings__section">
              <h3>When an agent is stuck</h3>
              <p className="settings__note">
                What you want an agent to do when it reaches one of these
                answers. Instruction only: loosening it cannot grant an agent
                authority the write path does not already allow.
              </p>
              {posture ? (
                <>
                  {POSTURE_FIELDS.map((field) => (
                    <label className="settings__field" key={field.id}>
                      <span>{field.label}</span>
                      <select
                        value={posture[field.id]}
                        onChange={(event) =>
                          setPostureDraft({
                            ...posture,
                            [field.id]: event.target.value as PostureAction,
                          })
                        }
                      >
                        {POSTURE_ACTIONS.map((action) => (
                          <option key={action} value={action}>
                            {POSTURE_ACTION_LABEL[action]}
                          </option>
                        ))}
                      </select>
                      <em>{field.note}</em>
                    </label>
                  ))}
                  <label className="settings__field">
                    <span>Highest claim an agent may propose</span>
                    <select
                      value={posture.max_claim_level}
                      onChange={(event) =>
                        setPostureDraft({
                          ...posture,
                          max_claim_level: event.target.value as "L0" | "L1",
                        })
                      }
                    >
                      <option value="L0">L0 — describes the source</option>
                      <option value="L1">L1 — asserts beyond it</option>
                    </select>
                  </label>
                  <label className="settings__field">
                    <span>Notes to agents</span>
                    <textarea
                      rows={3}
                      value={posture.notes}
                      onChange={(event) =>
                        setPostureDraft({ ...posture, notes: event.target.value })
                      }
                      placeholder="Free text an agent reads when it orients."
                    />
                  </label>
                  <div className="settings__actions">
                    <button
                      type="button"
                      disabled={Boolean(busy) || !postureChanged}
                      onClick={() =>
                        void act(
                          "posture",
                          () => savePosture(posture),
                          "Instruction saved.",
                        )
                      }
                    >
                      {busy === "posture" ? "Saving…" : "Save"}
                    </button>
                    {postureChanged && settings ? (
                      <button
                        type="button"
                        disabled={Boolean(busy)}
                        onClick={() => setPostureDraft(settings.posture)}
                      >
                        Discard
                      </button>
                    ) : null}
                  </div>
                </>
              ) : account.loading ? (
                <p className="settings__status">Reading instruction…</p>
              ) : null}
            </section>

            {account.data ? (
              <section className="settings__section">
                <h3>Plan</h3>
                <dl className="settings__facts">
                  <div>
                    <dt>Plan</dt>
                    <dd>{account.data.entitlement.plan || "—"}</dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>
                      {account.data.entitlement.entitled ? "active" : "inactive"}
                    </dd>
                  </div>
                </dl>
                <p className="settings__note">
                  Local single-tenant install. Model spend is billed by your
                  provider against the key above, not by this product.
                </p>
              </section>
            ) : null}
          </>
        ) : null}

        {/* Outside the `live` branch on purpose: how this browser draws a map
            is true whether or not it is talking to a host, and the fixture
            pages draw maps too. */}
        <section className="settings__section">
          <h3>This screen</h3>
          <p className="settings__note">
            How this browser draws a map. Nothing here changes what the graph
            says, where the server placed a node, or what an edge asserts — the
            node reader still names every relation in full.
          </p>
          <p className="settings__note">
            These choices are local to this browser. The appearance toggle on
            the identity bar and the select below write the same stored value.
          </p>

          <label className="settings__field">
            <span>Appearance</span>
            <select
              value={theme}
              onChange={(event) => {
                setTheme(event.target.value as "light" | "dark");
              }}
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
            <em>Also on the identity bar.</em>
          </label>

          <label className="settings__field">
            <span>Room between nodes · {spacingLabel(prefs.spacing)}</span>
            <input
              type="range"
              min={SPACING_RANGE.min}
              max={SPACING_RANGE.max}
              step={SPACING_RANGE.step}
              value={prefs.spacing}
              onChange={(event) =>
                setPrefs(writeGraphPrefs({ spacing: Number(event.target.value) }))
              }
            />
          </label>
          <p className="settings__note settings__note--tight">
            Added on top of the spacing the arrangement already guarantees. It
            only goes up: drawing nodes closer than the server placed them is
            how maps came to overlap in the first place.
          </p>

          <label className="settings__field">
            <span>Mono beside Jost</span>
            <select
              value={prefs.mono}
              onChange={(event) =>
                setPrefs(
                  writeGraphPrefs({
                    mono: event.target.value as MonoFace,
                  }),
                )
              }
            >
              {MONO_FACES.map((face) => (
                <option key={face.id} value={face.id}>
                  {face.label}
                </option>
              ))}
            </select>
            <em>
              {
                MONO_FACES.find((face) => face.id === prefs.mono)?.note
              }
            </em>
          </label>

          <label className="settings__toggle">
            <input
              type="checkbox"
              checked={prefs.edgeTypeLabels}
              onChange={(event) =>
                setPrefs(
                  writeGraphPrefs({ edgeTypeLabels: event.target.checked }),
                )
              }
            />
            <span>
              Name each edge's type on the map
              <em>
                The recorded predicate is already the label. This adds the
                geometry name — Contains, Leads to — beside it.
              </em>
            </span>
          </label>

          <label className="settings__toggle">
            <input
              type="checkbox"
              checked={prefs.dimSpokes}
              onChange={(event) =>
                setPrefs(writeGraphPrefs({ dimSpokes: event.target.checked }))
              }
            />
            <span>
              Draw hub spokes quietly
              <em>
                The edges from a packed root to its branches are the largest
                single source of crossings and carry the least. Turn this off on
                a graph that genuinely is a star, where they are the structure.
              </em>
            </span>
          </label>
        </section>

        {/* Read-only: how the host process is holding memory. This is the only
            place /operator/memory is surfaced. Live-only — there is no host to
            ask in fixture mode. */}
        {live ? (
          <section className="settings__section">
            <h3>Diagnostics</h3>
            <p className="settings__note">
              The host process's memory, read now. RSS is the truth; the Python
              heap is the part tracemalloc can attribute.
            </p>
            {memoryRead.loading ? (
              <p className="settings__status">Reading memory…</p>
            ) : memoryRead.data ? (
              <>
                <dl className="settings__facts">
                  <div>
                    <dt>RSS</dt>
                    <dd>{mib(memoryRead.data.rss_bytes)}</dd>
                  </div>
                  <div>
                    <dt>Peak</dt>
                    <dd>{mib(memoryRead.data.peak_rss_bytes)}</dd>
                  </div>
                  <div>
                    <dt>Python heap</dt>
                    <dd>{mib(memoryRead.data.python_traced_bytes)}</dd>
                  </div>
                  <div>
                    <dt>Graphs open</dt>
                    <dd>{memoryRead.data.ladybug_opens}</dd>
                  </div>
                </dl>
                {memoryRead.data.python_top.length ? (
                  <table className="settings__mem">
                    <tbody>
                      {memoryRead.data.python_top.slice(0, 6).map((row, i) => (
                        <tr key={i}>
                          <td>{mib(row.size)}</td>
                          <td>
                            <code>
                              {row.file.split("/").pop() || row.file}:{row.line}
                            </code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="settings__note settings__note--tight">
                    tracemalloc is not running on this host.
                  </p>
                )}
              </>
            ) : null}
          </section>
        ) : null}

        {account.error && !account.hostUnreachable ? (
          <NoticeCard kind="fault" body={account.error} />
        ) : null}
        {failure ? <NoticeCard kind="fault" body={failure} /> : null}
        {notice ? (
          <p className="settings__notice" role="status">
            {notice}
          </p>
        ) : null}
      </aside>
    </div>
  );
}
