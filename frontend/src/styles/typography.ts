/**
 * App typography tokens — change once here (and matching CSS vars in base.css).
 *
 * CSS:  font-family: var(--font-sans) | var(--font-mono)
 *  JS/G6: FONT_SANS_FAMILY | FONT_MONO_FAMILY
 *
 * Mono is a trial against Jost. Flip `FONT_MONO` to another loaded id, or
 * pick one in Settings → This screen. Loaded faces: dm, plex, space.
 */
export const FONT_SANS_FAMILY =
  'Jost, "Helvetica Neue", Helvetica, sans-serif';

const FONT_MONO_STACK = "ui-monospace, Menlo, Consolas, monospace";

export const FONT_MONO_TRIALS = {
  dm: {
    name: "DM Mono",
    note: "Geometric, same construction as Jost. Quiet at small sizes.",
  },
  plex: {
    name: "IBM Plex Mono",
    note: "Humanist, a little softer than Jost.",
  },
  space: {
    name: "Space Mono",
    note: "Also geometric, more ink and character. Louder in a tag.",
  },
} as const;

export type FontMonoId = keyof typeof FONT_MONO_TRIALS;

/** The mono in use. Change this to try another loaded face. */
export const FONT_MONO: FontMonoId = "dm";

export function fontMonoFamily(id: FontMonoId = FONT_MONO): string {
  return `"${FONT_MONO_TRIALS[id].name}", ${FONT_MONO_STACK}`;
}

export const FONT_MONO_FAMILY = fontMonoFamily(FONT_MONO);

/** Default G6 node label face — keep in sync with FONT_SANS_FAMILY. */
export const FONT_NODE_LABEL_FAMILY = FONT_SANS_FAMILY;
