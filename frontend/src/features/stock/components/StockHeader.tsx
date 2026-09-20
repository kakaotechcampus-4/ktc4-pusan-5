import { Change, Kicker, Tag, SkeletonText, Skeleton } from '@/components/ui';
import { formatPrice, formatQuoteTimestamp } from '@/lib/format';
import type { Resource, StockIdentity, StockQuoteData } from '@/lib/types';

export function StockHeaderSkeleton() {
  return (
    <section className="flex flex-col gap-3">
      <Skeleton className="h-4 w-20" />
      <Skeleton className="h-8 w-48" />
      <SkeletonText lines={1} />
    </section>
  );
}

export function StockHeader({
  stock,
  quote,
}: {
  stock: StockIdentity;
  quote: Resource<StockQuoteData> | null;
}) {
  const data = quote?.data;
  const timestamp = quote?.sourceAsOf ?? quote?.collectedAt;
  const timestampLabel = quote?.sourceAsOf ? '시세 기준' : '수집 시각';
  return (
    <section>
      <Kicker>종목 브리핑</Kicker>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-h1">{stock.name}</h1>
        <Tag>{stock.code}</Tag>
      </div>
      <div className="mt-2 flex items-baseline gap-3">
        {data ? (
          <span className="num text-h1 font-bold">{formatPrice(data.price)}</span>
        ) : quote?.status === 'unavailable' ? (
          <span className="num text-h1">—</span>
        ) : (
          <Skeleton className="h-8 w-28" />
        )}
        {data && <Change value={data.changeAmount} unit="price" size="base" />}
        {data && <Change value={data.change} size="base" />}
      </div>
      {quote?.status === 'stale' && <Tag>이전 시세</Tag>}
      {quote?.status === 'unavailable' && (
        <p role="status" className="text-sm text-neutral-600">
          현재 시세를 가져오지 못했습니다.
        </p>
      )}
      {data && timestamp && (
        <p className="text-xs text-neutral-600">
          {timestampLabel} · <time dateTime={timestamp}>{formatQuoteTimestamp(timestamp)}</time>{' '}
          (KST)
        </p>
      )}
    </section>
  );
}
