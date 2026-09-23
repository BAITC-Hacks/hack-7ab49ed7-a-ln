import { expect, it } from 'vitest';
import { validateFiles } from './uploadValidation';

const limits = { max_upload_mb: 1, max_zip_members: 3, max_nodes: 100, max_transactions: 1000 };
it('accepts a ZIP or exactly the three named Parquet files', () => {
  expect(validateFiles([new File(['x'], 'input.zip')], limits)).toBeNull();
  expect(
    validateFiles(
      ['edges', 'nodes', 'transactions'].map((n) => new File(['x'], `${n}.parquet`)),
      limits,
    ),
  ).toBeNull();
  expect(validateFiles([new File(['x'], 'edges.parquet')], limits)).toContain('ровно');
});
it('rejects empty, duplicated and oversized input', () => {
  expect(validateFiles([new File([], 'input.zip')], limits)).toContain('Пустые');
  expect(
    validateFiles(
      ['edges', 'edges', 'nodes'].map((n) => new File(['x'], `${n}.parquet`)),
      limits,
    ),
  ).toContain('ровно');
  expect(validateFiles([new File([new Uint8Array(1024 * 1024 + 1)], 'input.zip')], limits)).toContain(
    'превышает',
  );
});
