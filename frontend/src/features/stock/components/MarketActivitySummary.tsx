import { InfoTip, Skeleton, Stat, StatGrid } from '@/components/ui';
import { formatCompactKRW, formatPrice, formatRatio } from '@/lib/format';
import type { Resource, StockMetricsData, StockQuoteData } from '@/lib/types';

function renderValue(value: number | null | undefined, render: (value: number) => string) {
  return value === null || value === undefined ? '—' : render(value);
}

function StatSkeleton() {
  return (
    <StatGrid>
      {[1, 2, 3, 4, 5].map((key) => (
        <Skeleton key={key} className="h-16" />
      ))}
    </StatGrid>
  );
}

export function MarketActivitySummary({
  quote,
  metrics,
}: {
  quote: Resource<StockQuoteData> | null;
  metrics: Resource<StockMetricsData> | null;
}) {
  if (!quote && !metrics) return <StatSkeleton />;
  const q = quote?.data;
  const m = metrics?.data;
  return (
    <StatGrid>
      <Stat label="시가총액" value={renderValue(q?.marketCap, formatCompactKRW)} />
      <Stat
        label={
          <>
            거래량 <InfoTip description="전일 대비 거래량 변화율은 아직 연동되지 않았습니다." />
          </>
        }
        value={q ? `${formatPrice(q.volume)}주` : '—'}
      />
      <Stat label="거래대금" value={q ? formatCompactKRW(q.tradingValue) : '—'} />
      <Stat label="외국인 보유" value={renderValue(m?.foreignOwnership ?? null, formatRatio)} />
      <Stat
        label={
          <>
            기관 순매수{' '}
            <InfoTip description="종목별 기관 순매수 데이터는 아직 연동되지 않았습니다." />
          </>
        }
        value="준비중"
      />
    </StatGrid>
  );
}
