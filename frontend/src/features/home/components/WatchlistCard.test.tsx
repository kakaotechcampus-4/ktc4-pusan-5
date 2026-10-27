import { cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { WatchlistEntry } from '@/lib/types';
import { WatchlistCard } from './WatchlistCard';

afterEach(cleanup);

function entry(code: string, name: string, quoteStatus: WatchlistEntry['quoteStatus']) {
  return {
    code,
    name,
    market: 'KOSPI' as const,
    quote: quoteStatus === 'pending' ? null : { price: 62400, change: -1.08, changeAmount: -680 },
    quoteStatus,
    asOf: quoteStatus === 'pending' ? null : '2026-10-02T06:40:00Z',
  };
}

function renderCard(items: WatchlistEntry[]) {
  return render(
    <MemoryRouter>
      <WatchlistCard
        status="success"
        items={items}
        onRetry={() => {}}
        onLoginClick={() => {}}
        onAddClick={() => {}}
      />
    </MemoryRouter>,
  );
}

it('labels only stale quotes as delayed and keeps showing the last value', () => {
  const { getAllByText, container } = renderCard([
    entry('005930', '삼성전자', 'ready'),
    entry('000660', 'SK하이닉스', 'stale'),
  ]);
  expect(getAllByText('갱신 지연')).toHaveLength(1);
  // 낡은 시세도 마지막 정상값은 그대로 보여준다.
  expect(container.textContent?.match(/62,400/g)).toHaveLength(2);
});

it('does not label fresh or not-yet-collected quotes as delayed', () => {
  const { queryByText, getByText } = renderCard([
    entry('005930', '삼성전자', 'ready'),
    entry('035420', 'NAVER', 'pending'),
  ]);
  expect(queryByText('갱신 지연')).toBeNull();
  expect(getByText('미제공')).toBeTruthy();
});
