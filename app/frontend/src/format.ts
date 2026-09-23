import type { MetricUnit } from './api/types';

export const number = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
export const score = (value: number) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const money = (value: number) => `${number(value)} ₸`;
export const share = (value: number) => `${number(value * 100)} %`;
export const date = (value: string | null) =>
  value
    ? new Date(value.length === 10 ? `${value}T00:00:00Z` : value).toLocaleDateString('ru-RU', {
        timeZone: 'UTC',
      })
    : '—';
export function metric(value: number | string | null, unit: MetricUnit) {
  if (value == null) return 'Нет данных';
  if (typeof value === 'string') return value;
  return unit === 'kzt'
    ? money(value)
    : unit === 'share'
      ? share(value)
      : unit === 'days'
        ? `${number(value)} дн.`
        : unit === 'ratio'
          ? `${number(value)}×`
          : number(value);
}
export const CAUTION = 'Роли — гипотезы для проверки, не утверждение о виновности';
