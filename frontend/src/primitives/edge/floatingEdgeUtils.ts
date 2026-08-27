import type { InternalNode, Node } from "@xyflow/react";

type PointLike = { x: number; y: number };

type NodeLike =
  | Node
  | InternalNode
  | {
      position: { x: number; y: number };
      measured?: { width?: number; height?: number };
      width?: number;
      height?: number;
    }
  | PointLike;

function hasPosition(
  node: NodeLike,
): node is {
  position: { x: number; y: number };
  measured?: { width?: number; height?: number };
  width?: number;
  height?: number;
} {
  return "position" in node && !!node.position;
}

function getNodeDimensions(node: NodeLike) {
  if (!hasPosition(node)) {
    return { width: 0, height: 0 };
  }
  const width = node.measured?.width ?? node.width ?? 160;
  const height = node.measured?.height ?? node.height ?? 160;
  return { width, height };
}

function getNodeCenter(node: NodeLike): PointLike {
  if (!hasPosition(node)) {
    return { x: (node as PointLike).x, y: (node as PointLike).y };
  }
  const { width, height } = getNodeDimensions(node);
  const absolute =
    "internals" in node &&
    node.internals &&
    typeof node.internals === "object" &&
    "positionAbsolute" in node.internals
      ? (node.internals as { positionAbsolute: { x: number; y: number } })
          .positionAbsolute
      : null;
  const origin = absolute ?? node.position;
  return {
    x: origin.x + width / 2,
    y: origin.y + height / 2,
  };
}

/**
 * Intersection of the ray from node center toward the peer, on the circumference.
 * Assumes square measured bounds (circular node). Borrowed from Note Prototype.
 */
export function getNodeIntersection(node: NodeLike, targetNode: NodeLike) {
  const { width } = getNodeDimensions(node);
  const currNodeCenter = getNodeCenter(node);
  const targetCenter = getNodeCenter(targetNode);

  const dx = targetCenter.x - currNodeCenter.x;
  const dy = targetCenter.y - currNodeCenter.y;
  const angle = Math.atan2(dy, dx);
  const radius = width / 2;

  return {
    x: currNodeCenter.x + Math.cos(angle) * radius,
    y: currNodeCenter.y + Math.sin(angle) * radius,
  };
}

export function getEdgeParams(source: Node | InternalNode, target: Node | InternalNode) {
  const sourceIntersection = getNodeIntersection(source, target);
  const targetIntersection = getNodeIntersection(target, source);

  return {
    sx: sourceIntersection.x,
    sy: sourceIntersection.y,
    tx: targetIntersection.x,
    ty: targetIntersection.y,
  };
}

export function getConnectionLineParams(
  source: Node | InternalNode,
  targetX: number,
  targetY: number,
) {
  const fakeTarget = { x: targetX, y: targetY };
  const sourceIntersection = getNodeIntersection(source, fakeTarget);

  return {
    sx: sourceIntersection.x,
    sy: sourceIntersection.y,
    tx: targetX,
    ty: targetY,
  };
}
