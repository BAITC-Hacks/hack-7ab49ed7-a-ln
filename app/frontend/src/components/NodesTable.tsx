import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Filters, Methodology, SortBy } from '../api/types';
import { Empty, ErrorView, Gid, Loading, Pager, RoleChip } from './Common';
import { money, score } from '../format';
import s from '../pages/Pages.module.css';

const sortOptions: Record<SortBy, string> = {
  priority_score: 'Приоритет',
  role_score: 'Оценка роли',
  in_kzt: 'Входящая сумма',
  out_kzt: 'Исходящая сумма',
  in_deg: 'Число плательщиков',
  out_deg: 'Число получателей',
  traced_in_kzt: 'Прослеженный вход',
  control_nodes: 'Контролируемые узлы',
};
export function NodesTable({
  runId,
  filters,
  methodology,
  onSelect,
}: {
  runId: string;
  filters: Filters;
  methodology: Methodology;
  onSelect: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<SortBy>('priority_score');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [flag, setFlag] = useState('');
  const [seed, setSeed] = useState('');
  const result = useQuery({
    queryKey: ['nodes', runId, filters, sort, order, offset, flag, seed],
    queryFn: ({ signal }) =>
      api.nodes(
        runId,
        { ...filters, flag, is_seed: seed ? seed === 'yes' : undefined },
        sort,
        order,
        offset,
        signal,
      ),
  });
  return (
    <section className={s.card}>
      <h2>Клиенты в выборке</h2>
      <div className={s.toolbar}>
        <label>
          Сортировать{' '}
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as SortBy);
              setOffset(0);
            }}
          >
            {Object.entries(sortOptions).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          aria-label="Изменить порядок сортировки"
          onClick={() => {
            setOrder(order === 'desc' ? 'asc' : 'desc');
            setOffset(0);
          }}
        >
          {order === 'desc' ? '↓ По убыванию' : '↑ По возрастанию'}
        </button>
        <label>
          Исходные{' '}
          <select
            value={seed}
            onChange={(e) => {
              setSeed(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Все</option>
            <option value="yes">Да</option>
            <option value="no">Нет</option>
          </select>
        </label>
        <label>
          Сигнал{' '}
          <select
            value={flag}
            onChange={(e) => {
              setFlag(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Все</option>
            {Object.entries(methodology.flags).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className={s.muted}>
        Таблица учитывает роль и кластер. Порог приоритета и скрытие периферии применяются только к графу.
      </p>
      {result.isPending ? (
        <Loading />
      ) : result.error ? (
        <ErrorView error={result.error} retry={() => void result.refetch()} />
      ) : !result.data.items.length ? (
        <Empty />
      ) : (
        <div className={s.tableWrap}>
          <table>
            <thead>
              <tr>
                <th>№ / клиент</th>
                <th>Роль</th>
                <th>Приоритет</th>
                <th>Вход / выход</th>
                <th>Основание гипотезы</th>
              </tr>
            </thead>
            <tbody>
              {result.data.items.map((n) => (
                <tr key={n.id}>
                  <td>
                    <small>
                      № {n.priority_rank} · кластер {n.cluster_id}
                    </small>
                    <Gid id={n.id} onSelect={onSelect} />
                    <small>
                      {n.is_seed ? 'Исходный клиент · ' : ''}
                      {n.truncated ? 'Граница выгрузки' : ''}
                    </small>
                  </td>
                  <td>
                    <RoleChip role={n.role} methodology={methodology} />
                  </td>
                  <td>{score(n.priority_score)}</td>
                  <td>
                    {money(n.in_kzt)}
                    <small>{money(n.out_kzt)}</small>
                  </td>
                  <td>{n.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {result.data && <Pager offset={offset} limit={25} total={result.data.total} onChange={setOffset} />}
    </section>
  );
}
