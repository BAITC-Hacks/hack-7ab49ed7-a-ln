import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { server } from '../testSetup';
import { API_BASE } from '../api/base';
import { WorkspacePage } from '../pages/WorkspacePage';
import run from '../mocks/fixtures/run_succeeded.json';
import node from '../mocks/fixtures/node_detail.json';

function capturedHandlers() {
  const fixtures = import.meta.glob('../mocks/fixtures/*.json', { eager: true, import: 'default' });
  const paths: Record<string, string> = {
    meta: 'meta',
    methodology: 'methodology',
    [`runs/${run.id}`]: 'run_succeeded',
    [`runs/${run.id}/graph`]: 'graph',
    [`runs/${run.id}/top`]: 'top',
    [`runs/${run.id}/overview`]: 'overview',
    [`runs/${run.id}/nodes/${node.id}`]: 'node_detail',
    [`runs/${run.id}/nodes/${node.id}/counterparties`]: 'counterparties_in',
  };
  return Object.entries(paths).map(([path, name]) =>
    http.get(`${API_BASE}/${path}`, () =>
      HttpResponse.json(fixtures[`../mocks/fixtures/${name}.json`] as never),
    ),
  );
}
it('renders a real node card and server explanations without numeric ID conversion', async () => {
  server.use(...capturedHandlers());
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/runs/${run.id}?node=${node.id}`]}>
        <Routes>
          <Route path="/runs/:runId" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole('heading', { name: node.id })).toBeInTheDocument();
  expect(screen.getByText(node.evidence, { exact: true })).toBeInTheDocument();
  expect(screen.getByText('Компоненты приоритета', { exact: true })).toBeInTheDocument();
});
