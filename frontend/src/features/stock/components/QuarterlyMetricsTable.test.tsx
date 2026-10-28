import { cleanup, render } from '@testing-library/react';
import { QuarterlyMetricsTable } from './QuarterlyMetricsTable';
import type { InvestmentPoint, Resource } from '@/lib/types';

const growth = { value: null, status: 'unavailable' } as const;

function point(fiscalPeriod: string, bps: number | null | undefined): InvestmentPoint {
  return {
    fiscalPeriod,
    revenueGrowth: growth,
    operatingProfitGrowth: growth,
    netIncomeGrowth: growth,
    operatingProfit: null,
    netIncome: null,
    epsCumulative: null,
    // 서버가 아직 이 필드를 주지 않는 경우(배포 순서 차이)도 깨지지 않아야 한다
    bps: bps as number | null,
    roe: null,
    debtRatio: null,
    rs: null,
    rsAsOf: null,
    rsBaseDate: null,
    marketCap: null,
    marketCapAsOf: null,
    per: null,
    pbr: null,
  };
}

function resource(data: InvestmentPoint[]): Resource<InvestmentPoint[]> {
  return {
    status: 'ready',
    refreshing: false,
    retryAfterSeconds: null,
    sourceAsOf: null,
    collectedAt: '2026-10-27T09:00:00Z',
    data,
  };
}

afterEach(cleanup);

/** 지표 이름으로 행을 찾아 분기별 셀 텍스트를 돌려준다 */
function cellsOf(container: HTMLElement, label: string): string[] {
  const row = [...container.querySelectorAll('tbody tr')].find((tr) =>
    tr.querySelector('th')?.textContent?.trim().startsWith(label),
  );
  return [...(row?.querySelectorAll('td') ?? [])].map((td) => td.textContent ?? '');
}

it('shows quarterly BPS in won, and 미제공 for a quarter without it', () => {
  const { container } = render(
    <QuarterlyMetricsTable
      investment={resource([
        point('2026-03', 71907),
        point('2026-06', 86052),
        point('2026-09', null),
      ])}
    />,
  );
  expect(cellsOf(container, 'BPS')).toEqual(['71,907원', '86,052원', '미제공']);
});

it('treats a missing bps field like null instead of printing NaN', () => {
  const { container } = render(
    <QuarterlyMetricsTable investment={resource([point('2026-06', undefined)])} />,
  );
  expect(cellsOf(container, 'BPS')).toEqual(['미제공']);
});
