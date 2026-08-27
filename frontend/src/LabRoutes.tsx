/**
 * Every lab page, behind one dynamic import.
 *
 * These used to be thirteen `lazy()` declarations at the top of `App.tsx`.
 * Lazy is not the same as absent: each one still emitted a chunk, and the labs
 * are the bulk of the tree — 110 of 193 modules — so a shipped product carried
 * a whole design studio it never routes to.
 *
 * Collapsing them behind a single import lets the build drop the lot. `App`
 * reaches this module only inside `if (LAB_ENABLED)`, and `LAB_ENABLED` is
 * `import.meta.env.DEV`, which Vite replaces with a literal `false` in a
 * production build — so the branch is statically dead and Rollup takes this
 * module and everything it reaches with it.
 *
 * The labs stay exactly as they are and stay reachable in development. This
 * changes what ships, not what exists.
 */

import { lazy, type ComponentType } from "react";

export type LabRoute =
  | "explorations"
  | "ledger-feed"
  | "graph-map"
  | "canvas-linkage"
  | "ambient-canvas"
  | "graph-animations"
  | "graph-dna"
  | "graph-dna-motion"
  | "ledger-dna"
  | "arrangement"
  | "notices"
  | "events";

const ExplorationsIndex = lazy(() =>
  import("./explorations/ExplorationsIndex").then((module) => ({
    default: module.ExplorationsIndex,
  })),
);
const LedgerFeedLabPage = lazy(() =>
  import("./explorations/lab/LedgerFeedLabPage").then((module) => ({
    default: module.LedgerFeedLabPage,
  })),
);
const GraphMapLabPage = lazy(() =>
  import("./explorations/lab/GraphMapLabPage").then((module) => ({
    default: module.GraphMapLabPage,
  })),
);
const CanvasLinkageLabPage = lazy(() =>
  import("./explorations/lab/CanvasLinkageLabPage").then((module) => ({
    default: module.CanvasLinkageLabPage,
  })),
);
const AmbientCanvasLabPage = lazy(() =>
  import("./explorations/lab/AmbientCanvasLabPage").then((module) => ({
    default: module.AmbientCanvasLabPage,
  })),
);
const GraphAnimationsLabPage = lazy(() =>
  import("./explorations/lab/GraphAnimationsLabPage").then((module) => ({
    default: module.GraphAnimationsLabPage,
  })),
);
const ArrangementLabPage = lazy(() =>
  import("./explorations/lab/ArrangementLabPage").then((module) => ({
    default: module.ArrangementLabPage,
  })),
);
const NoticeLabPage = lazy(() =>
  import("./explorations/lab/NoticeLabPage").then((module) => ({
    default: module.NoticeLabPage,
  })),
);
const EventLabPage = lazy(() =>
  import("./explorations/lab/EventLabPage").then((module) => ({
    default: module.EventLabPage,
  })),
);
const GraphDnaWorkbenchPage = lazy(() =>
  import("./explorations/GraphDnaWorkbenchPage").then((module) => ({
    default: module.GraphDnaWorkbenchPage,
  })),
);
const GraphDnaMotionLabPage = lazy(() =>
  import("./explorations/lab/GraphDnaMotionLabPage").then((module) => ({
    default: module.GraphDnaMotionLabPage,
  })),
);
const LedgerDnaWorkbenchPage = lazy(() =>
  import("./explorations/LedgerDnaWorkbenchPage").then((module) => ({
    default: module.LedgerDnaWorkbenchPage,
  })),
);
const PAGES: Record<LabRoute, ComponentType> = {
  explorations: ExplorationsIndex,
  "ledger-feed": LedgerFeedLabPage,
  "graph-map": GraphMapLabPage,
  "canvas-linkage": CanvasLinkageLabPage,
  "ambient-canvas": AmbientCanvasLabPage,
  "graph-animations": GraphAnimationsLabPage,
  "graph-dna": GraphDnaWorkbenchPage,
  "graph-dna-motion": GraphDnaMotionLabPage,
  "ledger-dna": LedgerDnaWorkbenchPage,
  arrangement: ArrangementLabPage,
  notices: NoticeLabPage,
  events: EventLabPage,
};

/**
 * One component, because `App` has to reach the labs through a single dynamic
 * import for the build to be able to drop them. A function returning JSX would
 * have to be imported statically, which is the thing this file exists to
 * avoid.
 */
export function LabHost({ route }: { route: LabRoute }) {
  const Page = PAGES[route] ?? ExplorationsIndex;
  return <Page />;
}
