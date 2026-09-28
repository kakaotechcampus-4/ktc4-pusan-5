import type { ReactNode } from 'react';
import {
  Card,
  Change,
  Empty,
  InfoTip,
  Kicker,
  Skeleton,
  SkeletonText,
  StatList,
  StatListItem,
  Tag,
} from '@/components/ui';
import { formatMultiple, formatRatio } from '@/lib/format';
import type { Resource, StockFinancials, StockMetricsData, StockQuoteData } from '@/lib/types';
import { distanceFromWeek52High, growthLabel } from '../financialUtils';

function renderValue(value: number | null, render: (number: number) => string) {
  return value === null ? '—' : render(value);
}

function latestInvestmentPoint(financials: StockFinancials | null) {
  const points = financials?.investment.data;
  if (!points?.length) return null;
  return [...points].sort((a, b) => a.fiscalPeriod.localeCompare(b.fiscalPeriod)).at(-1) ?? null;
}

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
  const financialsLoading = financials === null;
  const latestPoint = latestInvestmentPoint(financials);
  const health = financials?.health.data ?? null;
  const weekPosition = q && m?.week52High ? distanceFromWeek52High(q.price, m.week52High) : null;

  const financialsValue = (node: ReactNode) =>
    financialsLoading ? <Skeleton className="h-4 w-16" /> : node;

  const rows: { label: string; description: string; value: ReactNode }[] = [
    {
      label: '시장위치',
      description: '52주 최고가 대비 현재 주가의 위치입니다.',
      value:
        weekPosition === null ? (
          <span className="num text-sm font-semibold">—</span>
        ) : (
          <Change value={weekPosition} size="sm" />
        ),
    },
    {
      label: '수급',
      description:
        '외국인 보유 지분율과 최근 기관 순매수 동향입니다. 기관 순매수는 아직 연동되지 않았습니다.',
      value: (
        <span className="num text-sm font-semibold">
          {`외인 ${renderValue(m?.foreignOwnership ?? null, formatRatio)} / 기관 `}
          <span className="text-neutral-600">준비중</span>
        </span>
      ),
    },
    {
      label: '실적모멘텀',
      description: '최근 분기 영업이익 성장률(전년 동기 대비)입니다.',
      value: financialsValue(
        latestPoint ? (
          growthLabel(latestPoint.operatingProfitGrowth)
        ) : (
          <span className="num text-sm font-semibold">—</span>
        ),
      ),
    },
    {
      label: '밸류에이션',
      description: 'PER은 주가를 EPS로, PBR은 주가를 BPS로 나눈 값입니다.',
      value: (
        <span className="num text-sm font-semibold">
          {`PER ${renderValue(m?.per ?? null, formatMultiple)} / PBR ${renderValue(m?.pbr ?? null, formatMultiple)}`}
        </span>
      ),
    },
    {
      label: '안전성',
      description: '자기자본 대비 부채 비율입니다.',
      value: financialsValue(
        <span className="num text-sm font-semibold">
          {renderValue(health?.debtRatio ?? null, formatRatio)}
        </span>,
      ),
    },
  ];
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
