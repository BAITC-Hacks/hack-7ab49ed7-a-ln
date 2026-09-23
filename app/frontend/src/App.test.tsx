import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { expect, it } from 'vitest';
import { AppShell, LoginPage } from './App';
import { RunsPage } from './pages/RunsPage';
import { server } from './testSetup';
import { createHandlers } from './mocks/handlers';

function renderApp(initialEntry = '/runs') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/runs/protected" element={<h1>Исследование по ссылке</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}
it('requires a session only when auth is enabled, and handles a rejected token', async () => {
  server.resetHandlers(...createHandlers({ authRequired: true }));
  renderApp();
  const user = userEvent.setup();
  const token = await screen.findByLabelText('Токен доступа');
  await user.type(token, 'wrong-token');
  await user.click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Неверный токен');
  expect(screen.getByRole('alert')).toHaveTextContent('mock-request');
  await user.clear(token);
  await user.type(token, 'demo-token');
  await user.click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('heading', { name: 'Исследования' })).toBeInTheDocument();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});
it('clears private cached data when logging out', async () => {
  server.resetHandlers(...createHandlers({ authRequired: true }));
  const client = renderApp();
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('Токен доступа'), 'demo-token');
  await user.click(screen.getByRole('button', { name: 'Войти' }));
  await screen.findByRole('heading', { name: 'Исследования' });
  client.setQueryData(['node', 'private'], { id: 'private' });
  await user.click(screen.getByRole('button', { name: 'Выйти' }));
  await waitFor(() => expect(client.getQueryData(['node', 'private'])).toBeUndefined());
  expect(await screen.findByLabelText('Токен доступа')).toBeInTheDocument();
});

it('preserves a protected deep link after login', async () => {
  server.resetHandlers(...createHandlers({ authRequired: true }));
  renderApp('/runs/protected?node=100000000000000001');
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('Токен доступа'), 'demo-token');
  await user.click(screen.getByRole('button', { name: 'Войти' }));
  expect(await screen.findByRole('heading', { name: 'Исследование по ссылке' })).toBeInTheDocument();
});
