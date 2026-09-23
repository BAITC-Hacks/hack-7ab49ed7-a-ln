import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Filters, Methodology, Role, Run } from '../api/types';
import { busy, canRetry, useMeta, useMethodology, useRun } from '../hooks/queries';
import { useWorkspaceGraph } from '../hooks/useWorkspaceGraph';
import {
  ConfirmDialog,
  Empty,
  ErrorView,
  Loading,
  RunFailure,
  RunStatus,
  Warnings,
} from '../components/Common';
import { NodeCard } from '../components/NodeCard';
import { AssistantPanel } from '../components/AssistantPanel';
import { ClusterList, ExportsMenu, Search, TopList } from '../components/WorkspaceLists';
import { GraphView } from '../components/GraphView';
import { NodesTable } from '../components/NodesTable';
import { Overview, DataRequests } from '../components/Overview';
import { date, money, number, score } from '../format';
import s from './Workspace.module.css';

export function WorkspacePage() {
  const { runId } = useParams();
  return runId ? <WorkspaceLoader key={runId} runId={runId} /> : <Empty>Исследование не выбрано.</Empty>;
}
function WorkspaceLoader({ runId }: { runId: string }) {
  const run = useRun(runId);
  if (run.isPending) return <Loading label="Открываем исследование…" />;
  if (run.error) return <ErrorView error={run.error} retry={() => void run.refetch()} />;
  return run.data.status === 'succeeded' ? <ReadyWorkspace run={run.data} /> : <RunProgress run={run.data} />;
}
function ReadyWorkspace({ run }: { run: Run }) {
  const methodology = useMethodology(run.id);
  const meta = useMeta();
  if (methodology.isPending || meta.isPending) return <Loading label="Загружаем методологию…" />;
  if (methodology.error || meta.error)
    return (
      <ErrorView
        error={methodology.error ?? meta.error}
        retry={() => {
          void methodology.refetch();
          void meta.refetch();
        }}
      />
    );
  return <Workspace run={run} methodology={methodology.data} llmEnabled={meta.data.llm_enabled} />;
}
function RunProgress({ run }: { run: Run }) {
  const [confirm, setConfirm] = useState(false);
  const client = useQueryClient();
  const operation = useMutation({
    mutationFn: () => (busy(run) ? api.cancel(run.id) : api.retry(run.id)),
    onSuccess: () => {
      setConfirm(false);
      void client.invalidateQueries({ queryKey: ['run', run.id] });
      void client.invalidateQueries({ queryKey: ['runs'] });
    },
  });
  return (
    <section className={s.pending}>
      <Link to="/runs">← Все исследования</Link>
      <h1>{run.name}</h1>
      <RunStatus run={run} />
      <Warnings items={run.warnings} />
      {run.error && <RunFailure error={run.error} needsUpload={run.status === 'failed' && !canRetry(run)} />}
      <p>
        {busy(run)
          ? 'После завершения анализа рабочее пространство откроется автоматически. Вы можете вернуться к списку исследований.'
          : 'Анализ не завершён. Результаты пока недоступны.'}
      </p>
      {(busy(run) || canRetry(run)) && (
        <button disabled={busy(run) && run.cancel_requested} onClick={() => setConfirm(true)}>
          {busy(run) ? 'Отменить анализ' : 'Повторить анализ'}
        </button>
      )}
      {confirm && (busy(run) || canRetry(run)) && (
        <ConfirmDialog
          title={busy(run) ? 'Отменить анализ?' : 'Повторить анализ?'}
          onClose={() => setConfirm(false)}
          onConfirm={() => operation.mutate()}
          pending={operation.isPending}
        >
          <p>{run.name}</p>
          {operation.error && <ErrorView error={operation.error} />}
        </ConfirmDialog>
      )}
    </section>
  );
}
function Workspace({
  run,
  methodology,
  llmEnabled,
}: {
  run: Run;
  methodology: Methodology;
  llmEnabled: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const [sidebar, setSidebar] = useState<'top' | 'clusters'>('top');
  const selected = params.get('node');
  const panel = params.get('panel') === 'assistant' ? 'assistant' : 'node';
  const view = params.get('view') ?? 'graph';
  const roles = params
    .getAll('role')
    .filter((role): role is Role => methodology.role_order.includes(role as Role));
  const cluster = params.get('cluster');
  const filters: Filters = {
    role: roles.length ? roles : undefined,
    cluster_id: cluster !== null && /^\d+$/.test(cluster) ? Number(cluster) : undefined,
    min_priority: Math.min(1, Math.max(0, Number(params.get('min_priority')) || 0)),
    hide_peripheral: params.get('hide_peripheral') === 'true',
  };
  const graph = useWorkspaceGraph(run.id, filters, selected);
  const update = (values: Record<string, string | null>) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(values)) {
        if (value === null) next.delete(key);
        else next.set(key, value);
      }
      return next;
    });
  const select = (id: string) => {
    graph.previewHighlight(null);
    update({ node: id, panel: 'node' });
  };
  const filterRoles = (role: Role, checked: boolean) => {
    graph.focus.reset();
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      const values = next.getAll('role').filter((r) => r !== role);
      next.delete('role');
      for (const value of checked ? [...values, role] : values) next.append('role', value);
      return next;
    });
  };
  return (
    <>
      <WorkspaceHeader run={run} />
      <Warnings items={run.warnings} />
      <div className={s.navRow}>
        <nav aria-label="Представление исследования">
          {[
            ['graph', 'Граф связей'],
            ['overview', 'Обзор'],
            ['nodes', 'Клиенты'],
            ['requests', 'Запросы данных'],
          ].map(([key, label]) => (
            <button key={key} aria-pressed={view === key} onClick={() => update({ view: key })}>
              {label}
            </button>
          ))}
        </nav>
        <span>Движок {run.engine_version}</span>
      </div>
      <div className={s.workspace}>
        <aside className={s.left}>
          <div className={s.search}>
            <Search runId={run.id} onSelect={select} />
          </div>
          <div className={s.tabs}>
            <button aria-pressed={sidebar === 'top'} onClick={() => setSidebar('top')}>
              Приоритеты
            </button>
            <button aria-pressed={sidebar === 'clusters'} onClick={() => setSidebar('clusters')}>
              Кластеры
            </button>
          </div>
          <div className={s.sideScroll}>
            {sidebar === 'top' ? (
              <TopList runId={run.id} selected={selected} methodology={methodology} onSelect={select} />
            ) : (
              <ClusterList
                runId={run.id}
                selected={filters.cluster_id}
                onSelect={(id) => {
                  graph.focus.reset();
                  update({ cluster: String(id), view: 'graph' });
                }}
              />
            )}
          </div>
        </aside>
        <div className={s.center}>
          {(view === 'graph' || view === 'nodes') && (
            <GraphFilters
              filters={filters}
              methodology={methodology}
              roleChange={filterRoles}
              update={(values) => {
                graph.focus.reset();
                update(values);
              }}
              reset={() => {
                graph.focus.reset();
                setParams((previous) => {
                  const next = new URLSearchParams(previous);
                  for (const key of ['role', 'cluster', 'min_priority', 'hide_peripheral']) next.delete(key);
                  return next;
                });
              }}
            />
          )}
          {view === 'overview' ? (
            <Overview runId={run.id} methodology={methodology} />
          ) : view === 'nodes' ? (
            <NodesTable
              key={JSON.stringify(filters)}
              runId={run.id}
              filters={filters}
              methodology={methodology}
              onSelect={select}
            />
          ) : view === 'requests' ? (
            <DataRequests runId={run.id} onSelect={select} />
          ) : (
            <>
              <div aria-live="polite">
                {graph.focus.pending && <Loading label="Исследуем связи…" />}
                {graph.focus.error && <ErrorView error={graph.focus.error} />}{' '}
                {graph.hydration?.error && <ErrorView error={graph.hydration.error} />}
                {graph.hydration?.data && (
                  <Warnings
                    items={[
                      'Выбранный клиент добавлен вне текущих фильтров. Его связи доступны через «Окружение и путь».',
                    ]}
                  />
                )}
              </div>
              {graph.focus.data && (
                <div className={s.focus}>
                  <span>{graph.focus.data.label}</span>
                  <button onClick={graph.focus.reset}>Вернуться к обзору ×</button>
                </div>
              )}
              {graph.focus.data && <Warnings items={graph.focus.data.warnings} />}{' '}
              {graph.base.isPending ? (
                <Loading label="Загрузка сети переводов…" />
              ) : graph.base.error ? (
                <ErrorView error={graph.base.error} retry={() => void graph.base.refetch()} />
              ) : (
                graph.displayed && (
                  <GraphView
                    key={graph.focus.data?.label ?? JSON.stringify(filters)}
                    data={graph.displayed}
                    methodology={methodology}
                    selected={selected}
                    highlight={graph.preview}
                    fitIds={graph.fitIds}
                    onSelect={select}
                  />
                )
              )}
              <p className={s.graphNote}>
                Стрелки показывают направление переводов. Вне выборки могут существовать другие операции.
              </p>
            </>
          )}
        </div>
        <aside className={s.right}>
          <div className={s.tabs}>
            <button aria-pressed={panel === 'node'} onClick={() => update({ panel: 'node' })}>
              Карточка клиента
            </button>
            <button aria-pressed={panel === 'assistant'} onClick={() => update({ panel: 'assistant' })}>
              Помощник
            </button>
          </div>
          <div className={s.sideScroll}>
            <div hidden={panel !== 'node'}>
              <NodeCard
                runId={run.id}
                gid={selected}
                methodology={methodology}
                actions={{
                  select,
                  graph: (label, work) => {
                    update({ view: 'graph' });
                    graph.show(label, work);
                  },
                  path: (source, target) => {
                    update({ view: 'graph' });
                    graph.path(source, target);
                  },
                }}
              />
            </div>
            <div hidden={panel !== 'assistant'}>
              <AssistantPanel
                runId={run.id}
                llmEnabled={llmEnabled}
                callbacks={{
                  select,
                  preview: graph.previewHighlight,
                  action: (value) => {
                    update({ view: 'graph' });
                    graph.action(value);
                  },
                  highlight: (value) => {
                    update({ view: 'graph' });
                    graph.highlight(value);
                  },
                }}
              />
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
function WorkspaceHeader({ run }: { run: Run }) {
  return (
    <header className={s.header}>
      <div>
        <Link to="/runs" className={s.back}>
          ← Исследования
        </Link>
        <h1>{run.name}</h1>
        <div className={s.summary}>
          {run.summary && (
            <>
              <span>
                {date(run.summary.period[0])} — {date(run.summary.period[1])}
              </span>
              <span>{number(run.summary.n_nodes)} клиентов</span>
              <span>{money(run.summary.total_kzt)} видимого оборота</span>
            </>
          )}
          <RunStatus run={run} />
        </div>
      </div>
      <div className={s.headerActions}>
        <Link className="button" to={`/methodology?run_id=${encodeURIComponent(run.id)}`}>
          Методология
        </Link>
        <ExportsMenu runId={run.id} />
      </div>
    </header>
  );
}
function GraphFilters({
  filters,
  methodology,
  roleChange,
  update,
  reset,
}: {
  filters: Filters;
  methodology: Methodology;
  roleChange: (role: Role, checked: boolean) => void;
  update: (values: Record<string, string | null>) => void;
  reset: () => void;
}) {
  return (
    <div className={s.filters}>
      <details>
        <summary>Роли {filters.role?.length ? `(${filters.role.length})` : '· все'}</summary>
        <div className={s.roleFilters}>
          {methodology.role_order.map((role) => (
            <label key={role}>
              <input
                type="checkbox"
                checked={filters.role?.includes(role) ?? false}
                onChange={(e) => roleChange(role, e.target.checked)}
              />
              {methodology.roles[role].label}
            </label>
          ))}
        </div>
      </details>
      <label>
        Кластер
        <input
          aria-label="Фильтр по кластеру"
          type="number"
          min={0}
          value={filters.cluster_id ?? ''}
          placeholder="Все"
          onChange={(e) => update({ cluster: e.target.value || null })}
        />
      </label>
      <label>
        Приоритет от
        <select value={filters.min_priority ?? 0} onChange={(e) => update({ min_priority: e.target.value })}>
          {[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9].map((value) => (
            <option key={value} value={value}>
              {score(value)}
            </option>
          ))}
        </select>
      </label>
      <label className={s.check}>
        <input
          type="checkbox"
          checked={filters.hide_peripheral ?? false}
          onChange={(e) => update({ hide_peripheral: e.target.checked ? 'true' : null })}
        />
        Без периферии
      </label>
      <button onClick={reset}>Сбросить</button>
    </div>
  );
}
