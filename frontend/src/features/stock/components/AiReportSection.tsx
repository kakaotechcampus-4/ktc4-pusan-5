import { Card, Empty, ErrorBox, SkeletonText, Tag } from '@/components/ui';
import { GuardrailNote } from '@/components/layout/GuardrailNote';
import { SectionHead } from '@/components/layout/PageShell';
import { formatAsOf, formatPrice } from '@/lib/format';
import type { AiReport } from '../mock';

export type AiReportStatus = 'loading' | 'empty' | 'error' | 'success';
/*
 * 가드레일: 매수·매도 같은 투자의견 문구를 절대 넣지 않는다. (DESIGN.md 7절, 루트 CLAUDE.md)
 */
export function AiReportSection({
  status,
  report,
  onRetry,
}: {
  status: AiReportStatus;
  report: AiReport;
  onRetry: () => void;
}) {
  return (
    <section>
      <SectionHead title="AI 투자 분석 보고서" right={<Tag tone="ai">AI 생성</Tag>} />
      <Card tone="plain">
        <GuardrailNote />

        {status === 'loading' && <SkeletonText lines={5} />}

        {status === 'error' && (
          <ErrorBox
            title="보고서를 불러오지 못했습니다"
            description="잠시 후 다시 시도해주세요"
            onRetry={onRetry}
          />
        )}

        {status === 'empty' && (
          <Empty
            title="아직 보고서가 준비되지 않았습니다"
            description="잠시 후 다시 확인해주세요"
          />
        )}

        {status === 'success' && (
          <>
            <ul className="text-ink flex list-disc flex-col gap-1.5 pl-5 text-sm leading-relaxed">
              {report.summaryPoints.map((point, i) => (
                <li key={i}>{point}</li>
              ))}
            </ul>

            <p className="text-sm leading-relaxed text-neutral-700">{report.conclusion}</p>

            {report.targetPrice && (
              <p className="text-sm text-neutral-700">
                목표주가{' '}
                <span className="num text-ink font-semibold">
                  {formatPrice(report.targetPrice.value)}원
                </span>{' '}
                <span className="text-xs text-neutral-600">
                  (출처: {report.targetPrice.source})
                </span>
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-600">
              <span>{formatAsOf(new Date(report.generatedAt), 'AI 생성')}</span>
              <span>· 출처 {report.sources.join(', ')}</span>
            </div>
          </>
        )}
      </Card>
    </section>
  );
}
