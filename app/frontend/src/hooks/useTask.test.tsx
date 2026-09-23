import { act, renderHook } from '@testing-library/react';
import { expect, it } from 'vitest';
import { useTask } from './useTask';

it('keeps the newest result when an older response arrives late', async () => {
  const { result } = renderHook(() => useTask<string>());
  let completeOld: (value: string) => void = () => {
    throw new Error('Deferred request was not started');
  };
  let oldSignal: AbortSignal | undefined;
  act(() => {
    void result.current.execute((signal) => {
      oldSignal = signal;
      return new Promise<string>((resolve) => {
        completeOld = resolve;
      });
    });
  });
  await act(async () => {
    await result.current.execute(async () => 'new run');
  });
  await act(async () => {
    completeOld('old run');
  });
  expect(oldSignal?.aborted).toBe(true);
  expect(result.current.data).toBe('new run');
});
it('aborts pending work when the workspace unmounts', () => {
  const { result, unmount } = renderHook(() => useTask<string>());
  let signal: AbortSignal | undefined;
  act(() => {
    void result.current.execute((value) => {
      signal = value;
      return new Promise(() => undefined);
    });
  });
  unmount();
  expect(signal?.aborted).toBe(true);
});
