import { useAuth } from '@/features/auth/useAuth';
import type { AuthStatus } from '@/features/auth/useAuth';
import { useSignalBoard } from './useSignalBoard';
import { useWatchlist } from './useWatchlist';
import type { WatchlistFetchStatus } from './useWatchlist';
import type { WatchlistStatus } from './components/WatchlistCard';

/** 관심 종목은 로그인한 사용자 것이라 인증 상태가 먼저 정해진다. */
function resolveWatchlistStatus(
  authStatus: AuthStatus,
  fetchStatus: WatchlistFetchStatus,
  itemCount: number,
): WatchlistStatus {
  if (authStatus === 'loading') return 'loading';
  if (authStatus === 'unauthenticated') return 'unauthenticated';
  if (authStatus === 'error') return 'error';
  if (fetchStatus === 'success' && itemCount === 0) return 'empty';
  return fetchStatus;
}

/**
 * 홈의 섹션별 로딩 상태를 한 곳에서 관리한다.
 * HomePage는 여기서 돌려주는 status/retry만 받아 조립하면 되고,
 * "섹션마다 상태를 따로 두는" 정책이 바뀌어도 이 파일만 고치면 된다.
 *
 * 시그널(useSignalBoard)과 관심 종목(useWatchlist) 모두 실제 API 를 쓴다.
 */
export function useHomeSections() {
  const signal = useSignalBoard();

  const { status: authStatus } = useAuth();
  const watchlist = useWatchlist(authStatus === 'authenticated');
  const watchlistStatus = resolveWatchlistStatus(
    authStatus,
    watchlist.status,
    watchlist.items.length,
  );

  return {
    signal,
    watchlist: { status: watchlistStatus, items: watchlist.items, retry: watchlist.retry },
  };
}
