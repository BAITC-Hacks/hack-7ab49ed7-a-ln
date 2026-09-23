import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Methodology, Overview as OverviewData } from '../api/types';
import { Empty, ErrorView, Gid, Loading, Pager, RoleChip, Warnings } from './Common';
import { money, number, share } from '../format';
import s from '../pages/Pages.module.css';

export function Overview({ runId, methodology }: { runId: string; methodology: Methodology }) {
  const result = useQuery({
    queryKey: ['overview', runId],
    queryFn: ({ signal }) => api.overview(runId, signal),
  });
  if (result.isPending) return <Loading />;
  if (result.error) return <ErrorView error={result.error} retry={() => void result.refetch()} />;
  const data = result.data;
  return (
    <>
      <Warnings items={data.warnings} />
      <div className={s.stats}>
        {[
          ['Клиентов', number(data.summary.n_nodes)],
          ['Связей', number(data.summary.n_edges)],
          ['Переводов', number(data.summary.n_tx)],
          ['Видимый оборот', money(data.summary.total_kzt)],
        ].map(([label, value]) => (
          <div className={s.stat} key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <div className={s.overviewGrid}>
        <section className={s.card}>
          <h2>Гипотезы ролей</h2>
          {methodology.role_order.map((role) => (
            <div className={s.roleRow} key={role}>
              <RoleChip role={role} methodology={methodology} />
              <progress
                max={Math.max(1, data.summary.n_nodes)}
                value={data.summary.roles[role] ?? 0}
                aria-label={methodology.roles[role].label}
              />
              <strong>{number(data.summary.roles[role] ?? 0)}</strong>
            </div>
          ))}
        </section>
        <ModelCard model={data.model} />
        <section className={`${s.card} ${s.wide}`}>
          <h2>Устойчивость сети</h2>
          <p className={s.muted}>
            Сравнение удаления приоритетных узлов со случайным удалением. Значения показываются в единицах
            расчёта сервера.
          </p>
          <div className={s.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Удалено</th>
                  <th>Достижимость · топ / случайно</th>
                  <th>Поток · топ / случайно</th>
                  <th>Компоненты · топ / случайно</th>
                </tr>
              </thead>
              <tbody>
                {data.resilience.rows.map((r) => (
                  <tr key={r.removed_top_n}>
                    <td>{r.removed_top_n}</td>
                    <td>
                      {share(r.reach_top)} / {share(r.reach_random)}
                    </td>
                    <td>
                      {share(r.flow_top)} / {share(r.flow_random)}
                    </td>
                    <td>
                      {number(r.components_top)} / {number(r.components_random)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.resilience.rows.length && <Empty>Недостаточно данных для сравнения.</Empty>}
          </div>
        </section>
        <section className={s.card}>
          <h2>Запросы дополнительных данных</h2>
          {Object.entries(data.data_requests).length ? (
            Object.entries(data.data_requests).map(([key, value]) => (
              <p key={key}>
                {key}: <strong>{number(value)}</strong>
              </p>
            ))
          ) : (
            <Empty>Дополнительные запросы не сформированы.</Empty>
          )}
        </section>
        <section className={s.card}>
          <h2>Ограничения интерпретации</h2>
          <Warnings items={methodology.limitations} />
        </section>
      </div>
    </>
  );
}
function ModelCard({ model }: { model: OverviewData['model'] }) {
  return (
    <section className={s.card}>
      <h2>Модель продолжения переводов</h2>
      {model.status === 'insufficient_data' ? (
        <Warnings items={['Недостаточно данных для надёжной оценки качества модели.']} />
      ) : (
        <div className={s.inlineStats}>
          <div>
            <span>AUC · кросс-валидация</span>
            <strong>{model.auc_cv === null ? '—' : number(model.auc_cv)}</strong>
          </div>
          <div>
            <span>AUC · перенос</span>
            <strong>{model.auc_transfer === null ? '—' : number(model.auc_transfer)}</strong>
          </div>
        </div>
      )}
      <p className={s.muted}>
        Обучающих примеров: {number(model.n_train)}. Базовая доля:{' '}
        {model.base_rate === null ? 'нет данных' : share(model.base_rate)}.
      </p>
      <p className={s.muted}>
        Это оценка продолжения переводов за границей выгрузки, а не качества определения противоправной
        деятельности.
      </p>
    </section>
  );
}
export function DataRequests({ runId, onSelect }: { runId: string; onSelect: (id: string) => void }) {
  const [offset, setOffset] = useState(0);
  const result = useQuery({
    queryKey: ['data-requests', runId, offset],
    queryFn: ({ signal }) => api.dataRequests(runId, offset, signal),
  });
  return (
    <section className={s.card}>
      <h2>Что запросить для проверки гипотез</h2>
      <p className={s.muted}>Следующие шаги помогают закрыть пробелы в наблюдаемом графе.</p>
      {result.isPending ? (
        <Loading />
      ) : result.error ? (
        <ErrorView error={result.error} retry={() => void result.refetch()} />
      ) : !result.data.items.length ? (
        <Empty>Запросы не сформированы.</Empty>
      ) : (
        result.data.items.map((item, i) => (
          <article className={s.dataRequest} key={`${item.id}:${i}`}>
            <Gid id={item.id} onSelect={onSelect} />
            <h3>{item.request}</h3>
            <p>{item.reason}</p>
            <small>Связанная сумма: {money(item.value_kzt)}</small>
          </article>
        ))
      )}
      {result.data && <Pager offset={offset} limit={25} total={result.data.total} onChange={setOffset} />}
    </section>
  );
}
