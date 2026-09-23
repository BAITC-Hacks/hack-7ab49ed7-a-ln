import type { ApiClient } from '../api/client';
import type { GraphEdge, Subgraph } from '../api/types';

const HYDRATION_BATCH = 500;
export async function hydrateGraph(
  api: ApiClient,
  runId: string,
  ids: string[],
  signal: AbortSignal,
  edges?: GraphEdge[],
  pairs: string[][] = [],
): Promise<Subgraph> {
  const unique = [...new Set(ids)];
  const batches: string[][] = [];
  for (let start = 0; start < unique.length; start += HYDRATION_BATCH)
    batches.push(unique.slice(start, start + HYDRATION_BATCH));
  if (unique.length > HYDRATION_BATCH && pairs.length) {
    for (let start = 0; start < pairs.length; start += HYDRATION_BATCH / 2)
      batches.push([...new Set(pairs.slice(start, start + HYDRATION_BATCH / 2).flat())]);
  }
  const parts: Subgraph[] = [];
  for (const batch of batches) {
    signal.throwIfAborted();
    parts.push(await api.hydrate(runId, batch, signal));
  }
  const nodes = [...new Map(parts.flatMap((p) => p.nodes).map((n) => [n.id, n])).values()];
  const nodeIds = new Set(nodes.map((n) => n.id));
  const mergedEdges = [
    ...new Map(
      (edges ?? parts.flatMap((p) => p.edges))
        .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map((e) => [JSON.stringify([e.source, e.target]), e]),
    ).values(),
  ];
  const incompleteInducedEdges = unique.length > HYDRATION_BATCH && !edges && !pairs.length;
  return {
    center: null,
    nodes,
    edges: mergedEdges,
    total_nodes: unique.length,
    total_edges: edges?.length ?? mergedEdges.length,
    truncated: nodes.length < unique.length || parts.some((p) => p.truncated) || incompleteInducedEdges,
    truncation_reason:
      nodes.length < unique.length
        ? 'max_nodes'
        : incompleteInducedEdges
          ? 'max_edges'
          : (parts.find((p) => p.truncated)?.truncation_reason ?? null),
  };
}
