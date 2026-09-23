import type { GraphNode, Subgraph } from '../api/types';
import type { DemoData } from './data';

export function graphSubset(
  data: DemoData,
  nodes: GraphNode[],
  query: URLSearchParams,
  center: string | null = null,
): Subgraph {
  const maxNodes = Number(query.get('max_nodes') ?? 5000);
  const maxEdges = Number(query.get('max_edges') ?? 20000);
  const kept = nodes.slice(0, maxNodes);
  const ids = new Set(kept.map((n) => n.id));
  const edges = data.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  return {
    center,
    nodes: kept,
    edges: edges.slice(0, maxEdges),
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: kept.length < nodes.length || edges.length > maxEdges,
    truncation_reason:
      kept.length < nodes.length ? 'max_nodes' : edges.length > maxEdges ? 'max_edges' : null,
  };
}
export function walk(data: DemoData, id: string, direction: string, depth: number) {
  const seen = new Set([id]);
  const queue: [string, number][] = [[id, 0]];
  for (let i = 0; i < queue.length; i++) {
    const [current, distance] = queue[i];
    if (distance >= depth) continue;
    const edges = data.edges.filter((e) =>
      direction === 'in' || direction === 'up'
        ? e.target === current
        : direction === 'out' || direction === 'down'
          ? e.source === current
          : e.source === current || e.target === current,
    );
    for (const edge of edges) {
      const next = edge.source === current ? edge.target : edge.source;
      if (!seen.has(next)) {
        seen.add(next);
        queue.push([next, distance + 1]);
      }
    }
  }
  return data.nodes.filter((n) => seen.has(n.id));
}
export function findPath(data: DemoData, source: string, target: string, undirected = false): string[] {
  const queue = [source];
  const parents = new Map<string, string>();
  const seen = new Set([source]);
  for (let i = 0; i < queue.length && !seen.has(target); i++) {
    for (const edge of data.edges.filter(
      (e) => e.source === queue[i] || (undirected && e.target === queue[i]),
    )) {
      const next = edge.source === queue[i] ? edge.target : edge.source;
      if (!seen.has(next)) {
        seen.add(next);
        parents.set(next, queue[i]);
        queue.push(next);
      }
    }
  }
  if (!seen.has(target)) return [];
  const path = [target];
  while (path[0] !== source) path.unshift(parents.get(path[0])!);
  return path;
}
