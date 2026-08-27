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
import type { SimLink, SimNode } from "../data/fieldGraph";
import {
  ALPHA_DECAY,
  ALPHA_MIN,
  COLLIDE_STRENGTH,
  REHEAT_ALPHA,
  VELOCITY_DECAY,
  chargeStrength,
  collideRadius,
  linkDistance,
  linkStrength,
} from "./forceConfig";

type ForceLink = SimulationLinkDatum<SimNode> & SimLink;

type UseForceLayoutArgs = {
  nodes: SimNode[];
  links: SimLink[];
  onTick: (nodes: SimNode[]) => void;
  reducedMotion: boolean;
};

function resolveId(end: string | SimNode): string {
  return typeof end === "string" ? end : end.id;
}

function asForceLinks(links: SimLink[]): ForceLink[] {
  return links.map((l) => ({
    ...l,
    source: resolveId(l.source),
    target: resolveId(l.target),
  })) as ForceLink[];
}

export function useForceLayout({
  nodes,
  links,
  onTick,
  reducedMotion,
}: UseForceLayoutArgs) {
  const simRef = useRef<Simulation<SimNode, ForceLink> | null>(null);
  const nodesRef = useRef(nodes);
  const linksRef = useRef(links);
  const onTickRef = useRef(onTick);

  nodesRef.current = nodes;
  linksRef.current = links;
  onTickRef.current = onTick;

  const unpinAll = useCallback((list: SimNode[]) => {
    for (const n of list) {
      n.fx = null;
      n.fy = null;
    }
  }, []);

  const applyLinkForce = useCallback(
    (sim: Simulation<SimNode, ForceLink>, nextLinks: SimLink[]) => {
      const known = new Set(sim.nodes().map((n) => n.id));
      const forceLinks = asForceLinks(
        nextLinks.filter(
          (l) =>
            known.has(resolveId(l.source)) && known.has(resolveId(l.target)),
        ),
      );
      sim.force(
        "link",
        forceLink<SimNode, ForceLink>(forceLinks)
          .id((d) => d.id)
          .distance(linkDistance)
          .strength(linkStrength),
      );
    },
    [],
  );

  useEffect(() => {
    const simNodes = nodesRef.current.map((n) => ({ ...n }));
    const simLinks = asForceLinks(linksRef.current);

    const sim = forceSimulation<SimNode, ForceLink>(simNodes)
      .force("charge", forceManyBody<SimNode>().strength(chargeStrength))
      .force(
        "collide",
        forceCollide<SimNode>().radius(collideRadius).strength(COLLIDE_STRENGTH),
      )
      .force(
        "link",
        forceLink<SimNode, ForceLink>(simLinks)
          .id((d) => d.id)
          .distance(linkDistance)
          .strength(linkStrength),
      )
      .force("center", forceCenter(560, 320))
      .velocityDecay(VELOCITY_DECAY)
      .alphaDecay(ALPHA_DECAY)
      .alphaMin(ALPHA_MIN);

    sim.on("tick", () => {
      onTickRef.current(simNodes.map((n) => ({ ...n })));
    });

    sim.on("end", () => {
      onTickRef.current(simNodes.map((n) => ({ ...n })));
    });

    if (reducedMotion) {
      for (let i = 0; i < 80; i++) sim.tick();
      onTickRef.current(simNodes.map((n) => ({ ...n })));
      sim.stop();
    }

    simRef.current = sim;
    return () => {
      sim.stop();
      simRef.current = null;
    };
  }, [reducedMotion]);

  const reheat = useCallback(() => {
    const sim = simRef.current;
    if (!sim || reducedMotion) return;
    unpinAll(sim.nodes());
    applyLinkForce(sim, linksRef.current);
    sim.alpha(REHEAT_ALPHA).restart();
  }, [applyLinkForce, reducedMotion, unpinAll]);

  const dragFix = useCallback((id: string, x: number, y: number) => {
    const sim = simRef.current;
    if (!sim) return;
    const n = sim.nodes().find((node) => node.id === id);
    if (!n) return;
    n.fx = x;
    n.fy = y;
    n.x = x;
    n.y = y;
  }, []);

  const dragEnd = useCallback(
    (id: string) => {
      const sim = simRef.current;
      if (!sim) return;
      const n = sim.nodes().find((node) => node.id === id);
      if (!n) return;
      n.fx = null;
      n.fy = null;
      reheat();
    },
    [reheat],
  );

  const syncNodes = useCallback(
    (next: SimNode[], opts?: { reheat?: boolean }) => {
      nodesRef.current = next;
      const sim = simRef.current;
      if (!sim) return;
      const byId = new Map(sim.nodes().map((n) => [n.id, n]));
      const merged: SimNode[] = [];
      for (const n of next) {
        const existing = byId.get(n.id);
        if (existing) {
          existing.concept = n.concept;
          if (n.fx != null) {
            existing.fx = n.fx;
            existing.fy = n.fy;
            existing.x = n.x;
            existing.y = n.y;
          }
          merged.push(existing);
        } else {
          merged.push({ ...n });
        }
      }
      sim.nodes(merged);
      // Keep link force coherent with the node set after structural changes
      applyLinkForce(sim, linksRef.current);
      if (opts?.reheat !== false && !reducedMotion) {
        unpinAll(merged);
        sim.alpha(REHEAT_ALPHA).restart();
      }
    },
    [applyLinkForce, reducedMotion, unpinAll],
  );

  const syncLinks = useCallback(
    (next: SimLink[]) => {
      linksRef.current = next;
      const sim = simRef.current;
      if (!sim) return;
      const known = new Set(sim.nodes().map((n) => n.id));
      const safe = next.filter(
        (l) =>
          known.has(resolveId(l.source)) && known.has(resolveId(l.target)),
      );
      applyLinkForce(sim, safe);
      if (!reducedMotion) {
        unpinAll(sim.nodes());
        sim.alpha(REHEAT_ALPHA).restart();
      }
    },
    [applyLinkForce, reducedMotion, unpinAll],
  );

  return { reheat, dragFix, dragEnd, syncNodes, syncLinks };
}
