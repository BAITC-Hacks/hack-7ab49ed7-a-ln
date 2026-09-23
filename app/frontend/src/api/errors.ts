import type { ErrorBody, FieldIssue } from './types';

type ErrorInput = Pick<ErrorBody, 'code' | 'message'> & Partial<Omit<ErrorBody, 'code' | 'message'>>;
function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}
function text(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;
  readonly details: FieldIssue[];
  readonly retryable: boolean;
  constructor(body: ErrorInput, status = 0) {
    super(body.message);
    this.name = 'ApiError';
    this.code = body.code;
    this.status = status;
    this.requestId = body.request_id;
    this.details = body.details ?? [];
    this.retryable = body.retryable ?? false;
  }
}
export function parseError(body: unknown, status: number, requestId?: string | null): ApiError {
  const error = record(record(body).error) as Partial<ErrorBody>;
  return new ApiError(
    {
      code: text(error.code) ?? 'http_error',
      message: text(error.message) ?? `Не удалось выполнить запрос (${status}).`,
      request_id: text(error.request_id) ?? requestId ?? undefined,
      details: error.details,
      retryable: typeof error.retryable === 'boolean' ? error.retryable : status >= 500,
    },
    status,
  );
}
export function networkError() {
  return new ApiError({
    code: 'network_error',
    message: 'Нет связи с сервером. Проверьте подключение и повторите запрос.',
    retryable: true,
  });
}
export function protocolError(status: number, requestId?: string | null) {
  return new ApiError(
    {
      code: 'invalid_response',
      message: 'Сервер вернул ответ в неподдерживаемом формате.',
      retryable: false,
      request_id: requestId ?? undefined,
    },
    status,
  );
}
