import { useState } from 'react';
import { SectionHead } from '@/components/layout/PageShell';
import { Card, Empty, Tabs } from '@/components/ui';
import type { Resource, StockFinancials, StockMetricsData, StockQuoteData } from '@/lib/types';
import { DetailInfoTab } from './DetailInfoTab';

type InsightTab = 'ai' | 'detail';
const TABS: { value: InsightTab; label: string }[] = [
  { value: 'ai', label: 'AI 보고서' },
  { value: 'detail', label: '상세 정보' },
];

export function StockInsightSection({
  quote,
  metrics,
  financials,
  financialsError,
  onRetryFinancials,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
  financials: StockFinancials | null;
  financialsError: Error | null;
  onRetryFinancials: () => void;
}) {
  const [tab, setTab] = useState<InsightTab>('ai');
  return (
    <section className="flex flex-col gap-3">
      <SectionHead title="AI 보고서 및 상세 정보" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === 'ai' ? (
        <Card tone="plain">
          <Empty title="AI 보고서는 준비 중입니다" />
        </Card>
      ) : (
        <DetailInfoTab
          quote={quote}
          metrics={metrics}
          financials={financials}
          error={financialsError}
          onRetry={onRetryFinancials}
        />
      )}
    </section>
  );
}
