import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, getStockFinancials } from '@/lib/api';
import type { Resource, StockFinancials } from '@/lib/types';

type LoadError = ApiError | Error;
type KeyedState = { key: string; data: StockFinancials | null; error: LoadError | null };
const TIMEOUT_MS = 12_000;

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function requestWithTimeout(request: (signal: AbortSignal) => Promise<StockFinancials>) {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TIMEOUT_MS);
  const promise = request(controller.signal)
    .catch((error: unknown) => {
      if (timedOut) throw new Error('요청 시간이 초과되었습니다');
      throw error;
    })
    .finally(() => clearTimeout(timeout));
  return { promise, abort: () => controller.abort() };
}

function needsRefresh(resource: Resource<unknown>): boolean {
  return (
    resource.status === 'pending' || resource.refreshing || resource.retryAfterSeconds !== null
  );
}

function retryDelay(resource: Resource<unknown>, attempts: number): number {
  const backoff = attempts <= 3 ? 3 : Math.min(60, 15 * 2 ** Math.min(attempts - 4, 2));
  return Math.max(backoff, resource.retryAfterSeconds ?? 0);
}

export function useStockFinancials(code: string | undefined) {
  const key = code ?? '';
  const [state, setState] = useState<KeyedState>({ key: '', data: null, error: null });
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    let hidden = document.visibilityState === 'hidden';
    let timer: ReturnType<typeof setTimeout> | undefined;
    let activeRequest: (() => void) | undefined;
    let generation = 0;
    let attempts = 0;

    const schedule = (seconds: number) => {
      if (cancelled || hidden) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(load, seconds * 1000);
    };
    const load = () => {
      if (cancelled || hidden || activeRequest) return;
      const requestId = ++generation;
      const request = requestWithTimeout((signal) => getStockFinancials(code, signal));
      activeRequest = request.abort;
      request.promise
        .then((data) => {
          if (cancelled || requestId !== generation) return;
          activeRequest = undefined;
          setState({ key, data, error: null });
          const resources = [data.income, data.eps];
          const pending = resources.filter(needsRefresh);
          if (pending.length) {
            attempts += 1;
            schedule(Math.max(...pending.map((resource) => retryDelay(resource, attempts))));
          }
        })
        .catch((error: unknown) => {
          if (cancelled || requestId !== generation || isAbort(error)) return;
          activeRequest = undefined;
          setState((previous) => ({
            key,
            data: previous.key === key ? previous.data : null,
            error: error instanceof Error ? error : new Error('financials failed'),
          }));
          if (!(error instanceof ApiError && [404, 422].includes(error.status))) schedule(30);
        });
    };
    const onVisibilityChange = () => {
      hidden = document.visibilityState === 'hidden';
      if (hidden) {
        generation += 1;
        if (timer) clearTimeout(timer);
        activeRequest?.();
        activeRequest = undefined;
      } else load();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    load();
    return () => {
      cancelled = true;
      generation += 1;
      if (timer) clearTimeout(timer);
      activeRequest?.();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [code, key, retryCount]);

  const retry = useCallback(() => setRetryCount((value) => value + 1), []);
  const data = state.key === key ? state.data : null;
  return useMemo(
    () => ({ data, error: state.key === key ? state.error : null, retry }),
    [data, key, retry, state.error, state.key],
  );
}
