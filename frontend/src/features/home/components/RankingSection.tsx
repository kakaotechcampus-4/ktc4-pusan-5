import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Change, Empty, ErrorBox, Skeleton, StockAvatar, Tabs } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatCompactKRW, formatPrice } from '@/lib/format';
import type { RankingBoard, RankingItem, RankingKind } from '@/lib/types';

const TABS: { value: RankingKind; label: string }[] = [
  { value: 'tradingValue', label: '거래대금' },
  { value: 'volume', label: '거래량' },
  { value: 'gainers', label: '등락률(상승)' },
  { value: 'losers', label: '등락률(하락)' },
];

/** 탭별 서버 순위를 그대로 표시한다. 한 탭의 일부 종목을 다른 기준으로 재정렬하지 않는다. */
export function RankingSection({
  loading,
  failed,
  rankings,
  onRetry,
}: {
  loading: boolean;
  failed: boolean;
  rankings: RankingBoard[];
  onRetry: () => void;
}) {
  const [tab, setTab] = useState<RankingKind>('tradingValue');
  const board = rankings.find((ranking) => ranking.kind === tab);
  const notConfigured = board?.status === 'notConfigured';
  const items = board?.items ?? [];
  const unavailable = !notConfigured && (failed || board?.status === 'unavailable');
  const pending = !loading && !failed && (!board || board.status === 'pending');

  return (
    <section className="flex flex-col gap-3">
      <SectionHead title="실시간 랭킹" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {notConfigured ? (
        <Empty
          title="등락률 랭킹은 준비 중입니다"
          description="거래대금·거래량 탭을 이용해주세요."
        />
      ) : (
        <>
          {loading && <RankingSkeleton />}
          {unavailable && (
            <ErrorBox
              title="랭킹을 갱신하지 못했습니다"
              description={
                items.length
                  ? '마지막으로 받은 순위입니다. 잠시 후 다시 시도해주세요.'
                  : '잠시 후 다시 시도해주세요.'
              }
              onRetry={onRetry}
            />
          )}
          {!failed && board?.status === 'stale' && (
            <p role="status" className="text-sm text-neutral-700">
              갱신 지연 · 마지막으로 수집한 순위입니다.
            </p>
          )}
          {pending && (
            <Empty
              title="첫 랭킹을 수집 중입니다"
              description="잠시 후 자동으로 갱신됩니다."
              action={<Button onClick={onRetry}>다시 확인</Button>}
            />
          )}
          {!loading && !unavailable && !pending && items.length === 0 && (
            <Empty
              title="표시할 랭킹이 없습니다"
              description="거래가 없는 시간에는 순위가 비어 있을 수 있습니다."
              action={<Button onClick={onRetry}>다시 확인</Button>}
            />
          )}
          {items.length > 0 && <RankingList items={items} kind={tab} />}
        </>
      )}
    </section>
  );
}

function RankingList({ items, kind }: { items: RankingItem[]; kind: RankingKind }) {
  return (
    <ol className="flex list-none flex-col">
      {items.map((item) => (
        <li key={item.code}>
          <Link
            to={`/stock/${item.code}`}
            className="border-divider text-ink flex items-center gap-3 border-b px-2 py-2.5 no-underline hover:bg-neutral-100"
          >
            <span className="num w-5 flex-none text-xs font-semibold text-neutral-500">
              {item.rank}
            </span>
            <StockAvatar initial={item.name.slice(0, 1)} size="sm" />
            <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.name}</span>
            <span className="num w-20 flex-none text-right text-sm font-semibold">
              {formatPrice(item.price)}
            </span>
            <span className="w-16 flex-none text-right">
              <Change value={item.change} size="sm" />
            </span>
            <span className="num hidden w-24 flex-none text-right text-xs text-neutral-600 sm:block">
              {kind === 'tradingValue'
                ? item.tradingValue === null
                  ? '—'
                  : `${formatCompactKRW(item.tradingValue)}원`
                : `${formatPrice(item.volume)}주`}
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

function RankingSkeleton() {
  return (
    <div className="flex flex-col">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="border-divider flex items-center gap-3 border-b px-2 py-2.5">
          <Skeleton className="size-6 flex-none" />
          <Skeleton className="h-5 flex-1" />
          <Skeleton className="h-9 w-20 flex-none" />
        </div>
      ))}
    </div>
  );
}
