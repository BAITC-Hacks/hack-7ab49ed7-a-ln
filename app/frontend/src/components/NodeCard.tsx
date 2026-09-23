import { useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Methodology, NodeDetail, Role, Subgraph } from '../api/types';
import { date, metric, money, number, score, share } from '../format';
import { Empty, ErrorView, Gid, Loading, Pager, RoleChip } from './Common';
import s from './Panels.module.css';

export interface NodeActions {
  select: (id: string) => void;
  graph: (label: string, work: (signal: AbortSignal) => Promise<Subgraph>) => void;
  path: (source: string, target: string) => void;
}
export function NodeCard({
  runId,
  gid,
  methodology,
  actions,
}: {
  runId: string;
  gid: string | null;
  methodology: Methodology;
  actions: NodeActions;
}) {
  const node = useQuery({
    queryKey: ['node', runId, gid],
    queryFn: ({ signal }) => api.node(runId, gid!, signal),
    enabled: !!gid,
  });
  if (!gid) return <Empty>Выберите клиента на графе, в приоритетном списке или найдите его по ID.</Empty>;
  if (node.isPending) return <Loading label="Загрузка карточки…" />;
  if (node.error) return <ErrorView error={node.error} retry={() => void node.refetch()} />;
  const data = node.data;
  return (
    <article className={s.nodeCard}>
      <span className={s.eyebrow}>Клиент · идентификатор</span>
      <h2 className={s.nodeId}>{data.id}</h2>
      <RoleChip role={data.role} methodology={methodology} />
      <div className={s.scores}>
        <div>
          <strong>{score(data.priority_score)}</strong>
          <span>Приоритет · № {data.priority_rank}</span>
        </div>
        <div>
          <strong>{score(data.role_score)}</strong>
          <span>Оценка роли</span>
        </div>
      </div>
      <p className={s.meta}>
        Кластер {data.cluster_id} · Колено {data.depth}
        {data.is_seed ? ' · Исходный клиент' : ''}
        {data.truncated ? ' · Граница выгрузки' : ''}
        {data.top_rank ? ` · № ${data.top_rank} в топе` : ''}
      </p>
      <div className={s.evidence}>
        <strong>Основание гипотезы</strong>
        <p>{data.evidence}</p>
        {data.why && <p>{data.why}</p>}
      </div>
      <div className={s.flows}>
        <div>
          <span>↘ Входящие</span>
          <strong>{money(data.in_kzt)}</strong>
          <small>
            {number(data.in_deg)} плательщиков · {number(data.in_tx)} операций
          </small>
        </div>
        <div>
          <span>↗ Исходящие</span>
          <strong>{money(data.out_kzt)}</strong>
          <small>
            {number(data.out_deg)} получателей · {number(data.out_tx)} операций
          </small>
        </div>
      </div>
      <NodeOperations key={gid} runId={runId} gid={gid} actions={actions} />
      <div className={s.flags}>
        {data.flags.map((flag) => (
          <span key={flag}>{methodology.flags[flag] ?? flag}</span>
        ))}
      </div>
      <NodeMetrics data={data} methodology={methodology} />
      <details>
        <summary>Полное описание</summary>
        <p className={s.preserve}>{data.card}</p>
      </details>
      <Counterparties
        key={`${gid}:in`}
        runId={runId}
        gid={gid}
        direction="in"
        methodology={methodology}
        onSelect={actions.select}
      />
      <Counterparties
        key={`${gid}:out`}
        runId={runId}
        gid={gid}
        direction="out"
        methodology={methodology}
        onSelect={actions.select}
      />
      <Transactions key={gid} runId={runId} gid={gid} onSelect={actions.select} />
    </article>
  );
}
function NodeMetrics({ data, methodology }: { data: NodeDetail; methodology: Methodology }) {
  return (
    <>
      <h3>Показатели для проверки</h3>
      {data.metrics.length ? (
        <dl className={s.metrics}>
          {data.metrics.map((item) => (
            <div key={item.key}>
              <dt>{item.label}</dt>
              <dd>{metric(item.value, item.unit)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <Empty>Дополнительных показателей нет.</Empty>
      )}
      <details open>
        <summary>Компоненты приоритета</summary>
        <p className={s.meta}>Поправочный коэффициент приоритета: {number(data.priority_reliability)}×.</p>
        <div className={s.components}>
          {data.priority_components.map((item) => (
            <div key={item.key}>
              <span>
                {item.label} <small>вес {share(item.weight)}</small>
              </span>
              <strong>{score(item.contribution)}</strong>
              <meter min={0} max={1} value={item.contribution} aria-label={`Вклад: ${item.label}`} />
              <small>Значение: {number(item.value)}</small>
            </div>
          ))}
        </div>
      </details>
      <details>
        <summary>Проверка правил ролей</summary>
        <ul className={s.ruleList}>
          {Object.entries(data.rules).map(([role, matched]) => (
            <li key={role}>
              <span aria-label={matched ? 'Правило выполнено' : 'Правило не выполнено'}>
                {matched ? '✓' : '−'}
              </span>
              <div>
                <strong>{methodology.roles[role as Role]?.label ?? role}</strong>
                <p>{methodology.roles[role as Role]?.rule}</p>
              </div>
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}
function NodeOperations({ runId, gid, actions }: { runId: string; gid: string; actions: NodeActions }) {
  const [target, setTarget] = useState('');
  const [depth, setDepth] = useState(1);
  const [direction, setDirection] = useState('both');
  const path = (e: FormEvent) => {
    e.preventDefault();
    actions.path(gid, target);
  };
  return (
    <div className={s.operations}>
      <div className={s.buttonRow}>
        <button
          onClick={() =>
            actions.graph('Откуда могли поступить деньги', (signal) => api.trace(runId, gid, 'up', signal))
          }
        >
          ← Откуда деньги
        </button>
        <button
          onClick={() =>
            actions.graph('Куда могли уйти деньги', (signal) => api.trace(runId, gid, 'down', signal))
          }
        >
          Куда ушли →
        </button>
      </div>
      <p className={s.meta}>
        Трассировка показывает достижимость по графу, а не доказанное движение конкретных денег.
      </p>
      <details>
        <summary>Окружение и путь</summary>
        <div className={s.inlineForm}>
          <label>
            Глубина
            <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
              {[1, 2, 3].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            Направление
            <select value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="both">Оба</option>
              <option value="in">Входящие</option>
              <option value="out">Исходящие</option>
            </select>
          </label>
          <button
            onClick={() =>
              actions.graph('Окружение клиента', (signal) =>
                api.neighborhood(runId, gid, depth, direction, signal),
              )
            }
          >
            Показать
          </button>
        </div>
        <form onSubmit={path} className={s.pathForm}>
          <label>
            Путь к клиенту
            <input
              value={target}
              inputMode="numeric"
              pattern="[0-9]{18}"
              maxLength={18}
              placeholder="Полный ID · 18 цифр"
              onChange={(e) => setTarget(e.target.value.replace(/\D/g, ''))}
              required
            />
          </label>
          <button disabled={target.length !== 18}>Найти путь</button>
        </form>
      </details>
    </div>
  );
}
function Counterparties({
  runId,
  gid,
  direction,
  methodology,
  onSelect,
}: {
  runId: string;
  gid: string;
  direction: 'in' | 'out';
  methodology: Methodology;
  onSelect: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const result = useQuery({
    queryKey: ['counterparties', runId, gid, direction, offset],
    queryFn: ({ signal }) => api.counterparties(runId, gid, direction, offset, signal),
  });
  return (
    <section className={s.section}>
      <h3>
        {direction === 'in' ? 'Плательщики' : 'Получатели'}{' '}
        {result.data && <span className={s.meta}>· {result.data.total}</span>}
      </h3>
      {result.isPending ? (
        <Loading />
      ) : result.error ? (
        <ErrorView error={result.error} retry={() => void result.refetch()} />
      ) : !result.data.items.length ? (
        <Empty>Переводов в выгрузке нет. Операции вне выборки неизвестны.</Empty>
      ) : (
        <>
          <div className={s.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Клиент / роль</th>
                  <th>Сумма / период</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Gid id={item.id} onSelect={onSelect} />
                      <RoleChip role={item.role} methodology={methodology} />
                    </td>
                    <td>
                      {money(item.sum_kzt)}
                      <small>
                        {item.n_tx} операций
                        <br />
                        {date(item.first_date)} — {date(item.last_date)}
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={10} total={result.data.total} onChange={setOffset} />
        </>
      )}
    </section>
  );
}
function Transactions({
  runId,
  gid,
  onSelect,
}: {
  runId: string;
  gid: string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [direction, setDirection] = useState<'in' | 'out' | 'both'>('both');
  const [counterparty, setCounterparty] = useState('');
  const [offset, setOffset] = useState(0);
  const validCounterparty = !counterparty || /^\d{18}$/.test(counterparty);
  const result = useQuery({
    queryKey: ['transactions', runId, gid, direction, counterparty, offset],
    queryFn: ({ signal }) => api.transactions(runId, gid, direction, counterparty, offset, signal),
    enabled: open && validCounterparty,
  });
  return (
    <details className={s.section} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Операции по датам</summary>
      <div className={s.inlineForm}>
        <label>
          Направление
          <select
            value={direction}
            onChange={(e) => {
              setDirection(e.target.value as typeof direction);
              setOffset(0);
            }}
          >
            <option value="both">Все</option>
            <option value="in">Входящие</option>
            <option value="out">Исходящие</option>
          </select>
        </label>
        <label>
          Контрагент
          <input
            inputMode="numeric"
            placeholder="ID · необязательно"
            value={counterparty}
            maxLength={18}
            onChange={(e) => {
              setCounterparty(e.target.value.replace(/\D/g, ''));
              setOffset(0);
            }}
          />
        </label>
      </div>
      {!validCounterparty ? (
        <p className={s.meta}>Введите полный ID из 18 цифр.</p>
      ) : result.isPending ? (
        <Loading />
      ) : result.error ? (
        <ErrorView error={result.error} retry={() => void result.refetch()} />
      ) : !result.data.items.length ? (
        <Empty>Операции не найдены.</Empty>
      ) : (
        <>
          <div className={s.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Дата / сумма</th>
                  <th>Отправитель → получатель</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((tx, i) => (
                  <tr key={`${tx.date}:${offset + i}`}>
                    <td>
                      {date(tx.date)}
                      <small>{money(tx.sum_kzt)}</small>
                    </td>
                    <td>
                      <Gid id={tx.source} onSelect={onSelect} />
                      <br />→ <Gid id={tx.target} onSelect={onSelect} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager offset={offset} limit={20} total={result.data.total} onChange={setOffset} />
        </>
      )}
    </details>
  );
}
