import { mockMyWatchlist } from './mock';
import { useMockLoad, useRemovedIds, type MyListStatus } from './useMyScraps';

/**
 * 관심 종목. 스크랩 훅과 같은 패턴이다.
 * 에러 화면은 아래 MOCK_RESULT 를 'error' 로 바꿔서 확인한다.
 * 빈 상태는 import 한 mockMyWatchlist 를 mockEmptyMyWatchlist 로 바꿔서 확인한다.
 */
const MOCK_RESULT: 'loading' | 'error' | 'success' = 'success';

export function useMyWatchlist(enabled: boolean) {
  const [loadState, retry] = useMockLoad(enabled, 700, MOCK_RESULT);
  const [removedIds, toggleRemoved] = useRemovedIds();

  const watchlist = mockMyWatchlist;
  const status: MyListStatus =
    loadState === 'success' && watchlist.items.length === 0 ? 'empty' : loadState;

  return { status, watchlist, removedIds, toggleRemoved, retry };
}
