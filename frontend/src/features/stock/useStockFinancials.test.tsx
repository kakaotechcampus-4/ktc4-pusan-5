import { act, render, renderHook, screen } from '@testing-library/react';
import type {
  FinancialEpsPoint,
  FinancialIncomePoint,
  Resource,
  StockFinancials,
} from '@/lib/types';
import { getStockFinancials } from '@/lib/api';
import { useStockFinancials } from './useStockFinancials';
import { mergeAnnualRows } from './financialUtils';
import { AnnualFinancialTrend } from './components/AnnualFinancialTrend';

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return { ...actual, getStockFinancials: vi.fn() };
});

const financialsRequest = vi.mocked(getStockFinancials);

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

function financials(
  code: string,
  income: Resource<FinancialIncomePoint[]>,
  eps: Resource<FinancialEpsPoint[]>,
): StockFinancials {
  return { code, source: 'KIS', basis: 'provider', income, eps };
}

async function settle() {
  await act(async () => await Promise.resolve());
}

describe('useStockFinancials', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  });
  afterEach(() => vi.useRealTimers());

  it('polls pending income and EPS until both are ready', async () => {
    const pending = financials(
      'A',
      resource<FinancialIncomePoint[]>('pending', null),
      resource<FinancialEpsPoint[]>('pending', null),
    );
    const ready = financials('A', resource('ready', []), resource('ready', []));
    financialsRequest.mockResolvedValueOnce(pending).mockResolvedValueOnce(ready);
    const { result } = renderHook(() => useStockFinancials('A'));
    await settle();
    expect(result.current.data?.income.status).toBe('pending');
    await act(async () => vi.advanceTimersByTimeAsync(3000));
    expect(financialsRequest).toHaveBeenCalledTimes(2);
    expect(result.current.data?.income.status).toBe('ready');
  });

  it('merges exact periods while preserving null, zero, and negative values', () => {
    const income: FinancialIncomePoint[] = [
      { fiscalPeriod: '2024-12', revenue: 0, operatingProfit: -10, netIncome: null },
    ];
    const eps: FinancialEpsPoint[] = [
      { fiscalPeriod: '2024-12', eps: 0 },
      { fiscalPeriod: '2023-12', eps: -2 },
    ];
    expect(mergeAnnualRows(income, eps)).toEqual([
      { fiscalPeriod: '2023-12', revenue: null, operatingProfit: null, netIncome: null, eps: -2 },
      { fiscalPeriod: '2024-12', revenue: 0, operatingProfit: -10, netIncome: null, eps: 0 },
    ]);
  });

  it('keeps successful income visible when EPS is unavailable', async () => {
    const income: FinancialIncomePoint[] = [
      { fiscalPeriod: '2024-12', revenue: 10, operatingProfit: 3, netIncome: 2 },
    ];
    financialsRequest.mockResolvedValue(
      financials(
        'A',
        resource('ready', income),
        resource<FinancialEpsPoint[]>('unavailable', null, { retryAfterSeconds: null }),
      ),
    );
    const { result } = renderHook(() => useStockFinancials('A'));
    await settle();
    expect(result.current.data?.income.data).toEqual(income);
    expect(result.current.data?.eps.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('shows collecting state instead of empty state for cold pending resources', () => {
    render(
      <AnnualFinancialTrend
        financials={financials(
          'A',
          resource<FinancialIncomePoint[]>('pending', null),
          resource<FinancialEpsPoint[]>('pending', null),
        )}
        error={null}
        onRetry={() => undefined}
      />,
    );
    expect(screen.getByRole('status', { name: '재무 데이터 불러오는 중' })).toBeTruthy();
    expect(screen.queryByText('재무 데이터를 수집하고 있습니다.')).toBeNull();
    expect(screen.queryByText('재무 추이 데이터가 없습니다')).toBeNull();
  });

  it('does not expose delayed A financials after navigating to B', async () => {
    let resolveA!: (value: StockFinancials) => void;
    let resolveB!: (value: StockFinancials) => void;
    financialsRequest.mockImplementation(
      (code: string) =>
        new Promise((resolve) => (code === 'A' ? (resolveA = resolve) : (resolveB = resolve))),
    );
    const { result, rerender } = renderHook(({ code }) => useStockFinancials(code), {
      initialProps: { code: 'A' },
    });
    act(() => rerender({ code: 'B' }));
    await act(async () => resolveA(financials('A', resource('ready', []), resource('ready', []))));
    expect(result.current.data).toBeNull();
    await act(async () => resolveB(financials('B', resource('ready', []), resource('ready', []))));
    expect(result.current.data?.code).toBe('B');
  });
});
