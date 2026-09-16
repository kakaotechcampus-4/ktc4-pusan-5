import { Stat, StatGrid } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatCompactKRW } from '@/lib/format';
import type { FinancialSummary } from '../mock';

export function FinancialSummarySection({ financials }: { financials: FinancialSummary }) {
  return (
    <section>
      <SectionHead title="재무 실적" />
      <StatGrid>
        <Stat label="매출액" value={formatCompactKRW(financials.revenue)} />
        <Stat label="영업이익" value={formatCompactKRW(financials.operatingProfit)} />
        <Stat label="순이익" value={formatCompactKRW(financials.netIncome)} />
      </StatGrid>
    </section>
  );
}
