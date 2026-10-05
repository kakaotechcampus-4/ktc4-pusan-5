import { act, renderHook } from '@testing-library/react';
import { searchAll } from '@/lib/api';
import type { SearchResponse } from '@/lib/types';
import { useSearch } from './useSearch';

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return { ...actual, searchAll: vi.fn() };
});

const searchRequest = vi.mocked(searchAll);

function response(query: string, names: string[]): SearchResponse {
  return {
    query,
    stocks: names.map((name, index) => ({
      code: `00000${index}`,
      name,
      market: 'KOSPI' as const,
    })),
    concepts: [],
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  searchRequest.mockReset();
});
afterEach(() => vi.useRealTimers());

it('stays idle and does not call the API for a blank query', () => {
  const { result } = renderHook(() => useSearch('   '));
  act(() => vi.advanceTimersByTime(1000));
  expect(result.current.status).toBe('idle');
  expect(searchRequest).not.toHaveBeenCalled();
});

it('waits for typing to pause, then returns the results', async () => {
  searchRequest.mockResolvedValue(response('삼성', ['삼성전자']));
  const { result } = renderHook(() => useSearch('삼성'));
  expect(result.current.status).toBe('loading');
  expect(searchRequest).not.toHaveBeenCalled();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(searchRequest).toHaveBeenCalledTimes(1);
  expect(searchRequest.mock.calls[0][0]).toBe('삼성');
  expect(result.current.status).toBe('success');
  expect(result.current.stocks.map((stock) => stock.name)).toEqual(['삼성전자']);
});

it('searches only the last input when the query changes quickly', async () => {
  searchRequest.mockResolvedValue(response('삼성전자', ['삼성전자']));
  const { rerender } = renderHook(({ query }) => useSearch(query), {
    initialProps: { query: '삼' },
  });
  rerender({ query: '삼성전자' });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(searchRequest).toHaveBeenCalledTimes(1);
  expect(searchRequest.mock.calls[0][0]).toBe('삼성전자');
});

it('does not show the previous results while the new query is loading', async () => {
  searchRequest.mockResolvedValue(response('삼성', ['삼성전자']));
  const { result, rerender } = renderHook(({ query }) => useSearch(query), {
    initialProps: { query: '삼성' },
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(result.current.stocks).toHaveLength(1);

  rerender({ query: '카카오' });
  expect(result.current.status).toBe('loading');
  expect(result.current.stocks).toEqual([]);
});

it('reports an error when the request fails', async () => {
  searchRequest.mockRejectedValue(new Error('network'));
  const { result } = renderHook(() => useSearch('삼성'));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
  expect(result.current.status).toBe('error');
  expect(result.current.stocks).toEqual([]);
});
