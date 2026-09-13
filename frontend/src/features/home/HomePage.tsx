import { useEffect, useState } from 'react';
import { SplitLayout } from '@/components/layout/PageShell';
import { mockIndexBoard, mockSignalBoard, mockWatchlist } from './mock';
import { HomeHero } from './components/HomeHero';
import { IndexSection } from './components/IndexTiles';
import { SignalSection, type SignalStatus } from './components/SignalList';
import { WatchlistCard, type WatchlistStatus } from './components/WatchlistCard';

type LoadState = 'loading' | 'error' | 'success';

/**
 * 판단: 실제 fetch 가 없어서 타이머로 상태 전이를 흉내낸다.
 * 홈은 섹션이 셋이고 셋 다 흐름이 같아서 훅 하나로 묶었다.
 * 실제 연동 시 이 훅 안쪽만 lib/api.ts 호출로 바꾸면 아래 렌더 분기는 그대로 쓸 수 있다.
 *
 * result 는 이 섹션이 끝에 도달할 상태다. 호출하는 쪽에서 섹션마다 따로 정한다.
 * 훅 안에 'success' 를 박아두면 한 줄만 고쳐도 세 섹션이 같이 바뀌어 버려서,
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
 * 홈 화면. 화면 조립과 상태 분기만 하고, 그리는 일은 components/ 가 맡는다.
 *
 * 섹션마다 상태를 따로 두는 이유: 지수·시그널·관심 종목은 각각 다른 API가 된다.
 * 하나가 실패해도 나머지는 보여야 하므로 페이지 전체를 에러로 덮지 않는다.
 */
export function HomePage() {
  // 섹션마다 결과를 따로 정한다. 두 번째 인자를 'error' 로 바꾸면 그 섹션만 에러가 뜬다.
  // 'loading' 으로 두면 그 섹션만 계속 로딩이라 스켈레톤을 오래 볼 수 있다.
  // 관심 종목 빈 상태는 아래 mockWatchlist 를 mockEmptyWatchlist 로 바꿔서 확인한다.
  // 시그널 빈 상태는 아래 mockSignalBoard 를 mockEmptySignalBoard 로 바꿔서 확인한다.
  const [indexState, retryIndex] = useMockLoad(400, 'success');
  const [signalState, retrySignal] = useMockLoad(900, 'success');
  const [watchState, retryWatch] = useMockLoad(700, 'success');

  const watchlistStatus: WatchlistStatus =
    watchState === 'success' && mockWatchlist.items.length === 0 ? 'empty' : watchState;

  const signalStatus: SignalStatus =
    signalState === 'success' && mockSignalBoard.signals.length === 0 ? 'empty' : signalState;

  return (
    <>
      <HomeHero
        asOf={indexState === 'success' ? mockIndexBoard.asOf : undefined}
        loading={indexState === 'loading'}
      />

      <IndexSection status={indexState} indices={mockIndexBoard.indices} onRetry={retryIndex} />

      <SplitLayout
        main={<SignalSection status={signalStatus} board={mockSignalBoard} onRetry={retrySignal} />}
        side={
          <WatchlistCard status={watchlistStatus} watchlist={mockWatchlist} onRetry={retryWatch} />
        }
      />
    </>
  );
}
