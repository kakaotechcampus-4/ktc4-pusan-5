import { Card, Kicker } from '@/components/ui';
import type { StockDetail } from '../mock';
import { FinancialTrendTable } from './FinancialTrendTable';
import { FinancialHealthSummary } from './FinancialHealthSummary';
import { QuarterlyMetricsTable } from './QuarterlyMetricsTable';

/** "상세 정보" 탭. 재무 추이·재무 건전성·분기별 투자 지표 세 덩어리로 구성한다. */
export function DetailInfoTab({ detail }: { detail: StockDetail }) {
  return (
    <div className="flex flex-col gap-4">
      <Card tone="plain">
        <Kicker>재무 추이</Kicker>
        <FinancialTrendTable trend={detail.financialTrend} />
      </Card>

      <Card tone="plain">
        <Kicker>재무 건전성 간단 요약</Kicker>
        <FinancialHealthSummary health={detail.financialHealth} financials={detail.financials} />
      </Card>

      <Card tone="plain">
        <Kicker>투자 지표</Kicker>
        <QuarterlyMetricsTable metrics={detail.quarterlyMetrics} />
      </Card>
    </div>
  );
}
