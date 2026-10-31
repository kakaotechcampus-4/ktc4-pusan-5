import type { ReactNode } from 'react';
import { Change, InfoTip, SkeletonText, StatList, StatListItem } from '@/components/ui';
import { formatCompactKRW, formatPrice, formatRatio } from '@/lib/format';
import type { Resource, StockMetricsData, StockQuoteData } from '@/lib/types';
import { NO_VALUE } from '../financialUtils';

function renderValue(value: number | null | undefined, render: (value: number) => string) {
  return value === null || value === undefined ? NO_VALUE : render(value);
}

function num(value: ReactNode) {
  return <span className="num text-sm font-semibold">{value}</span>;
}

export function MarketActivitySummary({
  quote,
  metrics,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
}) {
  if (!quote && !metrics) return <SkeletonText lines={5} />;
  const q = quote?.data;
  const m = metrics?.data;
  return (
    <StatList>
      <StatListItem label="시가총액" value={num(renderValue(q?.marketCap, formatCompactKRW))} />
      <StatListItem
        label={
          <>
            거래량{' '}
            <InfoTip description="전일 대비 거래량 변화율입니다. 장중에는 오늘 거래량이 쌓이는 중이라 낮게 보일 수 있고, 전일 거래량이 없으면 표시하지 않습니다." />
          </>
        }
        value={
          <span className="flex items-baseline gap-2">
            {num(q ? `${formatPrice(q.volume)}주` : NO_VALUE)}
            {typeof q?.volumeChange === 'number' && <Change value={q.volumeChange} />}
          </span>
        }
      />
      <StatListItem label="거래대금" value={num(q ? formatCompactKRW(q.tradingValue) : NO_VALUE)} />
      <StatListItem
        label="외국인 보유"
        value={num(renderValue(m?.foreignOwnership ?? null, formatRatio))}
      />
      <StatListItem
        label={
          <>
            기관 순매수{' '}
            <InfoTip description="종목별 기관 순매수 데이터는 아직 연동되지 않았습니다." />
          </>
        }
        value={<span className="text-sm font-semibold text-neutral-600">준비중</span>}
      />
    </StatList>
  );
}
