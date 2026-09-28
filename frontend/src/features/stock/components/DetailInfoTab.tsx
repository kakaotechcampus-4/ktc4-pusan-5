import { Card, Kicker } from '@/components/ui';
import type { Resource, StockFinancials, StockMetricsData, StockQuoteData } from '@/lib/types';
import { AnnualFinancialTrend } from './AnnualFinancialTrend';
import { FinancialHealthSummary } from './FinancialHealthSummary';
import { MarketActivitySummary } from './MarketActivitySummary';
import { QuarterlyMetricsTable } from './QuarterlyMetricsTable';

export function DetailInfoTab({
  quote,
  metrics,
  financials,
  error,
  onRetry,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
  financials: StockFinancials | null;
  error: Error | null;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <AnnualFinancialTrend financials={financials} error={error} onRetry={onRetry} />
      <Card tone="plain">
        <Kicker>재무 건전성 간단 요약</Kicker>
        <FinancialHealthSummary
          health={financials?.health ?? null}
          error={error}
          onRetry={onRetry}
        />
      </Card>
      <Card tone="plain">
        <Kicker>투자 지표</Kicker>
        <Kicker>시세 및 거래</Kicker>
        <MarketActivitySummary quote={quote} metrics={metrics} />
        <QuarterlyMetricsTable investment={financials?.investment ?? null} error={error} />
      </Card>
    </div>
  );
}
