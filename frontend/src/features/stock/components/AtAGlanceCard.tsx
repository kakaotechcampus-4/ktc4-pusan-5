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
import { distanceFromWeek52High, distanceFromWeek52Low, growthLabel } from '../financialUtils';

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
  const weekHighPosition =
    q && m?.week52High ? distanceFromWeek52High(q.price, m.week52High) : null;
  const weekLowPosition = q && m?.week52Low ? distanceFromWeek52Low(q.price, m.week52Low) : null;

  const financialsValue = (node: ReactNode) =>
    financialsLoading ? <Skeleton className="h-4 w-16" /> : node;

  const rows: { label: string; description: string; value: ReactNode }[] = [
    {
      label: '시장위치',
      description: '52주 최고가/최저가 대비 현재 주가의 위치',
      value:
        weekHighPosition === null || weekLowPosition === null ? (
          <span className="num text-sm font-semibold">—</span>
        ) : (
          <span className="flex flex-wrap items-center justify-end gap-1 text-sm font-semibold">
            <span className="text-neutral-600">최고 대비</span>
            <Change value={weekHighPosition} size="sm" />
            <span className="text-neutral-600">/ 최저 대비</span>
            <Change value={weekLowPosition} size="sm" />
          </span>
        ),
    },
    {
      label: '외국인 지분율 및 기관 순매수',
      description:
        '외국인과 기관은 개인 투자자에 비해 막대한 자금력과 정보력을 가진 세력으로, 차트 패턴의 신뢰성을 확인할 수 있습니다.',
      value: (
        <span className="num text-sm font-semibold">
          <span className="text-neutral-600">외인</span>{' '}
          {renderValue(m?.foreignOwnership ?? null, formatRatio)}
          {' / 기관 '}
          <span className="text-neutral-600">준비중</span>
        </span>
      ),
    },
    {
      label: '영업이익 성장률',
      description:
        '전년 대비 영업이익 증가 폭입니다. 차트 우상향이나 신고가 형성 시 높은 성장률이 뒷받침되면 상승 추세가 길게 유지됩니다.',
      value: financialsValue(
        latestPoint ? (
          growthLabel(latestPoint.operatingProfitGrowth)
        ) : (
          <span className="num text-sm font-semibold">—</span>
        ),
      ),
    },
    {
      label: 'PER / PBR',
      description:
        '현재 주가가 고평가되고 있는지 확인할 수 있습니다. PER은 기업이 버는 이익 대비 주가, PBR은 기업의 순자산 대비 주가를 의미합니다',
      value: (
        <span className="num text-sm font-semibold">
          <span className="text-neutral-600">PER</span>{' '}
          {renderValue(m?.per ?? null, formatMultiple)}
          {' / '}
          <span className="text-neutral-600">PBR</span>{' '}
          {renderValue(m?.pbr ?? null, formatMultiple)}
        </span>
      ),
    },
    {
      label: '저가자본 대비 부채비율',
      description: '매수시 유상증자나 악재 위험 같은 리스크를 확인할 수 있습니다.',
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
