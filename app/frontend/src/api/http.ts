import { uploadForm } from './upload';
import { API_BASE } from './base';
import { networkError, parseError, protocolError } from './errors';

export interface HttpClient {
  request<T>(path: string, options?: RequestInit): Promise<T>;
  upload<T>(
    path: string,
    form: FormData,
    onProgress: (value: number) => void,
    signal?: AbortSignal,
  ): Promise<T>;
  download(path: string, signal?: AbortSignal): Promise<Blob>;
}
export interface HttpDependencies {
  fetch: typeof fetch;
  createXHR: () => XMLHttpRequest;
  onUnauthorized: () => void;
}
export function createHttpClient(deps: HttpDependencies): HttpClient {
  async function getResponse(path: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers);
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type'))
      headers.set('Content-Type', 'application/json');
    try {
      return await deps.fetch(`${API_BASE}${path}`, {
        ...options,
        credentials: 'include',
        headers,
      });
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      throw networkError();
    }
  }
  async function readJSON(response: Response): Promise<unknown> {
    try {
      return await response.json();
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      if (!response.ok) throw parseError(null, response.status, response.headers.get('X-Request-ID'));
      throw protocolError(response.status, response.headers.get('X-Request-ID'));
    }
  }
  async function checkError(response: Response, path: string) {
    if (!response.ok) {
      if (response.status === 401 && path !== '/session') deps.onUnauthorized();
      throw parseError(await readJSON(response), response.status, response.headers.get('X-Request-ID'));
    }
  }
  return {
    async request<T>(path: string, options: RequestInit = {}): Promise<T> {
      const response = await getResponse(path, options);
      await checkError(response, path);
      return response.status === 204 ? (undefined as T) : ((await readJSON(response)) as T);
    },
    async download(path, signal) {
      const response = await getResponse(path, { signal });
      await checkError(response, path);
      return response.blob();
    },
    upload: (path, form, progress, signal) => uploadForm(deps, path, form, progress, signal),
  };
}
