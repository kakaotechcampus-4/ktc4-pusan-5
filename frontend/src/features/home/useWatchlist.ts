import { useEffect, useState } from 'react';
import { getWatchlist } from '@/lib/api';
import type { WatchlistEntry } from '@/lib/types';

export type WatchlistFetchStatus = 'loading' | 'error' | 'success';

/**
 * 관심 종목은 로그인한 사용자 것이라 enabled(로그인 여부)가 true일 때만 부른다.
 * 비로그인·인증 확인 중에는 요청하지 않고, 로그아웃되면 이전 사용자의 목록을 비운다.
 */
export function useWatchlist(enabled: boolean) {
  const [status, setStatus] = useState<WatchlistFetchStatus>('loading');
  const [items, setItems] = useState<WatchlistEntry[]>([]);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();
    getWatchlist(controller.signal)
      .then((response) => {
        setItems(response.items);
        setStatus('success');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setStatus('error');
      });
    // 로그아웃·재시도로 effect 가 정리될 때 이전 사용자의 목록을 비운다.
    return () => {
      controller.abort();
      setItems([]);
      setStatus('loading');
    };
  }, [enabled, attempt]);

  // 다시 시도: 로딩으로 되돌리고 attempt 를 올려 위 effect 를 다시 태운다.
  function retry() {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }

  return { status, items, retry };
}
