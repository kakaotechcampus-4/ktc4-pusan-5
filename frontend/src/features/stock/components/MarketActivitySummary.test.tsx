import { cleanup, render } from '@testing-library/react';
import { MarketActivitySummary } from './MarketActivitySummary';
import type { Resource, StockQuoteData } from '@/lib/types';

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
