import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { AssistantAction, AssistantAnswer, Filters, Subgraph } from '../api/types';
import { hydrateGraph } from '../graph/operations';
import { useTask } from './useTask';

interface FocusResult {
  graph: Subgraph;
  label: string;
  warnings: string[];
}
export function useWorkspaceGraph(runId: string, filters: Filters, selected: string | null) {
  const base = useQuery({
    queryKey: ['graph', runId, filters],
    queryFn: ({ signal }) => api.graph(runId, filters, signal),
  });
  const focus = useTask<FocusResult>(JSON.stringify(filters));
  const scope = JSON.stringify([runId, filters]);
  const [previewState, setPreviewState] = useState<{
    scope: string;
    value: AssistantAnswer['highlight'];
  } | null>(null);
  const preview = previewState?.scope === scope ? previewState.value : undefined;
  const previewHighlight = (value: AssistantAnswer['highlight'] | null) => {
    setPreviewState(value ? { scope, value } : null);
    if (value) focus.reset();
  };
  const fitIds = useMemo(() => focus.data?.graph.nodes.map((node) => node.id), [focus.data]);
  const current = focus.data?.graph ?? base.data;
  const missing = !!selected && !!current && !current.nodes.some((n) => n.id === selected);
  const hydration = useQuery({
    queryKey: ['graph-selection', runId, selected],
    queryFn: ({ signal }) => api.hydrate(runId, [selected!], signal),
    enabled: missing,
  });
  const displayed = useMemo(() => {
    if (!current || !missing || !hydration.data) return current;
    return {
      ...current,
      nodes: [...current.nodes, ...hydration.data.nodes],
      edges: [...current.edges, ...hydration.data.edges],
      total_nodes: Math.max(current.total_nodes, current.nodes.length + hydration.data.nodes.length),
    };
  }, [current, missing, hydration.data]);
  const show = (label: string, work: (signal: AbortSignal) => Promise<Subgraph>) => {
    setPreviewState(null);
    void focus.execute(async (signal) => ({ graph: await work(signal), label, warnings: [] }));
  };
  const path = (source: string, target: string) => {
    setPreviewState(null);
    void focus.execute(async (signal) => {
      const result = await api.path(runId, source, target, signal);
      const graph = await hydrateGraph(
        api,
        runId,
        result.found ? result.nodes : [source, target],
        signal,
        result.edges,
      );
      return {
        graph,
        label: 'Путь между клиентами',
        warnings: !result.found
          ? ['Путь в наблюдаемом графе не найден.']
          : !result.directed
            ? [
                'Направленный путь не найден. Показан путь без учёта направления; стрелки сохраняют направление исходных переводов.',
              ]
            : [],
      };
    });
  };
  const highlight = (value: AssistantAnswer['highlight']) =>
    show('Узлы из ответа помощника', async (signal) => {
      const graph = await hydrateGraph(api, runId, value.nodes, signal, undefined, value.edges);
      if (!value.edges.length) return graph;
      const pairs = new Set(value.edges.map((e) => JSON.stringify(e)));
      return { ...graph, edges: graph.edges.filter((e) => pairs.has(JSON.stringify([e.source, e.target]))) };
    });
  const action = (value: AssistantAction) => {
    if (value.type === 'path' && value.ids.length >= 2) path(value.ids[0], value.ids[value.ids.length - 1]);
    else show(value.label, (signal) => hydrateGraph(api, runId, value.ids, signal));
  };
  return {
    base,
    focus,
    hydration: missing ? hydration : null,
    displayed,
    show,
    path,
    highlight,
    action,
    preview,
    previewHighlight,
    fitIds,
  };
}
