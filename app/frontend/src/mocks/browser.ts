import { setupWorker } from 'msw/browser';
import { createHandlers } from './handlers';

export function createMockWorker() {
  return setupWorker(...createHandlers());
}
