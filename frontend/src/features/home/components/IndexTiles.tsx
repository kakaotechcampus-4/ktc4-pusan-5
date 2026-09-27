import { Button, Change, Empty, ErrorBox, Skeleton } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatMarketValue } from '@/lib/format';
import type { MarketItem } from '@/lib/types';

const GRID = 'grid grid-cols-2 gap-2 sm:grid-cols-3';

export function IndexSection({
  loading,
  failed,
  items,
  onRetry,
}: {
  loading: boolean;
  failed: boolean;
  items: MarketItem[];
  onRetry: () => void;
}) {
  return (
    <section>
      <SectionHead title="주요 지수" />
      {loading && (
        <div className={GRID}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-25" />
          ))}
        </div>
      )}
      {failed && (
        <ErrorBox
          title="지수 정보를 갱신하지 못했습니다"
          description={
            items.length
              ? '마지막으로 받은 정보입니다. 잠시 후 다시 시도해주세요.'
              : '잠시 후 다시 시도해주세요.'
          }
          onRetry={onRetry}
        />
      )}
      {!loading && !failed && items.length === 0 && (
        <Empty
          title="아직 지수 정보가 없습니다"
          description="잠시 후 다시 확인해주세요."
          action={<Button onClick={onRetry}>다시 확인</Button>}
        />
      )}
      {items.length > 0 && (
        <div className={GRID}>
          {items.map((item) => (
            <IndexTile key={item.code} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}

function IndexTile({ item }: { item: MarketItem }) {
  return (
    <div className="bg-surface flex flex-col gap-1 rounded-md p-3">
      <div className="text-kicker tracking-kicker font-semibold text-neutral-600">{item.name}</div>
      <div className="num text-h2 font-bold">
        {item.value !== null ? formatMarketValue(item.value, item.unit) : '—'}
      </div>
      {item.change !== null && <Change value={item.change} display="arrow" />}
      {item.status === 'stale' && (
        <p role="status" className="text-xs text-neutral-700">
          갱신 지연 · 마지막 정상값
        </p>
      )}
      {item.value === null && (
        <p role="status" className="text-xs text-neutral-600">
          {item.status === 'notConfigured'
            ? '제공 준비 중'
            : item.status === 'unavailable'
              ? '수집 지연 · 잠시 후 자동 갱신됩니다'
              : '첫 데이터 수집 중'}
        </p>
      )}
    </div>
  );
}
