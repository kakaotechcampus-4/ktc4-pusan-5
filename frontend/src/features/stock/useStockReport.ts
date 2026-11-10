import { useCallback, useEffect, useMemo, useState } from 'react';
import { getStockReport } from '@/lib/api';
import type { Resource, StockReport } from '@/lib/types';

type KeyedState = { key: string; resource: Resource<StockReport> | null; error: Error | null };

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

/**
 * 보고서는 서버가 미리 만들어 둔 것을 읽기만 하므로 폴링하지 않는다.
 * pending(아직 생성 전)은 화면이 빈 상태로 보여주고, 사용자가 다시 확인한다.
 */
export function useStockReport(code: string | undefined) {
  const key = code ?? '';
  const [state, setState] = useState<KeyedState>({ key: '', resource: null, error: null });
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    if (!code) return;
    const controller = new AbortController();
    getStockReport(code, controller.signal)
      .then((resource) => setState({ key, resource, error: null }))
      .catch((error: unknown) => {
        if (isAbort(error)) return;
        setState({
          key,
          resource: null,
          error: error instanceof Error ? error : new Error('report failed'),
        });
      });
    return () => controller.abort();
  }, [code, key, retryCount]);

  const retry = useCallback(() => {
    setState({ key: '', resource: null, error: null });
    setRetryCount((value) => value + 1);
  }, []);

  const current = state.key === key ? state : null;
  return useMemo(
    () => ({ resource: current?.resource ?? null, error: current?.error ?? null, retry }),
    [current, retry],
  );
}
