import { useState } from 'react';
import { Tabs, Tag } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import type { StockDetail } from '../mock';
import { useMockReportStatus } from '../useStockDetail';
import { AiReportSection } from './AiReportSection';
import { DetailInfoTab } from './DetailInfoTab';

type InsightTab = 'ai' | 'detail';

const TABS: { value: InsightTab; label: string }[] = [
  { value: 'ai', label: 'AI 보고서' },
  { value: 'detail', label: '상세 정보' },
];

/**
 * 차트 바로 아래에 오는 [AI 보고서 | 상세 정보] 탭 섹션. 기본 탭은 AI 보고서라
 * 페이지를 열면 바로 보고서가 보인다.
 */
export function StockInsightSection({
  detail,
  code,
}: {
  detail: StockDetail;
  code: string | undefined;
}) {
  const [tab, setTab] = useState<InsightTab>('ai');
  const [reportStatus, retryReport] = useMockReportStatus(code);

  return (
    <section className="flex flex-col gap-3">
      <SectionHead
        title="AI 보고서 및 상세 정보"
        right={tab === 'ai' ? <Tag tone="ai">AI 생성</Tag> : undefined}
      />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {tab === 'ai' && (
        <AiReportSection status={reportStatus} report={detail.aiReport} onRetry={retryReport} />
      )}
      {tab === 'detail' && <DetailInfoTab detail={detail} />}
    </section>
  );
}
