import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { expect, it } from 'vitest';
import { API_BASE } from '../api/base';
import type { Run } from '../api/types';
import { createDemoData } from '../mocks/data';
import { server } from '../testSetup';
import { RunsPage } from './RunsPage';
import { WorkspacePage } from './WorkspacePage';

function renderPage(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it.each(['list', 'workspace'])('keeps polling during cancellation in the %s', async (view) => {
  let run: Run = {
    ...createDemoData().run,
    status: 'running',
    cancel_requested: true,
    stage_label: 'Расчёт признаков',
    poll_after_ms: 500,
  };
  server.use(
    http.get(`${API_BASE}/runs`, () => HttpResponse.json({ items: [run], total: 1 })),
    http.get(`${API_BASE}/runs/${run.id}`, () => HttpResponse.json(run)),
  );
  renderPage(view === 'list' ? '/runs' : `/runs/${run.id}`);
  expect(await screen.findByText('Отмена…', { exact: true })).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: view === 'list' ? 'Отменить' : 'Отменить анализ' }),
  ).toBeDisabled();
  expect(screen.queryByText('Расчёт признаков')).not.toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();

  run = { ...run, status: 'cancelled', stage_label: null, poll_after_ms: null };
  expect(await screen.findByText('Отменён', { exact: true })).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: view === 'list' ? 'Повторить' : 'Повторить анализ' }),
  ).toBeEnabled();
});

it.each(['list', 'workspace'])('shows worker validation details in the %s', async (view) => {
  const run: Run = {
    ...createDemoData().run,
    status: 'failed',
    error: {
      code: 'validation_error',
      message: 'Данные не прошли проверку.',
      retryable: false,
      details: [{ field: 'transactions.sum', message: 'Сумма должна быть положительной.' }],
    },
  };
  server.use(
    http.get(`${API_BASE}/runs`, () => HttpResponse.json({ items: [run], total: 1 })),
    http.get(`${API_BASE}/runs/${run.id}`, () => HttpResponse.json(run)),
  );
  renderPage(view === 'list' ? '/runs' : `/runs/${run.id}`);
  expect(await screen.findByRole('alert')).toHaveTextContent('Данные не прошли проверку.');
  expect(screen.getByRole('alert')).toHaveTextContent('transactions.sum: Сумма должна быть положительной.');
  expect(screen.queryByRole('button', { name: /Повторить/ })).not.toBeInTheDocument();
  expect(
    screen.getByText('Исправьте данные и загрузите выгрузку заново.', { exact: false }),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole('link', { name: 'Загрузить исправленную выгрузку' }));
  expect(await screen.findByRole('textbox', { name: 'Название' })).toHaveFocus();
});

it.each(['list', 'workspace'])('allows retryable failures to be retried in the %s', async (view) => {
  const run: Run = {
    ...createDemoData().run,
    status: 'failed',
    stage_code: null,
    stage_label: null,
    error: { code: 'timeout', message: 'Время анализа истекло.', retryable: true, details: null },
  };
  server.use(
    http.get(`${API_BASE}/runs`, () => HttpResponse.json({ items: [run], total: 1 })),
    http.get(`${API_BASE}/runs/${run.id}`, () => HttpResponse.json(run)),
  );
  renderPage(view === 'list' ? '/runs' : `/runs/${run.id}`);
  expect(
    await screen.findByRole('button', { name: view === 'list' ? 'Повторить' : 'Повторить анализ' }),
  ).toBeEnabled();
  expect(screen.queryByRole('link', { name: 'Загрузить исправленную выгрузку' })).not.toBeInTheDocument();
});
