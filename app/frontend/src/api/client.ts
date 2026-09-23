import type {
  AssistantAnswer,
  AssistantMode,
  Cluster,
  Counterparty,
  DataRequest,
  ExportFile,
  Filters,
  Meta,
  Methodology,
  NodeDetail,
  NodeRow,
  Overview,
  Page,
  PathResult,
  Run,
  Session,
  SortBy,
  Subgraph,
  TopItem,
  Transaction,
} from './types';
import { createHttpClient, type HttpClient } from './http';

export function query(params: object = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '' || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, String(item));
  }
  return search.size ? `?${search}` : '';
}
const root = (id: string) => `/runs/${encodeURIComponent(id)}`;
const json = (body: unknown, signal?: AbortSignal): RequestInit => ({
  method: 'POST',
  body: JSON.stringify(body),
  signal,
});
export function createApi(http: HttpClient) {
  const request = <T>(path: string, options?: RequestInit) => http.request<T>(path, options);
  return {
    meta: (signal?: AbortSignal) => request<Meta>('/meta', { signal }),
    session: (signal?: AbortSignal) => request<Session>('/session', { signal }),
    login: (token: string) => request<void>('/session', json({ token })),
    logout: () => request<void>('/session', { method: 'DELETE' }),
    methodology: (signal?: AbortSignal, runId?: string) =>
      request<Methodology>(`/methodology${query({ run_id: runId })}`, { signal }),
    runs: (offset: number, signal?: AbortSignal) =>
      request<Page<Run>>(`/runs${query({ limit: 20, offset })}`, { signal }),
    run: (id: string, signal?: AbortSignal) => request<Run>(root(id), { signal }),
    demo: () => request<Run>('/runs/demo', { method: 'POST' }),
    cancel: (id: string) => request<Run>(`${root(id)}/cancel`, { method: 'POST' }),
    retry: (id: string) => request<Run>(`${root(id)}/retry`, { method: 'POST' }),
    delete: (id: string) => request<void>(root(id), { method: 'DELETE' }),
    overview: (id: string, signal?: AbortSignal) => request<Overview>(`${root(id)}/overview`, { signal }),
    graph: (id: string, filters: Filters, signal?: AbortSignal) =>
      request<Subgraph>(`${root(id)}/graph${query({ ...filters, max_nodes: 5000, max_edges: 20000 })}`, {
        signal,
      }),
    hydrate: (id: string, ids: string[], signal?: AbortSignal) =>
      request<Subgraph>(`${root(id)}/graph/nodes`, json({ ids, include_edges: true }, signal)),
    nodes: (
      id: string,
      filters: Filters,
      sort_by: SortBy,
      sort_order: 'asc' | 'desc',
      offset: number,
      signal?: AbortSignal,
    ) =>
      request<Page<NodeRow>>(
        `${root(id)}/nodes${query({ role: filters.role, cluster_id: filters.cluster_id, q: filters.q, is_seed: filters.is_seed, flag: filters.flag, sort_by, sort_order, offset, limit: 25 })}`,
        { signal },
      ),
    search: (id: string, q: string, signal?: AbortSignal) =>
      request<Page<Pick<NodeRow, 'id' | 'role' | 'priority_score' | 'priority_rank'>>>(
        `${root(id)}/search${query({ q, limit: 20 })}`,
        { signal },
      ),
    node: (id: string, gid: string, signal?: AbortSignal) =>
      request<NodeDetail>(`${root(id)}/nodes/${encodeURIComponent(gid)}`, { signal }),
    counterparties: (
      id: string,
      gid: string,
      direction: 'in' | 'out',
      offset: number,
      signal?: AbortSignal,
    ) =>
      request<Page<Counterparty>>(
        `${root(id)}/nodes/${encodeURIComponent(gid)}/counterparties${query({ direction, offset, limit: 10 })}`,
        { signal },
      ),
    transactions: (
      id: string,
      gid: string,
      direction: 'in' | 'out' | 'both',
      counterparty: string,
      offset: number,
      signal?: AbortSignal,
    ) =>
      request<Page<Transaction>>(
        `${root(id)}/nodes/${encodeURIComponent(gid)}/transactions${query({ direction, counterparty, offset, limit: 20 })}`,
        { signal },
      ),
    neighborhood: (id: string, gid: string, depth: number, direction: string, signal?: AbortSignal) =>
      request<Subgraph>(
        `${root(id)}/nodes/${encodeURIComponent(gid)}/neighborhood${query({ depth, direction, max_nodes: 300, max_edges: 1000 })}`,
        { signal },
      ),
    trace: (id: string, gid: string, direction: 'up' | 'down', signal?: AbortSignal) =>
      request<Subgraph>(
        `${root(id)}/nodes/${encodeURIComponent(gid)}/trace${query({ direction, max_hops: 4, max_nodes: 500 })}`,
        { signal },
      ),
    path: (id: string, source: string, target: string, signal?: AbortSignal) =>
      request<PathResult>(`${root(id)}/path${query({ source, target })}`, { signal }),
    top: (id: string, signal?: AbortSignal) =>
      request<{ items: TopItem[] }>(`${root(id)}/top?limit=50`, { signal }),
    clusters: (id: string, offset: number, sort_by: string, signal?: AbortSignal) =>
      request<Page<Cluster>>(`${root(id)}/clusters${query({ offset, limit: 20, sort_by })}`, { signal }),
    dataRequests: (id: string, offset: number, signal?: AbortSignal) =>
      request<Page<DataRequest>>(`${root(id)}/data-requests${query({ offset, limit: 25 })}`, { signal }),
    exports: (id: string, signal?: AbortSignal) =>
      request<{ items: ExportFile[] }>(`${root(id)}/exports`, { signal }),
    download: (id: string, name: string, signal?: AbortSignal) =>
      http.download(`${root(id)}/exports/${encodeURIComponent(name)}`, signal),
    upload: (form: FormData, onProgress: (value: number) => void, signal?: AbortSignal) =>
      http.upload<Run>('/runs', form, onProgress, signal),
    assistant: (id: string, question: string, mode: AssistantMode, signal?: AbortSignal) =>
      request<AssistantAnswer>(`${root(id)}/assistant`, json({ question, mode }, signal)),
  };
}
export type ApiClient = ReturnType<typeof createApi>;
export const api = createApi(
  createHttpClient({
    fetch: (...args) => fetch(...args),
    createXHR: () => new XMLHttpRequest(),
    onUnauthorized: () => window.dispatchEvent(new Event('mg:unauthorized')),
  }),
);
