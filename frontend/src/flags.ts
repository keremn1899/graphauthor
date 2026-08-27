/**
 * Build-time flags. Small on purpose, and imported by everything that needs
 * one, so nothing has to reach into a lab module to ask whether labs exist.
 */

/**
 * Whether the design labs are part of this build.
 *
 * `import.meta.env.DEV` is replaced by Vite with a literal `true`/`false`, so
 * this is a constant at build time rather than a runtime check. That is what
 * lets the production bundle drop the lab tree entirely instead of merely
 * never routing to it — and it is why this must not become a runtime toggle
 * without someone deciding they want 110 extra modules shipped.
 */
export const LAB_ENABLED = import.meta.env.DEV;
