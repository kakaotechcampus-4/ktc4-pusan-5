import { Change, Kicker, Tag, SkeletonText, Skeleton } from '@/components/ui';
import { formatAsOf, formatPrice } from '@/lib/format';
import type { StockQuote } from '../mock';

export function StockHeaderSkeleton() {
  return (
    <section className="flex flex-col gap-3">
      <Skeleton className="h-4 w-20" />
      <Skeleton className="h-8 w-48" />
      <SkeletonText lines={1} />
    </section>
  );
}

export function StockHeader({ stock }: { stock: StockQuote }) {
  return (
    <section>
      <Kicker>종목 브리핑</Kicker>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-h1">{stock.name}</h1>
        <Tag>{stock.code}</Tag>
      </div>
      <div className="mt-2 flex items-baseline gap-3">
        <span className="num text-h1 font-bold">{formatPrice(stock.price)}</span>
        <Change value={stock.changeAmount} unit="price" size="base" />
        <Change value={stock.change} size="base" />
      </div>
      <p className="text-sm text-neutral-600">{formatAsOf(new Date(stock.asOf))}</p>
    </section>
  );
}
