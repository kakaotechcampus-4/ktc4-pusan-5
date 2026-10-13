import { act, renderHook, waitFor } from '@testing-library/react';
import { addToWatchlist, getWatchlist } from '@/lib/api';
import { useWatchlistToggle } from './useWatchlistToggle';

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ status: 'authenticated' }),
}));
vi.mock('@/lib/api', () => ({
  getWatchlist: vi.fn(),
  addToWatchlist: vi.fn(),
  removeFromWatchlist: vi.fn(),
}));

const watchlistRequest = vi.mocked(getWatchlist);
const addRequest = vi.mocked(addToWatchlist);

function watchlistOf(...codes: string[]) {
  return { items: codes.map((code) => ({ code })) } as Awaited<ReturnType<typeof getWatchlist>>;
}

describe('useWatchlistToggle', () => {
  it('이전 종목의 담기 요청이 늦게 실패해도 현재 종목의 상태를 덮지 않는다', async () => {
    // B 는 이미 관심 종목이다.
    watchlistRequest.mockResolvedValue(watchlistOf('B'));
    let failAdd!: () => void;
    addRequest.mockReturnValue(
      new Promise<void>((_, reject) => {
        failAdd = () => reject(new Error('network'));
      }),
    );

    const { result, rerender } = renderHook(({ code }) => useWatchlistToggle(code, vi.fn()), {
      initialProps: { code: 'A' },
    });
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.watched).toBe(false);

    // A 를 담는 요청을 보내 둔 채(낙관적으로 watched=true) B 로 이동한다.
    act(() => {
      void result.current.toggle();
    });
    expect(result.current.watched).toBe(true);
    rerender({ code: 'B' });
    await waitFor(() => expect(result.current.watched).toBe(true)); // B 는 담겨 있음
    await waitFor(() => expect(result.current.ready).toBe(true));

    // 그제서야 A 요청이 실패한다.
    await act(async () => {
      failAdd();
    });

    // A 의 롤백(false)이 B 에 적용되면 안 된다.
    expect(result.current.watched).toBe(true);
    expect(result.current.pending).toBe(false);
  });
});
