/**
 * 종목 브리핑 화면이 부르는 세 API 의 목업.
 *   GET /api/stocks/{code}/overview · /prices · /financials
 * 숫자는 가공하지 않은 원본 값이다. 종목명에 "목업"을 넣어 실제 데이터와 구분한다.
 *
 * Resource 는 전부 ready·refreshing false·retryAfterSeconds null 로 둔다.
 * 그래야 화면이 빠른 재조회(폴링)를 걸지 않아 테스트 중 요청 수가 흔들리지 않는다.
 */
import type {
  Candle,
  Resource,
  StockFinancials,
  StockOverview,
  StockPriceResource,
} from '../../src/lib/types';
import { mergeDeep, type DeepPartial } from './deepMerge';
import { mockAsOf, mockCollectedAt, mockPrimaryStock } from './sharedMocks';

const mockStockCode = mockPrimaryStock.code;

/** 서비스하지 않는 종목 코드 자리. 404 STOCK_NOT_FOUND 시나리오에 쓴다 */
export const mockUnknownStockCode = 'NOPE00';

function mockResource<TData>(data: TData): Resource<TData> {
  return {
    status: 'ready',
    refreshing: false,
    data,
    sourceAsOf: mockAsOf,
    collectedAt: mockCollectedAt,
    retryAfterSeconds: null,
  };
}

export function mockStockOverview(overrides?: DeepPartial<StockOverview>): StockOverview {
  return mergeDeep<StockOverview>(
    {
      stock: {
        code: mockStockCode,
        name: mockPrimaryStock.name,
        market: mockPrimaryStock.market,
        listingStatus: 'listed',
        listedAt: '1975-06-11',
      },
      quote: mockResource({
        price: 62400,
        change: -1.08,
        changeAmount: -680,
        volume: 14203000,
        volumeChange: 3.2,
        tradingValue: 886267200000,
        marketCap: 372000000000000,
      }),
      metrics: mockResource({
        per: 11.4,
        pbr: 1.32,
        eps: 5473,
        bps: 47273,
        foreignOwnership: 51.2,
        week52High: 71200,
        week52Low: 49900,
      }),
    },
    overrides,
  );
}

/** 2026-08-21 까지 평일 일봉 20개. 날짜·값이 매번 같아야 화면이 매번 같다 */
function mockCandles(): Candle[] {
  const candles: Candle[] = [];
  const day = new Date(Date.UTC(2026, 7, 21));
  while (candles.length < 20) {
    const weekday = day.getUTCDay();
    if (weekday !== 0 && weekday !== 6) {
      const close = 60000 + (20 - candles.length) * 120;
      candles.unshift({
        date: day.toISOString().slice(0, 10),
        open: close - 200,
        high: close + 400,
        low: close - 500,
        close,
        volume: 12000000 + candles.length * 10000,
      });
    }
    day.setUTCDate(day.getUTCDate() - 1);
  }
  return candles;
}

export function mockStockPrices(overrides?: DeepPartial<StockPriceResource>): StockPriceResource {
  const candles = mockCandles();
  return mergeDeep<StockPriceResource>(
    {
      ...mockResource(candles),
      code: mockStockCode,
      period: '1Y',
      adjustment: 'raw',
      coverage: {
        fromDate: candles[0].date,
        toDate: candles[candles.length - 1].date,
        complete: true,
      },
    },
    overrides,
  );
}

export function mockStockFinancials(overrides?: DeepPartial<StockFinancials>): StockFinancials {
  return mergeDeep<StockFinancials>(
    {
      code: mockStockCode,
      source: 'KIS',
      basis: 'provider',
      income: mockResource([
        {
          fiscalPeriod: '2024-12',
          revenue: 300870900000000,
          operatingProfit: 32726000000000,
          netIncome: 34451400000000,
        },
        {
          fiscalPeriod: '2025-12',
          revenue: 312400000000000,
          operatingProfit: 35100000000000,
          netIncome: 36200000000000,
        },
      ]),
      eps: mockResource([
        { fiscalPeriod: '2024-12', eps: 4950 },
        { fiscalPeriod: '2025-12', eps: 5473 },
      ]),
      health: mockResource({
        fiscalPeriod: '2025-12',
        debtRatio: 26.4,
        roe: 9.1,
        operatingMargin: 11.2,
        currentRatio: 258.8,
      }),
      investment: mockResource([
        {
          fiscalPeriod: '2025-09',
          revenueGrowth: { value: 3.8, status: 'value' },
          operatingProfitGrowth: { value: 7.2, status: 'value' },
          netIncomeGrowth: { value: 5.1, status: 'value' },
          operatingProfit: 9100000000000,
          netIncome: 9400000000000,
          epsCumulative: 4100,
          bps: 47273,
          roe: 9.1,
          debtRatio: 26.4,
          rs: 62,
          rsAsOf: mockAsOf,
          rsBaseDate: '2026-08-21',
          marketCap: 372000000000000,
          marketCapAsOf: mockAsOf,
          per: 11.4,
          pbr: 1.32,
        },
      ]),
    },
    overrides,
  );
}
