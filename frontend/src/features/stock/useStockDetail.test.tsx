import { act, renderHook } from '@testing-library/react';
import type { PricePeriod, Resource, StockOverview, StockPriceResource } from '@/lib/types';
import { getStockOverview, getStockPrices } from '@/lib/api';
import { useStockDetail } from './useStockDetail';

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return { ...actual, getStockOverview: vi.fn(), getStockPrices: vi.fn() };
});

const overviewRequest = vi.mocked(getStockOverview);
const pricesRequest = vi.mocked(getStockPrices);

function resource<T>(
  status: Resource<T>['status'],
  data: T | null,
  options: Partial<Resource<T>> = {},
): Resource<T> {
  return {
    status,
    refreshing: false,
    data,
    sourceAsOf: null,
    collectedAt: null,
    retryAfterSeconds: null,
    ...options,
  };
}

function overview(
  code: string,
  quote = resource('ready', {
    price: 100,
    change: 1,
    changeAmount: 1,
    volume: 10,
    tradingValue: 1000,
    marketCap: 10000,
  }),
  metrics = resource('ready', {
    per: 1,
    pbr: 1,
    eps: 1,
    bps: 1,
    foreignOwnership: 1,
    week52High: 110,
    week52Low: 90,
  }),
): StockOverview {
  return {
    stock: {
      code,
      name: `Stock ${code}`,
      market: 'KOSPI',
      listingStatus: 'listed',
      listedAt: null,
    },
    quote,
    metrics,
  };
}

function prices(
  code: string,
  period: PricePeriod,
  status: Resource<StockPriceResource['data']>['status'] = 'ready',
): StockPriceResource {
  return {
    ...resource(status, [{ date: '2026-01-02', open: 1, high: 2, low: 1, close: 2, volume: 10 }]),
    code,
    period,
    adjustment: 'raw',
    coverage: { fromDate: '2026-01-02', toDate: '2026-01-02', complete: true },
  };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe('useStockDetail', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls a pending chart until it becomes ready', async () => {
    overviewRequest.mockResolvedValue(overview('A'));
    pricesRequest
      .mockResolvedValueOnce(prices('A', '1Y', 'pending'))
      .mockResolvedValueOnce(prices('A', '1Y'));
    const { result } = renderHook(() => useStockDetail('A', '1Y'));
    await settle();
    expect(result.current.prices?.status).toBe('pending');
    await act(async () => vi.advanceTimersByTimeAsync(3000));
    expect(pricesRequest).toHaveBeenCalledTimes(2);
    expect(result.current.prices?.status).toBe('ready');
  });

  it('does not expose a delayed A response after switching to B', async () => {
    let resolveA!: (value: StockOverview) => void;
    let resolveB!: (value: StockOverview) => void;
    overviewRequest.mockImplementation(
      (code: string) =>
        new Promise((resolve) => (code === 'A' ? (resolveA = resolve) : (resolveB = resolve))),
    );
    pricesRequest.mockResolvedValue(prices('B', '1Y'));
    const { result, rerender } = renderHook(({ code }) => useStockDetail(code, '1Y'), {
      initialProps: { code: 'A' },
    });
    rerender({ code: 'B' });
    await act(async () => resolveA(overview('A')));
    expect(result.current.overview.stock).toBeNull();
    await act(async () => resolveB(overview('B')));
    expect(result.current.overview.stock?.code).toBe('B');
  });

  it('does not retain A identity when B fails', async () => {
    overviewRequest
      .mockResolvedValueOnce(overview('A'))
      .mockRejectedValueOnce(new Error('B failed'));
    pricesRequest.mockResolvedValue(prices('A', '1Y'));
    const { result, rerender } = renderHook(({ code }) => useStockDetail(code, '1Y'), {
      initialProps: { code: 'A' },
    });
    await settle();
    rerender({ code: 'B' });
    await settle();
    expect(result.current.overview.stock).toBeNull();
    expect(result.current.overviewError?.message).toBe('B failed');
  });

  it('pauses pending polling while hidden and resumes when visible', async () => {
    overviewRequest.mockResolvedValue(overview('A'));
    pricesRequest.mockResolvedValue(prices('A', '1Y', 'pending'));
    renderHook(() => useStockDetail('A', '1Y'));
    await settle();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(pricesRequest).toHaveBeenCalledTimes(1);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    await settle();
    expect(pricesRequest).toHaveBeenCalledTimes(2);
  });

  it('clears old chart data when the period changes', async () => {
    overviewRequest.mockResolvedValue(overview('A'));
    pricesRequest.mockResolvedValue(prices('A', '1Y'));
    const { result, rerender } = renderHook(({ period }) => useStockDetail('A', period), {
      initialProps: { period: '1Y' as PricePeriod },
    });
    await settle();
    expect(result.current.prices?.period).toBe('1Y');
    pricesRequest.mockResolvedValue(prices('A', '3M'));
    act(() => rerender({ period: '3M' }));
    expect(result.current.prices).toBeNull();
    await settle();
  });

  it('clears a same-period error after a successful retry', async () => {
    overviewRequest.mockResolvedValue(overview('A'));
    pricesRequest
      .mockRejectedValueOnce(new Error('temporary'))
      .mockResolvedValueOnce(prices('A', '1Y'));
    const { result } = renderHook(() => useStockDetail('A', '1Y'));
    await settle();
    expect(result.current.priceError?.message).toBe('temporary');
    act(() => result.current.retryPrices());
    await settle();
    expect(result.current.priceError).toBeNull();
    expect(result.current.prices?.status).toBe('ready');
  });
});
