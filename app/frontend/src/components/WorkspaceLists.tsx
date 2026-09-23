import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Methodology } from '../api/types';
import { Empty, ErrorView, Loading, Pager, RoleChip } from './Common';
import { money, number, score } from '../format';
import { useTask } from '../hooks/useTask';
import s from './Panels.module.css';

export function Search({ runId, onSelect }: { runId: string; onSelect: (id: string) => void }) {
  const [input, setInput] = useState('');
  const [term, setTerm] = useState('');
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setTerm(input), 250);
    return () => clearTimeout(timer);
  }, [input]);
  const result = useQuery({
    queryKey: ['search', runId, term],
    queryFn: ({ signal }) => api.search(runId, term, signal),
    enabled: /^\d{3,18}$/.test(term) && open,
  });
  const select = (id: string) => {
    onSelect(id);
    setOpen(false);
    setInput(id);
  };
  return (
    <div
      className={s.search}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false);
      }}
    >
      <label className="sr-only" htmlFor="gid-search">
        Поиск клиента по ID
      </label>
      <input
        id="gid-search"
        value={input}
        inputMode="numeric"
        maxLength={18}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setInput(e.target.value.replace(/\D/g, ''));
          setOpen(true);
        }}
        placeholder="Поиск ID · от 3 цифр"
        autoComplete="off"
        aria-controls={open ? 'search-results' : undefined}
      />
      {open && input.length >= 3 && (
        <div className={s.searchResults} id="search-results">
          {result.isFetching ? (
            <Loading label="Поиск…" />
          ) : result.error ? (
            <ErrorView error={result.error} />
          ) : !result.data?.items.length ? (
            <p>Совпадений нет.</p>
          ) : (
            result.data.items.map((item) => (
              <button key={item.id} onClick={() => select(item.id)}>
                <code>{item.id}</code>
                <span>№ {item.priority_rank}</span>
              </button>
            ))
          )}
          <button onClick={() => setOpen(false)}>Закрыть результаты</button>
        </div>
      )}
    </div>
  );
}
export function TopList({
  runId,
  selected,
  methodology,
  onSelect,
}: {
  runId: string;
  selected: string | null;
  methodology: Methodology;
  onSelect: (id: string) => void;
}) {
  const result = useQuery({ queryKey: ['top', runId], queryFn: ({ signal }) => api.top(runId, signal) });
  if (result.isPending) return <Loading />;
  if (result.error) return <ErrorView error={result.error} retry={() => void result.refetch()} />;
  if (!result.data.items.length) return <Empty>Приоритетный список пуст.</Empty>;
  return (
    <div>
      {result.data.items.map((item) => (
        <article key={item.id} className={s.topItem} data-active={selected === item.id}>
          <button
            className={s.topSelect}
            onClick={() => onSelect(item.id)}
            aria-label={`Открыть клиента ${item.id}`}
          >
            <span className={s.rank}>{String(item.top_rank).padStart(2, '0')}</span>
            <span className={s.identity}>
              <code title={item.id}>…{item.id.slice(-9)}</code>
              <RoleChip role={item.role} methodology={methodology} />
            </span>
            <strong>{score(item.priority_score)}</strong>
          </button>
          <details>
            <summary>Почему проверить</summary>
            <p>{item.why || item.evidence}</p>
          </details>
        </article>
      ))}
    </div>
  );
}
export function ClusterList({
  runId,
  selected,
  onSelect,
}: {
  runId: string;
  selected?: number;
  onSelect: (id: number) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState('max_priority');
  const result = useQuery({
    queryKey: ['clusters', runId, offset, sort],
    queryFn: ({ signal }) => api.clusters(runId, offset, sort, signal),
  });
  return (
    <div>
      <div className={s.sideToolbar}>
        <label className="sr-only" htmlFor="cluster-sort">
          Сортировка кластеров
        </label>
        <select
          id="cluster-sort"
          value={sort}
          onChange={(e) => {
            setSort(e.target.value);
            setOffset(0);
          }}
        >
          <option value="max_priority">По приоритету</option>
          <option value="n_nodes">По числу клиентов</option>
          <option value="n_seed">По исходным клиентам</option>
        </select>
      </div>
      {result.isPending ? (
        <Loading />
      ) : result.error ? (
        <ErrorView error={result.error} retry={() => void result.refetch()} />
      ) : !result.data.items.length ? (
        <Empty>Кластеры не найдены.</Empty>
      ) : (
        result.data.items.map((c) => (
          <article className={s.cluster} key={c.cluster_id} data-active={selected === c.cluster_id}>
            <button onClick={() => onSelect(c.cluster_id)}>
              <strong>Кластер {c.cluster_id}</strong>
              <span>{number(c.n_nodes)}</span>
            </button>
            <p>{c.hypothesis}</p>
            <small>
              {money(c.sum_kzt_internal)} · {c.n_seed} исходных · {c.n_truncated} на границе
            </small>
          </article>
        ))
      )}
      {result.data && (
        <div className={s.sideToolbar}>
          <Pager offset={offset} limit={20} total={result.data.total} onChange={setOffset} />
        </div>
      )}
    </div>
  );
}
export function ExportsMenu({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false);
  const result = useQuery({
    queryKey: ['exports', runId],
    queryFn: ({ signal }) => api.exports(runId, signal),
    enabled: open,
  });
  const task = useTask<string>();
  const download = (name: string, filename: string) =>
    void task.execute(async (signal) => {
      const blob = await api.download(runId, name, signal);
      signal.throwIfAborted();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return filename;
    });
  return (
    <div
      className={s.exports}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false);
      }}
    >
      <button aria-expanded={open} onClick={() => setOpen(!open)}>
        ↓ Экспорт
      </button>
      {open && (
        <div className={s.exportMenu}>
          <h3>Результаты анализа</h3>
          {result.isPending ? (
            <Loading />
          ) : result.error ? (
            <ErrorView error={result.error} retry={() => void result.refetch()} />
          ) : !result.data.items.length ? (
            <Empty>Экспортов пока нет.</Empty>
          ) : (
            result.data.items.map((file) => (
              <button
                key={file.name}
                disabled={task.pending}
                onClick={() => download(file.name, file.filename)}
              >
                <span>
                  {file.description}
                  <small>
                    {file.filename} ·{' '}
                    {file.size_bytes === null
                      ? 'Размер при скачивании'
                      : `${number(file.size_bytes / 1024)} КБ`}
                  </small>
                </span>
              </button>
            ))
          )}
          {task.pending && <Loading label="Подготовка файла…" />}
          {task.error && <ErrorView error={task.error} />}
          <button onClick={() => setOpen(false)}>Закрыть</button>
        </div>
      )}
    </div>
  );
}
