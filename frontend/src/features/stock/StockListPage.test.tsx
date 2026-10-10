import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { StockListItem } from '@/lib/types';
import { listStocks } from '@/lib/api';
import { formatAsOf } from '@/lib/format';
import { StockListPage } from './StockListPage';

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return { ...actual, listStocks: vi.fn() };
});

const listStocksRequest = vi.mocked(listStocks);

function stock(rank: number, name: string, sector: string): StockListItem {
  return { rank, code: String(rank).padStart(6, '0'), name, market: 'KOSPI', sector };
}

// 1~10위 구간에는 전기전자만, 11~20위 구간에는 제약만 있다
const items: StockListItem[] = [
  stock(1, 'SK하이닉스', '전기전자'),
  stock(2, '삼성전자', '전기전자'),
  stock(11, '유한양행', '제약'),
  stock(12, '셀트리온', '제약'),
];

const AS_OF = '2026-10-04T12:00:00+09:00';

async function renderPage() {
  listStocksRequest.mockResolvedValue({ items, asOf: AS_OF });
  render(
    <MemoryRouter>
      <StockListPage />
    </MemoryRouter>,
  );
  await screen.findByRole('group', { name: '업종' });
}

function visibleNames() {
  return screen.getAllByRole('link').map((link) => link.querySelector('span span')?.textContent);
}

afterEach(cleanup);

it('hides rank sections that have no stock in the selected sector', async () => {
  await renderPage();
  expect(screen.getByText('1~10위')).toBeTruthy();
  expect(screen.getByText('11~20위')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: '제약 (2)' }));

  await waitFor(() => expect(screen.queryByText('1~10위')).toBeNull());
  expect(screen.getByText('11~20위')).toBeTruthy();
  expect(visibleNames()).toEqual(['유한양행', '셀트리온']);
});

it('keeps the selected sector when the sort order changes', async () => {
  await renderPage();
  fireEvent.click(screen.getByRole('button', { name: '전기전자 (2)' }));
  expect(visibleNames()).toEqual(['SK하이닉스', '삼성전자']);

  fireEvent.change(screen.getByLabelText('정렬'), { target: { value: 'name' } });

  expect(screen.getByRole('button', { name: '전기전자 (2)' }).getAttribute('aria-pressed')).toBe(
    'true',
  );
  expect(visibleNames()).toEqual(['삼성전자', 'SK하이닉스']);
  expect(screen.queryByText('1~10위')).toBeNull();
});

it('shows the asOf time from the response next to the market cap ranking', async () => {
  await renderPage();
  expect(screen.getByText(formatAsOf(new Date(AS_OF), '시가총액 기준'))).toBeTruthy();

  fireEvent.change(screen.getByLabelText('정렬'), { target: { value: 'name' } });

  expect(screen.queryByText(formatAsOf(new Date(AS_OF), '시가총액 기준'))).toBeNull();
});
