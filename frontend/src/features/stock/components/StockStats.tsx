import { Stat, StatGrid, Skeleton } from '@/components/ui';
import { formatCompactKRW, formatPrice } from '@/lib/format';
import type { StockQuote } from '../mock';

export function StockStatsSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-16" />
      ))}
    </div>
  );
}

export function StockStats({ stock }: { stock: StockQuote }) {
  return (
    <StatGrid>
      <Stat label="시가총액" value={formatCompactKRW(stock.marketCap)} />
      <Stat label="PER" value={stock.per} />
      <Stat label="PBR" value={stock.pbr} />
      <Stat label="거래량" value={formatPrice(stock.volume)} />
    </StatGrid>
  );
}
