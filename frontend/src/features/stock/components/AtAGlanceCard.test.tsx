import { cleanup, render } from '@testing-library/react';
import type {
  Resource,
  StockInvestorFlowData,
  StockMetricsData,
  StockQuoteData,
} from '@/lib/types';
import { AtAGlanceCard } from './AtAGlanceCard';

afterEach(cleanup);

function ready<T>(data: T): Resource<T> {
  return {
    status: 'ready',
    refreshing: false,
    retryAfterSeconds: null,
    sourceAsOf: null,
    collectedAt: '2026-11-02T09:00:00Z',
    data,
  };
}

const quote = ready<StockQuoteData>({
  price: 222000,
  change: 1,
  changeAmount: 1,
  volume: 100,
  volumeChange: null,
  tradingValue: 100,
  marketCap: null,
});
const metrics = ready<StockMetricsData>({
  per: null,
  pbr: null,
  eps: null,
  bps: null,
  foreignOwnership: 12.3,
  week52High: null,
  week52Low: null,
});

function foreignAndInstitutionRow(container: HTMLElement): string {
  const label = [...container.querySelectorAll('dt')].find((dt) =>
    dt.textContent?.includes('기관 순매수'),
  );
  return label?.parentElement?.textContent ?? '';
}

function renderCard(investorFlow: Resource<StockInvestorFlowData> | null | undefined) {
  return render(
    <AtAGlanceCard
      quote={quote}
      metrics={metrics}
      investorFlow={investorFlow}
      financials={null}
      financialsError={null}
      onRetryFinancials={() => {}}
    />,
  );
}

describe('AT A GLANCE 기관 순매수', () => {
  it('shows the net-buy quantity next to the foreign ownership', () => {
    const { container } = renderCard(
      ready<StockInvestorFlowData>({
        tradeDate: '2026-11-02',
        institutionNetQty: 1200,
        institutionNetValue: 8_500_000_000,
      }),
    );
    const row = foreignAndInstitutionRow(container);
    expect(row).toContain('+1,200주');
    expect(row).not.toContain('준비중');
  });

  it('uses the minus sign for net selling', () => {
    const { container } = renderCard(
      ready<StockInvestorFlowData>({
        tradeDate: '2026-11-02',
        institutionNetQty: -300,
        institutionNetValue: null,
      }),
    );
    expect(foreignAndInstitutionRow(container)).toContain('−300주');
  });

  it.each([
    ['null', null],
    ['a missing field (older server)', undefined],
  ])('shows 미제공 for %s', (_name, investorFlow) => {
    const { container } = renderCard(investorFlow);
    const row = foreignAndInstitutionRow(container);
    expect(row).toContain('미제공');
    expect(row).not.toContain('준비중');
  });
});
