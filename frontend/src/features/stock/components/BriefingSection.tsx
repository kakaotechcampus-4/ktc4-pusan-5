import { Card, SkeletonText, Tag } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { Empty, ErrorBox } from '@/components/ui';
import { formatAsOf } from '@/lib/format';
import type { Briefing } from '../mock';

export type BriefingStatus = 'loading' | 'empty' | 'error' | 'success';

export function BriefingSection({
  status,
  briefing,
  onRetry,
}: {
  status: BriefingStatus;
  briefing: Briefing;
  onRetry: () => void;
}) {
  return (
    <section>
      <SectionHead title="왜 움직였나" right={<Tag tone="ai">AI 요약</Tag>} />
      <Card>
        {status === 'loading' && <SkeletonText lines={4} />}
        {status === 'error' && (
          <ErrorBox
            title="브리핑을 불러오지 못했습니다"
            description="잠시 후 다시 시도해주세요"
            onRetry={onRetry}
          />
        )}
        {status === 'empty' && (
          <Empty
            title="아직 브리핑이 준비되지 않았습니다"
            description="잠시 후 다시 확인해주세요"
          />
        )}
        {status === 'success' && (
          <>
            <p className="text-sm leading-relaxed text-ink">{briefing.text}</p>
            <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-600">
              <span>{formatAsOf(new Date(briefing.generatedAt), 'AI 생성')}</span>
              <span>· 출처 {briefing.sources.join(', ')}</span>
            </div>
          </>
        )}
      </Card>
    </section>
  );
}
