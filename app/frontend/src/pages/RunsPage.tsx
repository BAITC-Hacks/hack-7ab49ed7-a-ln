import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Run } from '../api/types';
import { busy, canRetry, pollInterval, useMeta } from '../hooks/queries';
import {
  ConfirmDialog,
  Empty,
  ErrorView,
  Loading,
  Pager,
  RunFailure,
  RunStatus,
  Warnings,
} from '../components/Common';
import { date, money, number, share } from '../format';
import { validateFiles } from './uploadValidation';
import s from './Pages.module.css';

export function RunsPage() {
  const [offset, setOffset] = useState(0);
  const [confirm, setConfirm] = useState<{ run: Run; action: 'cancel' | 'retry' | 'delete' } | null>(null);
  const navigate = useNavigate();
  const client = useQueryClient();
  const runs = useQuery({
    queryKey: ['runs', offset],
    queryFn: ({ signal }) => api.runs(offset, signal),
    refetchInterval: (q) => {
      const intervals = q.state.data?.items.filter(busy).map((r) => pollInterval(r) || 1500);
      return intervals?.length ? Math.min(...intervals) : false;
    },
  });
  const demo = useMutation({
    mutationFn: api.demo,
    onSuccess: (run) => {
      void client.invalidateQueries({ queryKey: ['runs'] });
      navigate(`/runs/${run.id}`);
    },
  });
  const action = useMutation({
    mutationFn: async ({ run, action }: NonNullable<typeof confirm>) => {
      await api[action](run.id);
    },
    onSuccess: () => {
      setConfirm(null);
      void client.invalidateQueries({ queryKey: ['runs'] });
      void client.invalidateQueries({ queryKey: ['run'] });
    },
  });
  const names = { cancel: 'Отменить анализ', retry: 'Повторить анализ', delete: 'Удалить исследование' };
  return (
    <>
      <div className={s.heading}>
        <div>
          <span className={s.eyebrow}>Анализ транзакционных связей</span>
          <h1>Исследования</h1>
          <p>От выгрузки переводов — к объяснимым гипотезам и приоритетам проверки.</p>
        </div>
        <button onClick={() => demo.mutate()} disabled={demo.isPending}>
          {demo.isPending ? 'Создание…' : 'Запустить на демо-данных'} <span aria-hidden>↗</span>
        </button>
      </div>
      {demo.error && <ErrorView error={demo.error} />}
      <div className={s.columns}>
        <section className={s.card} aria-label="Список исследований">
          <div className={s.heading}>
            <h2>Последние исследования</h2>
            <span className={s.muted}>{runs.data ? `${number(runs.data.total)} всего` : ''}</span>
          </div>
          {runs.isPending ? (
            <Loading />
          ) : runs.error ? (
            <ErrorView error={runs.error} retry={() => void runs.refetch()} />
          ) : !runs.data.items.length ? (
            <Empty>Исследований пока нет. Загрузите выгрузку или начните с демо-данных.</Empty>
          ) : (
            runs.data.items.map((run) => (
              <article className={s.run} key={run.id}>
                <div className={s.runHeader}>
                  <h3>
                    <Link to={`/runs/${run.id}`}>{run.name || 'Без названия'}</Link>
                  </h3>
                  <RunStatus run={run} />
                </div>
                <div className={s.runMeta}>
                  <span>Создано {date(run.created_at)}</span>
                  {run.summary && (
                    <>
                      <span>{number(run.summary.n_nodes)} клиентов</span>
                      <span>{money(run.summary.total_kzt)}</span>
                      <span>
                        {date(run.summary.period[0])} — {date(run.summary.period[1])}
                      </span>
                    </>
                  )}
                </div>
                <Warnings items={run.warnings} />
                {run.error && (
                  <RunFailure error={run.error} needsUpload={run.status === 'failed' && !canRetry(run)} />
                )}
                <div className={s.actions}>
                  <Link className="button" to={`/runs/${run.id}`}>
                    {run.status === 'succeeded' ? 'Открыть исследование →' : 'Состояние анализа →'}
                  </Link>
                  {busy(run) && (
                    <button
                      disabled={run.cancel_requested}
                      onClick={() => {
                        action.reset();
                        setConfirm({ run, action: 'cancel' });
                      }}
                    >
                      Отменить
                    </button>
                  )}
                  {canRetry(run) && (
                    <button
                      onClick={() => {
                        action.reset();
                        setConfirm({ run, action: 'retry' });
                      }}
                    >
                      Повторить
                    </button>
                  )}
                  {run.status !== 'running' && (
                    <button
                      className={s.dangerText}
                      onClick={() => {
                        action.reset();
                        setConfirm({ run, action: 'delete' });
                      }}
                    >
                      Удалить
                    </button>
                  )}
                </div>
              </article>
            ))
          )}
          {runs.data && <Pager offset={offset} limit={20} total={runs.data.total} onChange={setOffset} />}
        </section>
        <UploadForm />
      </div>
      {confirm && (
        <ConfirmDialog
          title={names[confirm.action]}
          onClose={() => setConfirm(null)}
          pending={action.isPending}
          onConfirm={() => action.mutate(confirm)}
        >
          <p>«{confirm.run.name}»</p>
          <p>
            {confirm.action === 'delete'
              ? 'Входные файлы и результаты будут удалены. Это действие нельзя отменить.'
              : confirm.action === 'cancel'
                ? 'Выполнение текущего анализа будет остановлено.'
                : 'Анализ будет запущен заново с теми же входными файлами.'}
          </p>
          {action.error && <ErrorView error={action.error} />}
        </ConfirmDialog>
      )}
    </>
  );
}
function UploadForm() {
  const { hash } = useLocation();
  const nameInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (hash === '#upload') nameInput.current?.focus();
  }, [hash]);
  const meta = useMeta();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const upload = useMutation({
    mutationFn: (form: FormData) => {
      controller.current = new AbortController();
      return api.upload(form, setProgress, controller.current.signal);
    },
    onSuccess: (run) => {
      void client.invalidateQueries({ queryKey: ['runs'] });
      navigate(`/runs/${run.id}`);
    },
  });
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!meta.data) return;
    const issue = validateFiles(files, meta.data.limits);
    if (issue) {
      setError(issue);
      return;
    }
    const form = new FormData(event.currentTarget);
    form.delete('files');
    const start = String(form.get('observation_start') ?? '');
    const end = String(form.get('observation_end') ?? '');
    if (start && end && start > end) {
      setError('Начало окна наблюдения должно быть не позже окончания.');
      return;
    }
    for (const [key, value] of [...form.entries()]) if (value === '') form.delete(key);
    files.forEach((file) => form.append('files', file));
    setError(null);
    setProgress(0);
    upload.mutate(form);
  };
  return (
    <aside className={s.card} id="upload">
      <span className={s.eyebrow}>Новое исследование</span>
      <h2>Загрузить выгрузку</h2>
      <form onSubmit={submit} className={s.form}>
        <label>
          Название
          <input
            ref={nameInput}
            name="name"
            placeholder="Например, переводы за август"
            maxLength={160}
            disabled={upload.isPending}
          />
        </label>
        <label className={s.upload}>
          Файлы данных
          <input
            aria-label="Файлы данных"
            type="file"
            name="files"
            accept=".zip,.parquet"
            multiple
            disabled={upload.isPending}
            onChange={(e) => {
              const selected = Array.from(e.target.files ?? []);
              setFiles(selected);
              setError(meta.data ? validateFiles(selected, meta.data.limits) : null);
            }}
          />
          <small>
            Один ZIP или три Parquet: edges, nodes, transactions. До {meta.data?.limits.max_upload_mb ?? '…'}{' '}
            МБ суммарно.
          </small>
          {files.length > 0 && (
            <ul>
              {files.map((file) => (
                <li key={file.name}>
                  {file.name} · {number(file.size / 1024)} КБ
                </li>
              ))}
            </ul>
          )}
        </label>
        <details>
          <summary>Параметры сбора данных</summary>
          <div className={s.fields}>
            <label>
              Начало наблюдения
              <input type="date" name="observation_start" disabled={upload.isPending} />
            </label>
            <label>
              Конец наблюдения
              <input type="date" name="observation_end" disabled={upload.isPending} />
            </label>
            <label>
              Глубина обхода
              <input
                type="number"
                name="max_depth"
                min="1"
                step="1"
                placeholder="По данным"
                disabled={upload.isPending}
              />
            </label>
            <label>
              Порог перевода, ₸
              <input
                type="number"
                name="min_transfer_kzt"
                min="0.01"
                step="0.01"
                placeholder="По данным"
                disabled={upload.isPending}
              />
            </label>
          </div>
          <p className={s.muted}>
            Направление сбора: исходящие переводы. Если окно не указано, сервер выберет значения по данным и
            покажет предупреждение.
          </p>
        </details>
        <small>
          До {number(meta.data?.limits.max_nodes ?? 0)} узлов и{' '}
          {number(meta.data?.limits.max_transactions ?? 0)} операций. Структуру Parquet и содержимое архива
          проверяет сервер.
        </small>
        {error && (
          <p role="alert" className={s.dangerText}>
            {error}
          </p>
        )}
        {upload.error && <ErrorView error={upload.error} />}
        {upload.isPending && (
          <div role="status">
            <progress max={1} value={progress} aria-label="Загрузка файлов" className={s.bar} />
            <small>
              {progress === 1
                ? 'Файлы переданы. Сервер проверяет данные…'
                : `Загрузка файлов: ${share(progress)}`}
            </small>
          </div>
        )}
        <button className="primary" disabled={upload.isPending || !files.length || !meta.data}>
          {upload.isPending ? 'Загрузка и проверка…' : 'Загрузить и запустить анализ'}
        </button>
      </form>
    </aside>
  );
}
