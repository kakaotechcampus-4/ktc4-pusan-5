import { useState } from 'react';
import { SectionHead } from '@/components/layout/PageShell';
import { Card, Empty, Kicker, Tabs } from '@/components/ui';
import { useStockFinancials } from '../useStockFinancials';
import { AnnualFinancialTrend } from './AnnualFinancialTrend';

type InsightTab = 'ai' | 'detail';
const TABS: { value: InsightTab; label: string }[] = [
  { value: 'ai', label: 'AI 보고서' },
  { value: 'detail', label: '상세 정보' },
];

export function StockInsightSection({ code }: { code: string | undefined }) {
  const [tab, setTab] = useState<InsightTab>('ai');
  const { data, error, retry } = useStockFinancials(tab === 'detail' ? code : undefined);
  return (
    <section className="flex flex-col gap-3">
      <SectionHead title="AI 보고서 및 상세 정보" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === 'ai' ? (
        <Card tone="plain">
          <Empty title="AI 보고서는 준비 중입니다" />
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          <AnnualFinancialTrend financials={data} error={error} onRetry={retry} />
          {['재무 건전성 간단 요약', '투자 지표'].map((title) => (
            <Card key={title} tone="plain">
              <Kicker>{title}</Kicker>
              <Empty title="준비 중입니다" />
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
