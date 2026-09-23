import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell, ErrorBoundary, LoginPage } from './App';
import { RunsPage } from './pages/RunsPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { MethodologyPage } from './pages/MethodologyPage';
import { ApiError } from './api/errors';
import './tokens.css';

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (count, error) => count < 1 && error instanceof ApiError && error.retryable,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});
async function start() {
  if (import.meta.env.VITE_MOCK_API === 'true') {
    const { createMockWorker } = await import('./mocks/browser');
    const worker = createMockWorker();
    await worker.start({ onUnhandledRequest: 'bypass' });
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ErrorBoundary>
        <QueryClientProvider client={client}>
          <BrowserRouter>
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/runs" element={<RunsPage />} />
                <Route path="/runs/:runId" element={<WorkspacePage />} />
                <Route path="/methodology" element={<MethodologyPage />} />
                <Route path="/login" element={<LoginPage />} />
                <Route path="*" element={<Navigate to="/runs" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </QueryClientProvider>
      </ErrorBoundary>
    </StrictMode>,
  );
}
void start();
