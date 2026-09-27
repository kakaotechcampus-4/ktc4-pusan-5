import { Card, Empty, ErrorBox, Kicker, Skeleton, Tabs, Tag } from '@/components/ui';
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
  onLoadEarlier,
  canLoadEarlier,
}: {
  onLoadEarlier: () => void;
  canLoadEarlier: boolean;
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
      {prices?.refreshing && (
        <span className="sr-only" role="status">
          주가 데이터 불러오는 중
        </span>
      )}
      {prices?.status === 'stale' && !prices.refreshing && <Tag>이전 데이터</Tag>}
      {error && (
        <ErrorBox
          title="주가 차트를 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}
      {prices?.data?.length ? (
        <PriceVolumeChart
          key={period}
          candles={prices.data}
          onLoadEarlier={onLoadEarlier}
          canLoadEarlier={canLoadEarlier}
        />
      ) : !prices || prices.status === 'pending' ? (
        !error && <Skeleton className="h-80 w-full" />
      ) : prices.status === 'unavailable' ? (
        !error && (
          <ErrorBox
            title="주가 데이터를 준비하지 못했습니다"
            description="잠시 후 다시 확인해주세요"
            onRetry={onRetry}
          />
        )
      ) : (
        !error && (
          <Empty
            title="해당 기간의 주가 데이터가 없습니다"
            description="다른 기간을 선택해보세요"
          />
        )
      )}
    </Card>
  );
}
