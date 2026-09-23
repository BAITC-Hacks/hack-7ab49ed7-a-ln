import { API_BASE } from './base';
import { networkError, parseError, protocolError } from './errors';
import type { HttpDependencies } from './http';

interface UploadCallbacks<T> {
  resolve: (value: T) => void;
  reject: (reason: Error) => void;
  cleanup: () => void;
  unauthorized: () => void;
}
function finishUpload<T>(xhr: XMLHttpRequest, callbacks: UploadCallbacks<T>) {
  callbacks.cleanup();
  const requestId = xhr.getResponseHeader('X-Request-ID');
  if (xhr.status >= 200 && xhr.status < 300) {
    if (xhr.response) callbacks.resolve(xhr.response as T);
    else callbacks.reject(protocolError(xhr.status, requestId));
    return;
  }
  if (xhr.status === 401) callbacks.unauthorized();
  callbacks.reject(parseError(xhr.response, xhr.status, requestId));
}
function configureUpload<T>(
  xhr: XMLHttpRequest,
  callbacks: UploadCallbacks<T>,
  progress: (value: number) => void,
) {
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) progress(event.loaded / event.total);
  };
  xhr.onerror = () => {
    callbacks.cleanup();
    callbacks.reject(networkError());
  };
  xhr.onabort = () => {
    callbacks.cleanup();
    callbacks.reject(new DOMException('Загрузка отменена', 'AbortError'));
  };
  xhr.onload = () => finishUpload(xhr, callbacks);
}
export function uploadForm<T>(
  deps: HttpDependencies,
  path: string,
  form: FormData,
  progress: (value: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Загрузка отменена', 'AbortError'));
      return;
    }
    const xhr = deps.createXHR();
    const abort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener('abort', abort);
    xhr.open('POST', `${API_BASE}${path}`);
    xhr.withCredentials = true;
    xhr.responseType = 'json';
    configureUpload(xhr, { resolve, reject, cleanup, unauthorized: deps.onUnauthorized }, progress);
    signal?.addEventListener('abort', abort, { once: true });
    xhr.send(form);
  });
}
