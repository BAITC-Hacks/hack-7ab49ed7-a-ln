import { describe, expect, it, vi } from 'vitest';
import { createApi } from './client';
import { createHttpClient } from './http';
import type { HttpClient } from './http';
import { API_BASE } from './base';
import { ApiError } from './errors';

function dependencies(fetcher: typeof fetch) {
  return { fetch: fetcher, createXHR: () => new XMLHttpRequest(), onUnauthorized: vi.fn() };
}
describe('HTTP boundary', () => {
  it('uses a single versioned base, cookies and repeated filters without rounding IDs', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ items: [], total: 0 }));
    const api = createApi(createHttpClient(dependencies(fetcher)));
    await api.nodes(
      'run-a',
      { role: ['transit', 'terminal'], q: '999999999999999999' },
      'in_kzt',
      'desc',
      25,
    );
    const [url, options] = fetcher.mock.calls[0];
    expect(String(url)).toContain(`${API_BASE}/runs/run-a/nodes?`);
    expect(String(url)).toContain('role=transit&role=terminal');
    expect(String(url)).toContain('999999999999999999');
    expect(options?.credentials).toBe('include');
  });
  it('normalizes errors and notifies session expiry', async () => {
    const deps = dependencies(
      vi.fn<typeof fetch>().mockResolvedValue(
        Response.json(
          {
            error: {
              code: 'unauthorized',
              message: 'Требуется вход',
              request_id: 'request-42',
              retryable: false,
            },
          },
          { status: 401 },
        ),
      ),
    );
    const client = createHttpClient(deps);
    await expect(client.request('/runs')).rejects.toMatchObject({
      status: 401,
      requestId: 'request-42',
      message: 'Требуется вход',
    });
    expect(deps.onUnauthorized).toHaveBeenCalledOnce();
  });
  it('normalizes non-JSON proxy failures without losing the request ID', async () => {
    const client = createHttpClient(
      dependencies(
        vi
          .fn<typeof fetch>()
          .mockResolvedValue(
            new Response('<h1>Too large</h1>', { status: 413, headers: { 'X-Request-ID': 'proxy-42' } }),
          ),
      ),
    );
    await expect(client.request('/runs')).rejects.toMatchObject({ status: 413, requestId: 'proxy-42' });
  });
  it('rejects malformed successful responses', async () => {
    const client = createHttpClient(
      dependencies(vi.fn<typeof fetch>().mockResolvedValue(new Response('invalid', { status: 200 }))),
    );
    await expect(client.request('/meta')).rejects.toBeInstanceOf(ApiError);
  });
  it('can replace HTTP with a fake transport', async () => {
    const http: HttpClient = {
      request: vi.fn().mockResolvedValue({ id: 'run-7' }),
      upload: vi.fn(),
      download: vi.fn(),
    };
    expect(await createApi(http).run('run-7')).toEqual({ id: 'run-7' });
    expect(http.request).toHaveBeenCalledWith('/runs/run-7', { signal: undefined });
  });
});
