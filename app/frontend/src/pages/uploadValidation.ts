import type { Meta } from '../api/types';

export function validateFiles(files: File[], limits: Meta['limits']): string | null {
  if (!files.length) return 'Выберите архив ZIP или три файла Parquet.';
  const names = files.map((f) => f.name);
  const zip = files.length === 1 && /\.zip$/i.test(files[0].name);
  const parquet =
    files.length === 3 &&
    ['edges.parquet', 'nodes.parquet', 'transactions.parquet'].every((name) => names.includes(name));
  if (!zip && !parquet)
    return 'Нужен один ZIP либо ровно edges.parquet, nodes.parquet и transactions.parquet.';
  if (files.some((f) => f.size === 0)) return 'Пустые файлы не принимаются.';
  if (files.reduce((sum, file) => sum + file.size, 0) > limits.max_upload_mb * 1024 * 1024)
    return `Общий размер превышает ${limits.max_upload_mb} МБ.`;
  return null;
}
