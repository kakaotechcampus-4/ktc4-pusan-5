import { useEffect, useState } from 'react';
import { mockSignalBoard, mockWatchlist } from './mock';
import type { SignalStatus } from './components/SignalList';
import type { WatchlistStatus } from './components/WatchlistCard';

type LoadState = 'loading' | 'error' | 'success';

/**
 * 판단: 실제 fetch 가 없어서 타이머로 상태 전이를 흉내낸다.
 * 홈은 섹션이 여섯이고 다 흐름이 같아서 훅 하나로 묶었다.
 * 실제 연동 시 이 훅 안쪽만 lib/api.ts 호출로 바꾸면 HomePage의 렌더 분기는 그대로 쓸 수 있다.
 *
 * result 는 이 섹션이 끝에 도달할 상태다. 호출하는 쪽에서 섹션마다 따로 정한다.
 * 훅 안에 'success' 를 박아두면 한 줄만 고쳐도 여러 섹션이 같이 바뀌어 버려서,
 * "지수만 에러" 같은 상황을 확인할 수 없다. 실제 API 도 섹션마다 성패가 따로 난다.
 */
function useMockLoad(delayMs: number, result: LoadState = 'success'): [LoadState, () => void] {
  const [state, setState] = useState<LoadState>('loading');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setState(result), delayMs);
    return () => clearTimeout(timer);
  }, [delayMs, result, attempt]);

  // 다시 시도: 로딩으로 되돌리고 attempt 를 올려 위 effect 를 다시 태운다.
  // attempt 를 올리지 않으면 effect 가 재실행되지 않아 로딩에서 멈춘다.
  function retry() {
    setState('loading');
    setAttempt((n) => n + 1);
  }

  return [state, retry];
}

/**
 * 홈의 섹션별 로딩 상태를 한 곳에서 관리한다.
 * HomePage는 여기서 돌려주는 status/retry만 받아 조립하면 되고,
 * "섹션마다 상태를 따로 두는" 정책이 바뀌어도 이 파일만 고치면 된다.
 *
 * 관심 종목 빈 상태는 mock.ts의 mockWatchlist를 mockEmptyWatchlist로 바꿔서 확인한다.
 * 시그널 빈 상태는 mockSignalBoard를 mockEmptySignalBoard로 바꿔서 확인한다.
 */
export function useHomeSections() {
  const [signalState, retrySignal] = useMockLoad(900, 'success');
  const [watchState, retryWatch] = useMockLoad(700, 'success');
  const [insightState, retryInsight] = useMockLoad(1100, 'success');

  const watchlistStatus: WatchlistStatus =
    watchState === 'success' && mockWatchlist.items.length === 0 ? 'empty' : watchState;

  const signalStatus: SignalStatus =
    signalState === 'success' && mockSignalBoard.signals.length === 0 ? 'empty' : signalState;

  return {
    signal: { status: signalStatus, retry: retrySignal },
    watchlist: { status: watchlistStatus, retry: retryWatch },
    insight: { status: insightState, retry: retryInsight },
  };
}
