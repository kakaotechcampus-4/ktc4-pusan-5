import { useEffect, useState } from 'react';
import { getMarketOverview } from '@/lib/api';
import type { MarketOverview } from '@/lib/types';

/** 숨겨진 탭은 폴링하지 않고, 복귀 시 갱신한다. 실패 시 마지막 응답을 유지한다. */
export function useMarketOverview() {
  const [data, setData] = useState<MarketOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    let inFlight = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    async function refresh() {
      if (disposed || inFlight) return;
      clearTimeout(timer);
      if (document.hidden) return;
      inFlight = true;
      controller = new AbortController();
      const requestController = controller;
      const timeout = setTimeout(() => requestController.abort(), 12_000);
      try {
        const response = await getMarketOverview(requestController.signal);
        if (disposed) return;
        setData(response);
        setFailed(false);
        failures = 0;
      } catch {
        if (disposed) return;
        setFailed(true);
        failures += 1;
      } finally {
        clearTimeout(timeout);
        inFlight = false;
        if (!disposed) timer = setTimeout(refresh, Math.min(60_000 * 2 ** failures, 300_000));
      }
    }

    function handleVisibility() {
      if (document.hidden) clearTimeout(timer);
      else void refresh();
    }

    void refresh();
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [attempt]);

  return { data, failed, loading: !data && !failed, retry: () => setAttempt((n) => n + 1) };
}
