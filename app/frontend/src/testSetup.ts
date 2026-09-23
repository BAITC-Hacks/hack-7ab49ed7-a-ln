import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, afterAll, vi } from 'vitest';
import { setupServer } from 'msw/node';
import { createHandlers } from './mocks/handlers';

export const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  server.resetHandlers(...createHandlers());
  const nativeFetch = globalThis.fetch;
  vi.stubGlobal('fetch', (input: RequestInfo | URL, options?: RequestInit) =>
    nativeFetch(typeof input === 'string' ? new URL(input, window.location.origin) : input, options),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
afterAll(() => server.close());
