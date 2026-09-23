import { useEffect, useRef, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/errors';
import type { Methodology, Role, Run } from '../api/types';
import { number, share } from '../format';
import s from './Common.module.css';

export function Loading({ label = 'Загрузка данных…' }: { label?: string }) {
  return (
    <div role="status" className={s.state}>
      <span className={s.spinner} />
      {label}
    </div>
  );
}
export function Empty({ children = 'По выбранным условиям ничего не найдено.' }: { children?: ReactNode }) {
  return <div className={s.state}>{children}</div>;
}
export function ErrorView({ error, retry }: { error: unknown; retry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  return (
    <div role="alert" className={s.error}>
      <strong>{error instanceof Error ? error.message : 'Не удалось получить данные.'}</strong>
      {apiError?.details?.map((d, i) => (
        <p key={i}>
          {d.field}: {d.message}
        </p>
      ))}
      {apiError?.requestId && (
        <small>
          ID запроса: <code>{apiError.requestId}</code>
        </small>
      )}
      {retry && <button onClick={retry}>Повторить</button>}
    </div>
  );
}
export function RunFailure({
  error,
  needsUpload,
}: {
  error: NonNullable<Run['error']>;
  needsUpload: boolean;
}) {
  return (
    <>
      <ErrorView error={new ApiError(error)} />
      {needsUpload && (
        <p>
          Исправьте данные и загрузите выгрузку заново.{' '}
          <Link to="/runs#upload">Загрузить исправленную выгрузку</Link>
        </p>
      )}
    </>
  );
}
export function Warnings({ items }: { items: string[] }) {
  return items.length ? (
    <div className={s.warnings} role="note">
      {items.map((w, i) => (
        <p key={i}>ⓘ {w}</p>
      ))}
    </div>
  ) : null;
}
export function RoleChip({ role, methodology }: { role: Role; methodology?: Methodology }) {
  return (
    <span className={s.role}>
      <i style={{ background: methodology?.roles[role]?.color ?? '#607582' }} />
      {methodology?.roles[role]?.label ?? role}
    </span>
  );
}
const statusLabels: Record<Run['status'], string> = {
  queued: 'В очереди',
  running: 'Анализируется',
  succeeded: 'Готово',
  failed: 'Ошибка',
  cancelled: 'Отменён',
};
export function RunStatus({ run }: { run: Run }) {
  const cancelling = run.status === 'running' && run.cancel_requested;
  return (
    <div className={s.runStatus}>
      <span className={`${s.status} ${s[run.status]}`}>
        {cancelling ? 'Отмена…' : statusLabels[run.status]}
      </span>
      {run.stage_label && run.status !== 'succeeded' && !cancelling && <span>{run.stage_label}</span>}
      {(run.status === 'queued' || run.status === 'running') && !cancelling && (
        <>
          <progress max={1} value={run.progress ?? undefined} aria-label="Ход анализа" />
          <small>{run.progress === null ? 'Ожидание обновления' : share(run.progress)}</small>
        </>
      )}
    </div>
  );
}
export function Pager({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  return (
    <nav className={s.pager} aria-label="Страницы результатов">
      <span>
        {total
          ? `${number(offset + 1)}–${number(Math.min(offset + limit, total))} из ${number(total)}`
          : '0 результатов'}
      </span>
      <button
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
        aria-label="Предыдущая страница"
      >
        ←
      </button>
      <button
        disabled={offset + limit >= total}
        onClick={() => onChange(offset + limit)}
        aria-label="Следующая страница"
      >
        →
      </button>
    </nav>
  );
}
export function Gid({ id, onSelect }: { id: string; onSelect: (id: string) => void }) {
  return (
    <button
      className={s.gid}
      onClick={() => onSelect(id)}
      title={`Открыть клиента ${id}`}
      aria-label={`Открыть клиента ${id}`}
    >
      {id}
    </button>
  );
}
export function ConfirmDialog({
  title,
  children,
  onConfirm,
  onClose,
  pending = false,
}: {
  title: string;
  children: ReactNode;
  onConfirm: () => void;
  onClose: () => void;
  pending?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={s.dialog}
      aria-labelledby="confirmation-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onClose();
      }}
    >
      <h2 id="confirmation-title">{title}</h2>
      <div>{children}</div>
      <div className={s.actions}>
        <button autoFocus disabled={pending} onClick={onClose}>
          Назад
        </button>
        <button className="danger" disabled={pending} onClick={onConfirm}>
          {pending ? 'Выполняется…' : 'Подтвердить'}
        </button>
      </div>
    </dialog>
  );
}
