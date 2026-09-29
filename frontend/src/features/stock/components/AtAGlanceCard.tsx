import {
  Card,
  Empty,
  InfoTip,
  Kicker,
  SkeletonText,
  StatList,
  StatListItem,
  Tag,
} from '@/components/ui';
import type { Resource, StockFinancials, StockMetricsData, StockQuoteData } from '@/lib/types';
import { buildAtAGlanceRows } from '../atAGlanceRows';

export function AtAGlanceCard({
  quote,
  metrics,
  financials,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
  financials: StockFinancials | null;
}) {
  if (!quote && !metrics)
    return (
      <Card tone="plain">
        <Kicker>AT A GLANCE · 핵심 지표</Kicker>
        <SkeletonText lines={5} />
      </Card>
    );
  const q = quote?.data;
  const m = metrics?.data;
  const rows = buildAtAGlanceRows({ quote: q, metrics: m, financials });
  const unavailable = [quote?.status, metrics?.status].some(
    (status) => status === 'unavailable' || status === 'empty',
  );
  return (
    <Card tone="plain" className="flex-1">
      <Kicker>AT A GLANCE · 핵심 지표</Kicker>
      {quote?.status === 'unavailable' && (
        <p className="mb-2 text-sm text-neutral-600">현재 시세를 준비하지 못했습니다</p>
      )}
      {metrics?.status === 'stale' && <Tag>이전 지표</Tag>}
      {metrics?.status === 'unavailable' && (
        <p className="mb-2 text-sm text-neutral-600">주요 지표를 준비하지 못했습니다</p>
      )}
      {unavailable && !q && !m ? (
        <Empty title="주요 지표를 준비하지 못했습니다" description="잠시 후 다시 확인해주세요" />
      ) : (
        <StatList className="flex-1 justify-center">
          {rows.map((row) => (
            <StatListItem
              key={row.label}
              layout="stack"
              label={
                <>
                  {row.label}
                  <InfoTip description={row.description} />
                </>
              }
              value={row.value}
            />
          ))}
        </StatList>
      )}
    </Card>
  );
}
