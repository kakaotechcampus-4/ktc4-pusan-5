import { Card, ErrorBox, Skeleton, SkeletonText, Tag } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatAsOf } from '@/lib/format';
import type { MarketInsight } from '../mock';

export type MarketInsightStatus = 'loading' | 'error' | 'success';

export function MarketInsightSection({
  status,
  insights,
  onRetry,
}: {
  status: MarketInsightStatus;
  insights: { items: MarketInsight[]; generatedAt: string; sources: string[] };
  onRetry: () => void;
}) {
  return (
    <section className="flex flex-col gap-3">
      <SectionHead title="마켓 인사이트" right={<Tag tone="ai">AI 요약</Tag>} />

      {status === 'loading' && <MarketInsightSkeleton />}

      {status === 'error' && (
        <ErrorBox
          title="마켓 인사이트를 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status === 'success' && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {insights.items.map((item) => (
              <Card key={item.id} tone="plain">
                <div className="text-h3 leading-tight font-bold">{item.title}</div>
                <p className="text-sm text-neutral-700">{item.summary}</p>
              </Card>
            ))}
          </div>

          {/* LLM 생성 필드는 생성 기준 시각과 출처를 함께 노출한다. (루트 CLAUDE.md) */}
          <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-600">
            <span>{formatAsOf(new Date(insights.generatedAt), 'AI 생성')}</span>
            <span>· 출처 {insights.sources.join(', ')}</span>
          </div>
        </>
      )}
    </section>
  );
}

function MarketInsightSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i} tone="plain">
          <Skeleton className="h-6 w-3/4" />
          <SkeletonText lines={2} />
        </Card>
      ))}
    </div>
  );
}
