import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Run } from '../api/types';

export const busy = (run: Run) => run.status === 'queued' || run.status === 'running';
export const canRetry = (run: Run) =>
  run.status === 'cancelled' || (run.status === 'failed' && run.error?.retryable !== false);
export const pollInterval = (run?: Run) =>
  run && busy(run) ? Math.max(500, run.poll_after_ms ?? 1500) : false;
export const useMeta = () =>
  useQuery({ queryKey: ['meta'], queryFn: ({ signal }) => api.meta(signal), staleTime: 60_000 });
export const useMethodology = (runId?: string) =>
  useQuery({
    queryKey: ['methodology', runId],
    queryFn: ({ signal }) => api.methodology(signal, runId),
    staleTime: Infinity,
  });
export const useRun = (id: string) =>
  useQuery({
    queryKey: ['run', id],
    queryFn: ({ signal }) => api.run(id, signal),
    refetchInterval: (q) => pollInterval(q.state.data),
  });
