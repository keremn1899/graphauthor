import "./ExplorationsIndex.css";

const LINKS = [
  {
    href: "#/explorations/notices",
    label: "Notice specimens",
    note: "Temporary — block, dock, and inline cards without failing the host",
  },
  {
    href: "#/explorations/events",
    label: "Event specimens",
    note: "Temporary — remaining write-path types as a filled Logs page",
  },
  {
    href: "#/explorations/graph-dna?api=live&apiToken=devtoken",
    label: "Graph DNA",
    note: "Product Graph page + overlays, with Radix look parameters (no motion)",
  },
  {
    href: "#/explorations/graph-dna-motion?api=live&apiToken=devtoken",
    label: "Graph DNA motion lab",
    note: "Saved animated DNA specimen — drag, hover, gravity, orbit",
  },
  {
    href: "#/explorations/ledger-dna",
    label: "Ledger DNA workbench",
    note: "Tune operator attention, arc anatomy, stable inspection, and motion",
  },
  {
    href: "#/explorations/arrangement?api=live&apiToken=devtoken",
    label: "Arrangement",
    note: "Server-decided layout — lenses, regions, gap gutter, quality metrics",
  },
  {
    href: "#/explorations/graph-map",
    label: "Graph map",
    note: "Live graph catalogue + committed map data path",
  },
  {
    href: "#/explorations/ledger-feed",
    label: "Ledger feed",
    note: "Review — activities, proposals, confirm / reject / requeue",
  },
  {
    href: "#/explorations/canvas-linkage",
    label: "Canvas linkage",
    note: "Screen 2 graph half — focus, proposal overlay, version diff",
  },
  {
    href: "#/explorations/ambient-canvas",
    label: "Ambient canvas",
    note: "Ask / ambient graph",
  },
  {
    href: "#/explorations/graph-animations",
    label: "Graph animations",
    note: "A/B on ambient hover bond, charcoal focus, linkage edges",
  },
];

export function ExplorationsIndex() {
  return (
    <main className="explorations-index">
      <header className="explorations-index__header">
        <p>Workshop</p>
        <h1>Explorations</h1>
        <span>
          Design and interaction studies. The working product lives in{" "}
          <a href="#/graph?api=live">Graph</a>.
        </span>
      </header>
      <ul className="explorations-index__list">
        {LINKS.map((l) => (
          <li key={l.href}>
            <a href={l.href}>{l.label}</a>
            <span>{l.note}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
