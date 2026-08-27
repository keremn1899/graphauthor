import { useCallback, useEffect, useRef } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
} from "d3-force";
import type { EdgeKind } from "../../../primitives/edge/types";
import {
  type SimLink,
  type SimNode,
} from "../data/trialGraph";
import {
  ALPHA_DECAY,
  ALPHA_MIN,
  REHEAT_ALPHA,
  VELOCITY_DECAY,
  chargeStrength,
  collideRadius,
  linkDistance,
  linkStrength,
  linksForLens,
} from "./forceConfig";

type ForceLink = SimulationLinkDatum<SimNode> & SimLink;

type UseForceLayoutArgs = {
  nodes: SimNode[];
  links: SimLink[];
  lens: EdgeKind;
  onTick: (nodes: SimNode[]) => void;
  reducedMotion: boolean;
};

function resolveId(end: string | SimNode): string {
  return typeof end === "string" ? end : end.id;
}

export function useForceLayout({
  nodes,
  links,
  lens,
  onTick,
  reducedMotion,
}: UseForceLayoutArgs) {
  const simRef = useRef<Simulation<SimNode, ForceLink> | null>(null);
  const nodesRef = useRef(nodes);
  const linksRef = useRef(links);
  const onTickRef = useRef(onTick);
  const settledPinnedRef = useRef(false);

  nodesRef.current = nodes;
  linksRef.current = links;
  onTickRef.current = onTick;

  const pinSettled = useCallback((list: SimNode[]) => {
    for (const n of list) {
      if (n.kind === "mass" && n.certainty >= 0.75 && n.fx == null) {
        n.fx = n.x;
        n.fy = n.y;
      }
      // Intended gaps are settled absence — pin them calm
      if (n.kind === "gap" && n.gapData?.kind === "intended" && n.fx == null) {
        n.fx = n.x;
        n.fy = n.y;
      }
    }
    settledPinnedRef.current = true;
  }, []);

  const unpinAllMasses = useCallback((list: SimNode[]) => {
    for (const n of list) {
      if (n.kind === "gap" && n.gapData?.kind === "intended") continue;
      n.fx = null;
      n.fy = null;
    }
    settledPinnedRef.current = false;
  }, []);

  const rebuild = useCallback(() => {
    const current = nodesRef.current.map((n) => ({ ...n }));
    const lensLinks = linksForLens(linksRef.current, lens).map((l) => ({
      ...l,
      source: resolveId(l.source),
      target: resolveId(l.target),
    }));

    simRef.current?.stop();

    const sim = forceSimulation<SimNode, ForceLink>(current)
      .force(
        "charge",
        forceManyBody<SimNode>().strength((d) => chargeStrength(d)),
      )
      .force(
        "link",
        forceLink<SimNode, ForceLink>(lensLinks as ForceLink[])
          .id((d) => d.id)
          .distance((l) => linkDistance(l as SimLink))
          .strength((l) => linkStrength(l as SimLink)),
      )
      .force(
        "collide",
        forceCollide<SimNode>().radius((d) => collideRadius(d)).strength(0.9),
      )
      .force("center", forceCenter(520, 340).strength(0.04))
      .velocityDecay(VELOCITY_DECAY)
      .alphaDecay(ALPHA_DECAY)
      .alphaMin(ALPHA_MIN);

    if (reducedMotion) {
      // Jump to settled layout without visible drift
      sim.alpha(1);
      for (let i = 0; i < 120; i++) sim.tick();
      pinSettled(current);
      onTickRef.current(current.map((n) => ({ ...n })));
      sim.stop();
      simRef.current = sim;
      return;
    }

    settledPinnedRef.current = false;
    sim.on("tick", () => {
      const list = sim.nodes();
      if (sim.alpha() < 0.02 && !settledPinnedRef.current) {
        pinSettled(list);
      }
      onTickRef.current(list);
    });

    sim.alpha(1).restart();
    simRef.current = sim;
  }, [lens, reducedMotion, pinSettled]);

  useEffect(() => {
    rebuild();
    return () => {
      simRef.current?.stop();
    };
  }, [rebuild]);

  /** Sync structural node set (birth/death) into the running sim. */
  const syncNodes = useCallback(
    (next: SimNode[], opts?: { reheat?: boolean }) => {
      nodesRef.current = next;
      const sim = simRef.current;
      if (!sim) {
        rebuild();
        return;
      }
      sim.nodes(next.map((n) => ({ ...n })));
      if (opts?.reheat !== false && !reducedMotion) {
        unpinAllMasses(sim.nodes());
        sim.alpha(REHEAT_ALPHA).restart();
      } else {
        onTickRef.current(sim.nodes().map((n) => ({ ...n })));
      }
    },
    [rebuild, reducedMotion, unpinAllMasses],
  );

  const reheat = useCallback(() => {
    const sim = simRef.current;
    if (!sim || reducedMotion) return;
    unpinAllMasses(sim.nodes());
    // Rebuild links for current lens with fresh node refs
    const lensLinks = linksForLens(linksRef.current, lens).map((l) => ({
      ...l,
      source: resolveId(l.source),
      target: resolveId(l.target),
    }));
    sim.force(
      "link",
      forceLink<SimNode, ForceLink>(lensLinks as ForceLink[])
        .id((d) => d.id)
        .distance((l) => linkDistance(l as SimLink))
        .strength((l) => linkStrength(l as SimLink)),
    );
    sim.alpha(REHEAT_ALPHA).restart();
  }, [lens, reducedMotion, unpinAllMasses]);

  const pinNode = useCallback((id: string, x: number, y: number) => {
    const sim = simRef.current;
    if (!sim) return;
    const n = sim.nodes().find((node) => node.id === id);
    if (!n) return;
    n.fx = x;
    n.fy = y;
    n.x = x;
    n.y = y;
  }, []);

  const releaseNode = useCallback(
    (id: string) => {
      const sim = simRef.current;
      if (!sim) return;
      const n = sim.nodes().find((node) => node.id === id);
      if (!n) return;
      n.fx = null;
      n.fy = null;
      if (!reducedMotion) {
        settledPinnedRef.current = false;
        sim.alpha(REHEAT_ALPHA).restart();
      }
    },
    [reducedMotion],
  );

  const setLinks = useCallback(
    (next: SimLink[]) => {
      linksRef.current = next;
      reheat();
    },
    [reheat],
  );

  return {
    reheat,
    syncNodes,
    pinNode,
    releaseNode,
    setLinks,
    rebuild,
  };
}
