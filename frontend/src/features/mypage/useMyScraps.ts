import { useEffect, useState } from 'react';
import { mockScraps } from './mock';

export type MyListStatus = 'loading' | 'error' | 'empty' | 'success';
type LoadState = 'loading' | 'error' | 'success';

/**
 * 판단: 실제 fetch 가 없어서 타이머로 상태 전이를 흉내낸다. (홈 useMockLoad 와 같은 방식)
 * enabled 가 처음 true 가 될 때 로딩을 시작하고, 한 번 시작하면 다시 false 가 돼도 결과를 유지한다.
 * 실제 연동 시 이 훅 안쪽만 lib/api.ts 호출로 바꾸면 된다.
 */
export function useMockLoad(
  enabled: boolean,
  delayMs: number,
  result: LoadState,
): [LoadState, () => void] {
  const [state, setState] = useState<LoadState>('loading');
  const [attempt, setAttempt] = useState(0);
  const [started, setStarted] = useState(enabled);

  if (enabled && !started) setStarted(true);

  useEffect(() => {
    if (!started) return;
    const timer = setTimeout(() => setState(result), delayMs);
    return () => clearTimeout(timer);
  }, [started, delayMs, result, attempt]);

  function retry() {
    setState('loading');
    setAttempt((n) => n + 1);
  }

  return [state, retry];
}

/** 토글 가능한 id 집합. 해제 상태(removed)를 항목별로 들고 있다. */
export function useRemovedIds(): [Set<string>, (id: string) => void] {
  const [removedIds, setRemovedIds] = useState<Set<string>>(() => new Set());

  function toggleRemoved(id: string) {
    setRemovedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return [removedIds, toggleRemoved];
}

/**
 * 스크랩 목록. MyPage 최상위에서 호출해 탭을 오가도 상태가 유지된다.
 * 에러 화면은 아래 MOCK_RESULT 를 'error' 로 바꿔서 확인한다.
 * 빈 상태는 import 한 mockScraps 를 mockEmptyScraps 로 바꿔서 확인한다.
 */
const MOCK_RESULT: LoadState = 'success';

export function useMyScraps(enabled: boolean) {
  const [loadState, retry] = useMockLoad(enabled, 800, MOCK_RESULT);
  const [removedIds, toggleRemoved] = useRemovedIds();

  const items = mockScraps.items;
  const status: MyListStatus = loadState === 'success' && items.length === 0 ? 'empty' : loadState;

  return { status, items, removedIds, toggleRemoved, retry };
}
