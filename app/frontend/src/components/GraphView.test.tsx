import { render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { createDemoData } from '../mocks/data';
import { GraphView } from './GraphView';
import type { GraphFactory } from '../graph/types';

it('falls back to an accessible paginated table when WebGL fails', async () => {
  const data = createDemoData();
  const factory: GraphFactory = () => {
    throw new Error('WebGL недоступен');
  };
  render(
    <GraphView
      data={data.graph}
      methodology={data.methodology}
      selected={null}
      onSelect={vi.fn()}
      factory={factory}
    />,
  );
  await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument());
  expect(screen.getByText('WebGL недоступен', { exact: false })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: `Открыть клиента ${data.nodes[0].id}` })).toBeInTheDocument();
  expect(screen.getAllByRole('row')).toHaveLength(26);
});
