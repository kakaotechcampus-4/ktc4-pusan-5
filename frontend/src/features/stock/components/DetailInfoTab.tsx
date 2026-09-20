import { Card, Empty, Kicker } from '@/components/ui';
import type { StockFinancials } from '@/lib/types';
import { AnnualFinancialTrend } from './AnnualFinancialTrend';
import { FinancialHealthSummary } from './FinancialHealthSummary';

export function DetailInfoTab({
  financials,
  error,
  onRetry,
}: {
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
        <Empty title="준비 중입니다" />
      </Card>
    </div>
  );
}
