import { useSearchParams } from 'react-router-dom';
import { useMethodology } from '../hooks/queries';
import { ErrorView, Loading, RoleChip, Warnings } from '../components/Common';
import { CAUTION, share } from '../format';
import s from './Pages.module.css';

export function MethodologyPage() {
  const [params] = useSearchParams();
  const result = useMethodology(params.get('run_id') ?? undefined);
  if (result.isPending) return <Loading />;
  if (result.error) return <ErrorView error={result.error} retry={() => void result.refetch()} />;
  const data = result.data;
  return (
    <div className={s.method}>
      <div className={s.heading}>
        <div>
          <span className={s.eyebrow}>Объяснимый анализ</span>
          <h1>Методология</h1>
          <p>{CAUTION}.</p>
        </div>
      </div>
      <section className={s.card}>
        <h2>Роли и правила назначения</h2>
        <p className={s.muted}>
          Правила применяются в указанном порядке. Уверенность в роли не является вероятностью противоправной
          деятельности.
        </p>
        <div className={s.rules}>
          {data.role_order.map((role, i) => (
            <article key={role}>
              <strong>
                {i + 1}. <RoleChip role={role} methodology={data} />
              </strong>
              <p>{data.roles[role].rule}</p>
            </article>
          ))}
        </div>
      </section>
      <section className={s.card}>
        <h2>Из чего складывается приоритет</h2>
        <table>
          <thead>
            <tr>
              <th>Компонент</th>
              <th>Вес</th>
            </tr>
          </thead>
          <tbody>
            {data.priority_components.map((c) => (
              <tr key={c.key}>
                <td>{c.label}</td>
                <td>{share(c.weight)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className={s.card}>
        <h2>Сигналы для проверки</h2>
        <dl className={s.terms}>
          {Object.entries(data.flags).map(([key, label]) => (
            <div key={key} style={{ display: 'contents' }}>
              <dt>{key}</dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className={s.card}>
        <h2>Границы наблюдения</h2>
        <Warnings items={data.limitations} />
      </section>
    </div>
  );
}
