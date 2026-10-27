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
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="border-divider flex flex-col gap-2 md:border-r md:pr-6">
            <Kicker>재무 건전성 간단 요약</Kicker>
            <FinancialHealthSummary
              health={financials?.health ?? null}
              error={error}
              onRetry={onRetry}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Kicker>시세 및 거래</Kicker>
            <MarketActivitySummary quote={quote} metrics={metrics} />
          </div>
        </div>
      </Card>
      <Card tone="plain">
        <Kicker>투자 지표</Kicker>
        <QuarterlyMetricsTable investment={financials?.investment ?? null} error={error} />
      </Card>
    </div>
  );
}
