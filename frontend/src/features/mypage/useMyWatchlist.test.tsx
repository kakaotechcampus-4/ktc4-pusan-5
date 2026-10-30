import { act, renderHook, waitFor } from '@testing-library/react';
import { addToWatchlist, getWatchlist, removeFromWatchlist } from '@/lib/api';
import type { WatchlistEntry } from '@/lib/types';
import { useMyWatchlist } from './useMyWatchlist';

vi.mock('@/lib/api', () => ({
  getWatchlist: vi.fn(),
  addToWatchlist: vi.fn(),
  removeFromWatchlist: vi.fn(),
}));

const watchlistRequest = vi.mocked(getWatchlist);
const addRequest = vi.mocked(addToWatchlist);
const removeRequest = vi.mocked(removeFromWatchlist);

function entry(code: string): WatchlistEntry {
  return {
    code,
    name: `Stock ${code}`,
    market: 'KOSPI',
    quote: { price: 100, change: 1, changeAmount: 1 },
    quoteStatus: 'ready',
    asOf: '2026-10-09T15:30:00+09:00',
  };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe('useMyWatchlist', () => {
  it('서버의 관심 종목을 불러온다', async () => {
    watchlistRequest.mockResolvedValue({ items: [entry('005930')] });

    const { result } = renderHook(() => useMyWatchlist(true));

    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.items.map((item) => item.code)).toEqual(['005930']);
  });

  it('목록이 비어 있으면 empty 다', async () => {
    watchlistRequest.mockResolvedValue({ items: [] });

    const { result } = renderHook(() => useMyWatchlist(true));

    await waitFor(() => expect(result.current.status).toBe('empty'));
  });

  it('불러오기에 실패하면 error 다', async () => {
    watchlistRequest.mockRejectedValue(new Error('network'));

    const { result } = renderHook(() => useMyWatchlist(true));

    await waitFor(() => expect(result.current.status).toBe('error'));
  });

  it('별을 누르면 서버에서 해제하고, 다시 누르면 다시 담는다', async () => {
    watchlistRequest.mockResolvedValue({ items: [entry('005930')] });
    removeRequest.mockResolvedValue();
    addRequest.mockResolvedValue();
    const { result } = renderHook(() => useMyWatchlist(true));
    await waitFor(() => expect(result.current.status).toBe('success'));

    await act(() => result.current.toggleRemoved('005930'));
    expect(removeRequest).toHaveBeenCalledWith('005930');
    expect(result.current.removedIds.has('005930')).toBe(true);

    await act(() => result.current.toggleRemoved('005930'));
    expect(addRequest).toHaveBeenCalledWith('005930');
    expect(result.current.removedIds.has('005930')).toBe(false);
  });

  it('해제 요청이 실패하면 해제 표시를 하지 않는다', async () => {
    watchlistRequest.mockResolvedValue({ items: [entry('005930')] });
    removeRequest.mockRejectedValue(new Error('network'));
    const { result } = renderHook(() => useMyWatchlist(true));
    await waitFor(() => expect(result.current.status).toBe('success'));

    await act(() => result.current.toggleRemoved('005930'));

    expect(result.current.removedIds.has('005930')).toBe(false);
  });
});
