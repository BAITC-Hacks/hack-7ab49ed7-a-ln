import { useEffect, useRef, useState } from 'react';
import type { AssistantAnswer, Methodology, Subgraph } from '../api/types';
import type { GraphFactory, GraphRenderer } from '../graph/types';
import { Empty, Gid, Pager, RoleChip, Warnings } from './Common';
import { money, number, score } from '../format';
import s from './GraphView.module.css';

export function GraphView({
  data,
  methodology,
  selected,
  onSelect,
  factory,
  highlight,
  fitIds,
}: {
  data: Subgraph;
  methodology: Methodology;
  selected: string | null;
  onSelect: (id: string) => void;
  factory?: GraphFactory;
  highlight?: AssistantAnswer['highlight'];
  fitIds?: string[];
}) {
  const [colorBy, setColorBy] = useState<'role' | 'cluster'>('role');
  const [table, setTable] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const container = useRef<HTMLDivElement>(null);
  const adapter = useRef<GraphRenderer | null>(null);
  const callback = useRef(onSelect);
  useEffect(() => {
    callback.current = onSelect;
  }, [onSelect]);
  const showTable = table || !!failure;
  const hasNodes = data.nodes.length > 0;
  useEffect(() => {
    if (showTable || !container.current) return;
    let disposed = false;
    const fail = (error: Error) => {
      queueMicrotask(() => {
        if (!disposed) setFailure(error.message);
      });
    };
    const initialize = async () => {
      try {
        const create = factory ?? (await import('../graph/adapter')).createGraphRenderer;
        if (disposed || !container.current) return;
        adapter.current = create(container.current, (id) => callback.current(id), fail);
        setRevision((value) => value + 1);
      } catch (error) {
        fail(new Error('WebGL недоступен. Используйте таблицу узлов.', { cause: error }));
      }
    };
    void initialize();
    return () => {
      disposed = true;
      adapter.current?.destroy();
      adapter.current = null;
    };
  }, [factory, showTable, hasNodes]);
  useEffect(() => {
    adapter.current?.replace(data);
    adapter.current?.zoom('reset');
  }, [data, showTable, revision]);
  useEffect(() => {
    adapter.current?.style({
      colorBy,
      selected: highlight?.nodes.length ? null : selected,
      methodology,
      highlight,
    });
  }, [colorBy, selected, methodology, highlight, data, showTable, revision]);
  useEffect(() => {
    if (fitIds) adapter.current?.fit(fitIds);
  }, [fitIds, data, showTable, revision]);
  return (
    <section className={s.frame} aria-label="Сеть переводов">
      <div className={s.toolbar}>
        <div>
          <strong>Сеть переводов</strong>
          <small>
            {data.truncated
              ? `Показано ${number(data.nodes.length)} из ${number(data.total_nodes)} узлов`
              : `${number(data.nodes.length)} узлов`}{' '}
            · {number(data.edges.length)} из {number(data.total_edges)} связей
          </small>
        </div>
        <label>
          Цвет{' '}
          <select value={colorBy} onChange={(e) => setColorBy(e.target.value as 'role' | 'cluster')}>
            <option value="role">По роли</option>
            <option value="cluster">По кластеру</option>
          </select>
        </label>
        <button aria-pressed={showTable} onClick={() => setTable(!showTable)} disabled={!!failure}>
          {showTable ? 'Граф' : 'Таблица'}
        </button>
      </div>
      {data.truncated && (
        <Warnings
          items={[
            `Часть сети скрыта: достигнут лимит ${data.truncation_reason === 'max_edges' ? 'связей' : 'узлов'}. Список клиентов и поиск работают по полной выгрузке.`,
          ]}
        />
      )}
      {failure && <Warnings items={[failure]} />}
      {!data.nodes.length ? (
        <Empty>В выбранной части графа нет узлов. Измените фильтры.</Empty>
      ) : showTable ? (
        <div className={s.fallback}>
          <table>
            <thead>
              <tr>
                <th>Клиент</th>
                <th>Роль</th>
                <th>Приоритет</th>
                <th>Вход / выход</th>
              </tr>
            </thead>
            <tbody>
              {data.nodes.slice(offset, offset + 25).map((n) => (
                <tr key={n.id}>
                  <td>
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
                </tr>
              ))}
            </tbody>
          </table>
          <Pager offset={offset} limit={25} total={data.nodes.length} onChange={setOffset} />
        </div>
      ) : (
        <div className={s.canvasArea}>
          <div
            ref={container}
            className={s.canvas}
            aria-label="Интерактивный направленный граф. Для клавиатурной навигации переключитесь в таблицу."
          />
          <div className={s.zoom}>
            <button aria-label="Приблизить" onClick={() => adapter.current?.zoom('in')}>
              +
            </button>
            <button aria-label="Отдалить" onClick={() => adapter.current?.zoom('out')}>
              −
            </button>
            <button aria-label="Показать весь граф" onClick={() => adapter.current?.zoom('reset')}>
              ⌖
            </button>
          </div>
          <div className={s.hint}>Прокрутка — масштаб · перетаскивание — обзор · клик — карточка</div>
        </div>
      )}
      <div className={s.legend}>
        {colorBy === 'role' ? (
          methodology.role_order.map((role) => <RoleChip key={role} role={role} methodology={methodology} />)
        ) : (
          <span>Цвет обозначает принадлежность к кластеру</span>
        )}
        <span>◎ Исходный клиент</span>
        <span>Бледный цвет — граница выгрузки</span>
        <span>Размер — приоритет · стрелка — направление</span>
      </div>
    </section>
  );
}
