import { useEffect, useRef, useState } from 'react';
import { useWatchlist } from '@/features/home/useWatchlist';
import { addToWatchlist, removeFromWatchlist } from '@/lib/api';
import type { MyListStatus } from './useMyScraps';

/**
 * 관심 종목. 홈과 같은 GET /api/watchlist 를 쓴다.
 * 별을 누르면 서버에서 바로 해제하고, 목록에는 흐리게 남겨 둔다(다시 담기 가능).
 * 탭을 떠나면 해제 표시를 버리고, 다시 열 때 서버 목록을 새로 불러온다.
 */
export function useMyWatchlist(enabled: boolean) {
  const { status: fetchStatus, items, retry } = useWatchlist(enabled);
  const [removedIds, setRemovedIds] = useState<Set<string>>(() => new Set());
  // 같은 종목의 요청이 끝나기 전에 또 누르는 것을 막는다.
  const inFlight = useRef(new Set<string>());

  useEffect(() => {
    if (!enabled) return;
    return () => setRemovedIds(new Set());
  }, [enabled]);

  async function toggleRemoved(code: string) {
    if (inFlight.current.has(code)) return;
    inFlight.current.add(code);
    const removing = !removedIds.has(code);
    try {
      await (removing ? removeFromWatchlist(code) : addToWatchlist(code));
      setRemovedIds((prev) => {
        const next = new Set(prev);
        if (removing) next.add(code);
        else next.delete(code);
        return next;
      });
    } catch {
      // 실패하면 상태를 바꾸지 않는다. 별 모양이 그대로라 사용자가 다시 시도할 수 있다.
    } finally {
      inFlight.current.delete(code);
    }
  }

  const status: MyListStatus =
    fetchStatus === 'success' && items.length === 0 ? 'empty' : fetchStatus;

  return { status, items, removedIds, toggleRemoved, retry };
}
