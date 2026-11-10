import { cleanup, render } from '@testing-library/react';
import { MarketActivitySummary } from './MarketActivitySummary';
import type { Resource, StockInvestorFlowData, StockQuoteData } from '@/lib/types';

function quoteWith(volumeChange: number | null | undefined): Resource<StockQuoteData> {
  return {
    status: 'ready',
    refreshing: false,
    retryAfterSeconds: null,
    sourceAsOf: null,
    collectedAt: '2026-10-27T09:00:00Z',
    data: {
      price: 222000,
      change: 1,
      changeAmount: 1,
      volume: 13585239,
      // 서버가 아직 이 필드를 주지 않는 경우(배포 순서 차이)도 깨지지 않아야 한다
      volumeChange: volumeChange as number | null,
      tradingValue: 100,
      marketCap: null,
    },
  };
}

afterEach(cleanup);

/** "거래량" 라벨(dt)이 속한 행(dt + dd)의 텍스트 */
function volumeRow(container: HTMLElement): string {
  const label = [...container.querySelectorAll('dt')].find((dt) =>
    dt.textContent?.includes('거래량'),
  );
  return label?.parentElement?.textContent ?? '';
}

it('shows the day-over-day volume change next to the volume', () => {
  const { container } = render(<MarketActivitySummary quote={quoteWith(18.76)} metrics={null} />);
  expect(volumeRow(container)).toContain('13,585,239주');
  expect(volumeRow(container)).toContain('+18.76%');
});

it('uses the minus sign for a decrease', () => {
  const { container } = render(<MarketActivitySummary quote={quoteWith(-38.1)} metrics={null} />);
  expect(volumeRow(container)).toContain('−38.10%');
});

it('shows 0.00% in flat tone instead of hiding it', () => {
  const { container } = render(<MarketActivitySummary quote={quoteWith(0)} metrics={null} />);
  expect(volumeRow(container)).toContain('0.00%');
});

it.each([null, undefined])('omits the change when it is %s but keeps the volume', (value) => {
  const { container } = render(<MarketActivitySummary quote={quoteWith(value)} metrics={null} />);
  expect(volumeRow(container)).toContain('13,585,239주');
  expect(volumeRow(container)).not.toContain('%');
  expect(volumeRow(container)).not.toContain('NaN');
});

function flowWith(
  status: Resource<StockInvestorFlowData>['status'],
  data: StockInvestorFlowData | null,
): Resource<StockInvestorFlowData> {
  return {
    status,
    refreshing: false,
    retryAfterSeconds: null,
    sourceAsOf: null,
    collectedAt: '2026-11-03T09:00:00Z',
    data,
  };
}

/** "기관 순매수" 라벨(dt)이 속한 행(dt + dd)의 텍스트 */
function institutionRow(container: HTMLElement): string {
  const label = [...container.querySelectorAll('dt')].find((dt) =>
    dt.textContent?.includes('기관 순매수'),
  );
  return label?.parentElement?.textContent ?? '';
}

function renderWithFlow(investorFlow: Resource<StockInvestorFlowData> | null | undefined) {
  return render(
    <MarketActivitySummary quote={quoteWith(0)} metrics={null} investorFlow={investorFlow} />,
  );
}

describe('기관 순매수', () => {
  it('shows a net buy with sign, amount and the trade date', () => {
    const { container } = renderWithFlow(
      flowWith('ready', {
        tradeDate: '2026-11-02',
        institutionNetQty: 1250,
        institutionNetValue: 8_500_000_000,
      }),
    );
    const row = institutionRow(container);
    expect(row).toContain('+1,250');
    expect(row).toContain('주');
    expect(row).toContain('85억');
    expect(row).toContain('2026. 11. 02 기준');
  });

  it('uses the minus sign for a net sell', () => {
    const { container } = renderWithFlow(
      flowWith('ready', {
        tradeDate: '2026-11-02',
        institutionNetQty: -1250,
        institutionNetValue: -8_500_000_000,
      }),
    );
    const row = institutionRow(container);
    expect(row).toContain('−1,250');
    expect(row).toContain('−85억');
  });

  it('omits the amount when the source did not give one', () => {
    const { container } = renderWithFlow(
      flowWith('ready', {
        tradeDate: '2026-11-02',
        institutionNetQty: 10,
        institutionNetValue: null,
      }),
    );
    const row = institutionRow(container);
    expect(row).toContain('+10');
    expect(row).toContain('2026. 11. 02 기준');
    expect(row).not.toContain('null');
    expect(row).not.toContain('NaN');
  });

  it('keeps showing the last value without a delay label when stale', () => {
    const { container } = renderWithFlow(
      flowWith('stale', {
        tradeDate: '2026-11-02',
        institutionNetQty: 5,
        institutionNetValue: null,
      }),
    );
    expect(institutionRow(container)).toContain('5');
    expect(institutionRow(container)).not.toContain('갱신 지연');
  });

  it('holds the place with a skeleton while the collector is still working', () => {
    const { container } = renderWithFlow(flowWith('pending', null));
    expect(institutionRow(container)).not.toContain('미제공');
    expect(institutionRow(container)).not.toContain('준비중');
  });

  it.each([
    ['unavailable', flowWith('unavailable', null)],
    ['empty', flowWith('empty', null)],
    ['a missing field (older server)', undefined],
    ['null', null],
  ])('shows 미제공 for %s', (_name, investorFlow) => {
    const { container } = renderWithFlow(investorFlow);
    expect(institutionRow(container)).toContain('미제공');
    expect(institutionRow(container)).not.toContain('NaN');
  });
});
