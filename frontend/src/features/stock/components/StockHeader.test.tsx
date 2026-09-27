import { cleanup, render } from '@testing-library/react';
import { StockHeader } from './StockHeader';
import type { Resource, StockIdentity, StockQuoteData } from '@/lib/types';

const stock: StockIdentity = {
  code: '000660',
  name: 'SK하이닉스',
  market: 'KOSPI',
  listingStatus: 'listed',
  listedAt: null,
};
const quote: Resource<StockQuoteData> = {
  status: 'stale',
  refreshing: false,
  retryAfterSeconds: null,
  sourceAsOf: null,
  collectedAt: '2026-09-20T01:23:00Z',
  data: { price: 100, change: 1, changeAmount: 1, volume: 1, tradingValue: 100, marketCap: null },
};
afterEach(cleanup);

it('labels the saved collection time when a stale quote has no source time', () => {
  const { container, getByText } = render(<StockHeader stock={stock} quote={quote} />);
  expect(getByText('이전 시세')).toBeTruthy();
  expect(container.textContent).toContain('수집 시각');
  expect(container.querySelector('time')?.dateTime).toBe(quote.collectedAt);
  expect(container.querySelector('time')?.textContent).toContain('10:23');
});
it('prefers source time and does not describe it as market close', () => {
  const sourceAsOf = '2026-09-20T01:20:00Z';
  const { container } = render(<StockHeader stock={stock} quote={{ ...quote, sourceAsOf }} />);
  expect(container.textContent).toContain('시세 기준');
  expect(container.textContent).not.toContain('수집 시각');
  expect(container.textContent).not.toContain('장 마감');
  expect(container.querySelector('time')?.dateTime).toBe(sourceAsOf);
});
it.each([
  { ...quote, collectedAt: null },
  { ...quote, data: null },
])('omits timestamps without a quote or timestamp', (resource) => {
  const { container } = render(<StockHeader stock={stock} quote={resource} />);
  expect(container.querySelector('time')).toBeNull();
});
