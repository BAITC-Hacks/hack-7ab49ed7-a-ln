import { expect, it, vi } from 'vitest';
import { createApi } from '../api/client';
import { hydrateGraph } from './operations';
import type { HttpClient } from '../api/http';
import { createDemoData } from '../mocks/data';

it('hydrates in batches of at most 500 and preserves path edges across batches', async () => {
  const data = createDemoData();
  const ids = Array.from({ length: 501 }, (_, i) => String(100000000000000000n + BigInt(i)));
  const http: HttpClient = {
    request: vi.fn(async (_path: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body)) as { ids: string[] };
      return {
        ...data.graph,
        nodes: body.ids.map((id) => ({ ...data.nodes[0], id })),
        edges: [],
        total_nodes: body.ids.length,
        total_edges: 0,
      };
    }) as HttpClient['request'],
    upload: vi.fn(),
    download: vi.fn(),
  };
  const edge = { ...data.edges[0], source: ids[499], target: ids[500] };
  const result = await hydrateGraph(createApi(http), 'run', ids, new AbortController().signal, [edge]);
  expect(http.request).toHaveBeenCalledTimes(2);
  expect(result.nodes).toHaveLength(501);
  expect(result.edges).toEqual([edge]);
  expect(result.truncated).toBe(false);
});
