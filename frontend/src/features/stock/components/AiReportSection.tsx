import { Card, Empty, ErrorBox, Kicker, SkeletonText, Tag } from '@/components/ui';
import { GuardrailNote } from '@/components/layout/GuardrailNote';
import { formatAsOf, formatDate } from '@/lib/format';
import type { Resource, StockReport } from '@/lib/types';
import type { ReportScrapState } from '../useReportScrap';
import { ReportBackgroundList } from './ReportBackgroundList';
import { ReportFactorList } from './ReportFactorList';
import { ReportScrapButton } from './ReportScrapButton';
import { ReportSummaryBlock } from './ReportSummaryBlock';
import { ReportTermList } from './ReportTermList';

/**
 * "AI 보고서" 탭의 내용물. 제목·탭은 부모(StockInsightSection)가 갖고 있어 여기선 카드 내용만 그린다.
 * 가드레일: 매수·매도 같은 투자의견 문구를 절대 넣지 않는다. (DESIGN.md 7절, 루트 CLAUDE.md)
 */
export function AiReportSection({
  resource,
  error,
  onRetry,
  scrap,
}: {
  resource: Resource<StockReport> | null;
  error: Error | null;
  onRetry: () => void;
  scrap: ReportScrapState;
}) {
  const report = resource?.data ?? null;
  const failed = error !== null || resource?.status === 'unavailable';
  const loading = !failed && resource === null;

  return (
    <Card tone="plain">
      <GuardrailNote />

      {loading && <SkeletonText lines={5} />}

      {failed && (
        <ErrorBox
          title="보고서를 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {!failed && resource !== null && report === null && (
        <Empty
          title="아직 보고서가 준비되지 않았습니다"
          description="장 마감 후 만들어집니다. 잠시 뒤 다시 확인해주세요"
        />
      )}

      {report && <ReportBody report={report} scrap={scrap} />}
    </Card>
  );
}

function ReportBody({ report, scrap }: { report: StockReport; scrap: ReportScrapState }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-600">
        <Tag tone="ai">AI 생성</Tag>
        <span>{formatAsOf(new Date(report.asOf), '보고서 기준')}</span>
        {report.generatedAt && <span>· {formatDate(new Date(report.generatedAt))} 생성</span>}
        <span className="ml-auto">
          <ReportScrapButton scrap={scrap} />
        </span>
      </div>

      <ReportSummaryBlock
        summary={report.summary}
        verdict={report.verdict}
        relativeVerdict={report.relativeVerdict}
      />

      {report.factors.length > 0 && (
        <section className="flex flex-col gap-2">
          <Kicker>움직인 이유</Kicker>
          <ReportFactorList factors={report.factors} />
        </section>
      )}

      {report.terms.length > 0 && (
        <section className="flex flex-col gap-2">
          <Kicker>용어 풀이</Kicker>
          <ReportTermList terms={report.terms} />
        </section>
      )}

      <ReportBackgroundList background={report.background} />
    </div>
  );
}
