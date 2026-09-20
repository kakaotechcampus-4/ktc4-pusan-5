import { Card, Empty, ErrorBox, Kicker, Skeleton, Tabs } from '@/components/ui';
import { formatMarketDate } from '@/lib/format';
import type { PricePeriod, StockPriceResource } from '@/lib/types';
import { PriceVolumeChart } from './PriceVolumeChart';

const TABS: { value: PricePeriod; label: string }[] = [
  { value: '1M', label: '1개월' },
  { value: '3M', label: '3개월' },
  { value: '1Y', label: '1년' },
  { value: '5Y', label: '5년' },
  { value: 'ALL', label: '전체' },
];

export function PriceActionSection({
  period,
  prices,
  error,
  onRetry,
  onPeriodChange,
}: {
  period: PricePeriod;
  prices: StockPriceResource | null;
  error: Error | null;
  onRetry: () => void;
  onPeriodChange: (period: PricePeriod) => void;
}) {
  return (
    <Card tone="plain" className="flex-1">
      <Kicker>PRICE ACTION · 주가와 거래량</Kicker>
      <Tabs tabs={TABS} value={period} onChange={onPeriodChange} />
      {prices && (
        <p className="text-xs text-neutral-600">
          원주가 · {formatMarketDate(prices.coverage.fromDate)} ~{' '}
          {formatMarketDate(prices.coverage.toDate)}
        </p>
      )}
      {prices?.refreshing && (
        <p role="status" className="text-sm text-neutral-600">
          요청한 기간의 데이터를 수집 중입니다.
        </p>
      )}
      {prices?.status === 'stale' && !prices.refreshing && (
        <p role="status" className="text-sm text-neutral-600">
          갱신 지연 · 저장된 데이터를 표시합니다.
        </p>
      )}
      {error ? (
        <>
          {
            <ErrorBox
              title="주가 차트를 불러오지 못했습니다"
              description="저장된 마지막 데이터를 표시합니다"
              onRetry={onRetry}
            />
          }
          {prices?.data?.length ? <PriceVolumeChart candles={prices.data} /> : null}
        </>
      ) : !prices || (prices.status === 'pending' && !prices.data) ? (
        <Skeleton className="h-80 w-full" />
      ) : prices.status === 'unavailable' ? (
        <ErrorBox
          title="주가 데이터를 준비하지 못했습니다"
          description="잠시 후 다시 확인해주세요"
          onRetry={onRetry}
        />
      ) : prices.status === 'empty' || !prices.data?.length ? (
        <Empty title="해당 기간의 주가 데이터가 없습니다" description="다른 기간을 선택해보세요" />
      ) : (
        <PriceVolumeChart candles={prices.data} />
      )}
    </Card>
  );
}
