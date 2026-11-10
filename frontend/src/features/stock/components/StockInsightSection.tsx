import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { SectionHead } from '@/components/layout/PageShell';
import { Tabs } from '@/components/ui';
import type {
  Resource,
  StockFinancials,
  StockMetricsData,
  StockQuoteData,
  StockReport,
} from '@/lib/types';
import type { ReportScrapState } from '../useReportScrap';
import { AiReportSection } from './AiReportSection';
import { DetailInfoTab } from './DetailInfoTab';

type InsightTab = 'ai' | 'detail';
const TABS: { value: InsightTab; label: string }[] = [
  { value: 'ai', label: 'AI 보고서' },
  { value: 'detail', label: '상세 정보' },
];

/** 홈의 보고서 카드가 `/stock/코드#report` 로 보내면 이 섹션을 화면 맨 위로 올린다. */
export const REPORT_HASH = '#report';

export function StockInsightSection({
  quote,
  metrics,
  financials,
  financialsError,
  onRetryFinancials,
  report,
  reportError,
  onRetryReport,
  reportScrap,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
  financials: StockFinancials | null;
  financialsError: Error | null;
  onRetryFinancials: () => void;
  report: Resource<StockReport> | null;
  reportError: Error | null;
  onRetryReport: () => void;
  reportScrap: ReportScrapState;
}) {
  const [tab, setTab] = useState<InsightTab>('ai');
  const { hash } = useLocation();
  const sectionRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (hash === REPORT_HASH) sectionRef.current?.scrollIntoView({ block: 'start' });
  }, [hash]);
  return (
    // scroll-mt: 위에 붙어 있는 사이트 헤더에 제목이 가려지지 않게 한다.
    <section ref={sectionRef} className="flex scroll-mt-16 flex-col gap-3">
      <SectionHead title="AI 보고서 및 상세 정보" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === 'ai' ? (
        <AiReportSection
          resource={report}
          error={reportError}
          onRetry={onRetryReport}
          scrap={reportScrap}
        />
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
