import { useCallback, useEffect, useRef, useState } from 'react';

export function useTask<T>(scope?: string) {
  const active = useRef<AbortController | null>(null);
  const [state, setState] = useState<{ pending: boolean; data?: T; error?: Error; scope?: string }>({
    pending: false,
    scope,
  });
  useEffect(() => () => active.current?.abort(), [scope]);
  const execute = useCallback(
    async (work: (signal: AbortSignal) => Promise<T>) => {
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      setState({ pending: true, scope });
      try {
        const data = await work(controller.signal);
        if (!controller.signal.aborted) {
          setState({ pending: false, data, scope });
          return data;
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setState({
            pending: false,
            scope,
            error: error instanceof Error ? error : new Error('Не удалось выполнить действие.'),
          });
      }
    },
    [scope],
  );
  const reset = useCallback(() => {
    active.current?.abort();
    setState({ pending: false, scope });
  }, [scope]);
  return {
    ...(state.scope === scope ? state : { pending: false, data: undefined, error: undefined }),
    execute,
    reset,
  };
}
