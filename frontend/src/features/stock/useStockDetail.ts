import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, getStockOverview, getStockPrices } from '@/lib/api';
import type { PricePeriod, Resource, StockOverview, StockPriceResource } from '@/lib/types';

type LoadError = ApiError | Error;
type KeyedState<T> = { key: string; data: T | null; error: LoadError | null };
type OverviewData = StockOverview;
const TIMEOUT_MS = 12_000;

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function requestWithTimeout<T>(request: (signal: AbortSignal) => Promise<T>): {
  promise: Promise<T>;
  abort: () => void;
} {
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

function retryDelay(resource: Resource<unknown>, fastAttempts: number): number {
  const backoff = fastAttempts <= 3 ? 3 : Math.min(60, 15 * 2 ** Math.min(fastAttempts - 4, 2));
  return Math.max(backoff, resource.retryAfterSeconds ?? 0);
}

function shouldPoll(resource: Resource<unknown>): boolean {
  return (
    resource.status === 'pending' || resource.refreshing || resource.retryAfterSeconds !== null
  );
}

export function useStockDetail(code: string | undefined, period: PricePeriod) {
  const overviewKey = code ?? '';
  const priceKey = code ? `${code}:${period}` : '';
  const [overviewState, setOverviewState] = useState<KeyedState<OverviewData>>({
    key: '',
    data: null,
    error: null,
  });
  const [priceState, setPriceState] = useState<KeyedState<StockPriceResource>>({
    key: '',
    data: null,
    error: null,
  });
  const [overviewRetry, setOverviewRetry] = useState(0);
  const [priceRetry, setPriceRetry] = useState(0);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    let hidden = document.visibilityState === 'hidden';
    let timer: ReturnType<typeof setTimeout> | undefined;
    let activeRequest: (() => void) | undefined;
    let fastAttempts = 0;
    let generation = 0;

    const schedule = (delay: number) => {
      if (cancelled || hidden) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(load, delay * 1000);
    };
    const load = () => {
      if (cancelled || hidden || activeRequest) return;
      const requestId = ++generation;
      const request = requestWithTimeout((signal) => getStockOverview(code, signal));
      activeRequest = request.abort;
      request.promise
        .then((data) => {
          if (cancelled || requestId !== generation) return;
          activeRequest = undefined;
          setOverviewState({ key: overviewKey, data, error: null });
          if (shouldPoll(data.quote) || shouldPoll(data.metrics)) {
            fastAttempts += 1;
            schedule(
              Math.max(
                retryDelay(data.quote, fastAttempts),
                retryDelay(data.metrics, fastAttempts),
              ),
            );
          } else schedule(60);
        })
        .catch((error: unknown) => {
          if (cancelled || requestId !== generation || isAbort(error)) return;
          activeRequest = undefined;
          setOverviewState((previous) => ({
            key: overviewKey,
            data: previous.key === overviewKey ? previous.data : null,
            error: error instanceof Error ? error : new Error('overview failed'),
          }));
          if (!(error instanceof ApiError && [404, 422].includes(error.status)))
            schedule(error instanceof ApiError && error.status === 503 ? 15 : 60);
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
      if (timer) clearTimeout(timer);
      activeRequest?.();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [code, overviewKey, overviewRetry]);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    let hidden = document.visibilityState === 'hidden';
    let timer: ReturnType<typeof setTimeout> | undefined;
    let activeRequest: (() => void) | undefined;
    let fastAttempts = 0;
    let generation = 0;
    const schedule = (delay: number) => {
      if (cancelled || hidden) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(load, delay * 1000);
    };
    const load = () => {
      if (cancelled || hidden || activeRequest) return;
      const requestId = ++generation;
      const request = requestWithTimeout((signal) => getStockPrices(code, period, signal));
      activeRequest = request.abort;
      request.promise
        .then((data) => {
          if (cancelled || requestId !== generation) return;
          activeRequest = undefined;
          setPriceState({ key: priceKey, data, error: null });
          if (shouldPoll(data)) {
            fastAttempts += 1;
            schedule(retryDelay(data, fastAttempts));
          }
        })
        .catch((error: unknown) => {
          if (cancelled || requestId !== generation || isAbort(error)) return;
          activeRequest = undefined;
          setPriceState((previous) => ({
            key: priceKey,
            data: previous.key === priceKey ? previous.data : null,
            error: error instanceof Error ? error : new Error('prices failed'),
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
      if (timer) clearTimeout(timer);
      activeRequest?.();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [code, period, priceKey, priceRetry]);

  const retryOverview = useCallback(() => setOverviewRetry((value) => value + 1), []);
  const retryPrices = useCallback(() => setPriceRetry((value) => value + 1), []);
  const overview = overviewState.key === overviewKey ? overviewState.data : null;
  const prices = priceState.key === priceKey ? priceState.data : null;
  return useMemo(
    () => ({
      overview: overview ?? { stock: null, quote: null, metrics: null },
      overviewError: overviewState.key === overviewKey ? overviewState.error : null,
      prices,
      priceError: priceState.key === priceKey ? priceState.error : null,
      retryOverview,
      retryPrices,
    }),
    [
      overview,
      overviewKey,
      overviewState.error,
      overviewState.key,
      priceKey,
      priceState.error,
      priceState.key,
      prices,
      retryOverview,
      retryPrices,
    ],
  );
}
