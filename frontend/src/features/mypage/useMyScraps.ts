import { useEffect, useRef, useState } from 'react';
import { addScrap, getMyScraps, removeScrap } from '@/lib/api';
import type { MyScrap } from './types';

export type MyListStatus = 'loading' | 'error' | 'empty' | 'success';
type LoadState = 'loading' | 'error' | 'success';

/**
 * 스크랩한 보고서. MyPage 최상위에서 호출해 탭을 오가도 상태가 유지된다.
 * 북마크를 누르면 서버에서 바로 해제하고, 목록에는 흐리게 남겨 둔다(다시 스크랩 가능).
 * enabled 가 true 가 될 때 불러오고, 로그아웃되면 이전 사용자의 목록을 비운다.
 */
export function useMyScraps(enabled: boolean) {
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [items, setItems] = useState<MyScrap[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [removedIds, setRemovedIds] = useState<Set<string>>(() => new Set());
  // 같은 스크랩의 요청이 끝나기 전에 또 누르는 것을 막는다.
  const inFlight = useRef(new Set<string>());

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();
    getMyScraps(controller.signal)
      .then((response) => {
        setItems(response.items);
        setLoadState('success');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setLoadState('error');
      });
    return () => {
      controller.abort();
      setItems([]);
      setRemovedIds(new Set());
      setLoadState('loading');
    };
  }, [enabled, attempt]);

  function retry() {
    setLoadState('loading');
    setAttempt((n) => n + 1);
  }

  async function toggleRemoved(scrapId: string) {
    const scrap = items.find((item) => item.scrapId === scrapId);
    if (!scrap || inFlight.current.has(scrapId)) return;
    inFlight.current.add(scrapId);
    const removing = !removedIds.has(scrapId);
    try {
      await (removing ? removeScrap(scrap.reportId) : addScrap(scrap.reportId));
      setRemovedIds((prev) => {
        const next = new Set(prev);
        if (removing) next.add(scrapId);
        else next.delete(scrapId);
        return next;
      });
    } catch {
      // 실패하면 상태를 바꾸지 않는다. 북마크 모양이 그대로라 사용자가 다시 시도할 수 있다.
    } finally {
      inFlight.current.delete(scrapId);
    }
  }

  const status: MyListStatus = loadState === 'success' && items.length === 0 ? 'empty' : loadState;

  return { status, items, removedIds, toggleRemoved, retry };
}
