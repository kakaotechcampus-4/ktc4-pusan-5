import { useEffect, useState } from 'react';
import { useAuth } from '@/features/auth/useAuth';
import { addToWatchlist, getWatchlist, removeFromWatchlist } from '@/lib/api';

/**
 * 종목 상세에서 이 종목을 관심 종목에 담았는지 확인하고 담기/빼기를 한다.
 *
 * watched 가 null 이면 아직 모른다(인증 확인 중, 목록 조회 중·실패).
 * 비로그인이면 목록을 조회할 수 없으니 담지 않은 것으로 보고, 누르면 onLoginRequired 를 부른다.
 */
export function useWatchlistToggle(code: string | undefined, onLoginRequired: () => void) {
  const { status: authStatus } = useAuth();
  const [watched, setWatched] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!code || authStatus !== 'authenticated') return;

    const controller = new AbortController();
    getWatchlist(controller.signal)
      .then((response) => setWatched(response.items.some((item) => item.code === code)))
      .catch(() => {
        // 조회 실패 시 모르는 상태로 둔다. 잘못된 상태를 보여주는 것보다 누를 수 없게 막는다.
      });
    // 종목이 바뀌거나 로그아웃되면 이전 종목·이전 사용자의 상태를 버린다.
    return () => {
      controller.abort();
      setWatched(null);
    };
  }, [code, authStatus]);

  async function toggle() {
    if (!code) return;
    if (authStatus === 'unauthenticated') {
      onLoginRequired();
      return;
    }
    if (watched === null || pending) return;

    const next = !watched;
    setWatched(next);
    setPending(true);
    try {
      await (next ? addToWatchlist(code) : removeFromWatchlist(code));
    } catch {
      setWatched(!next);
    } finally {
      setPending(false);
    }
  }

  const ready =
    authStatus === 'unauthenticated' || (authStatus === 'authenticated' && watched !== null);
  return { watched: watched ?? false, ready, pending, toggle };
}
