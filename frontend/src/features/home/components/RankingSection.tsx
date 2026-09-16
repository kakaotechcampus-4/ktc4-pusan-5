import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Change, Empty, ErrorBox, Skeleton, StockAvatar, Tabs } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatPrice } from '@/lib/format';
import type { RankingItem } from '../mock';

export type RankingStatus = 'loading' | 'error' | 'empty' | 'success';

type RankingTab = 'tradingValue' | 'volume' | 'gainers' | 'losers';

const TABS: { value: RankingTab; label: string }[] = [
  { value: 'tradingValue', label: '거래대금' },
  { value: 'volume', label: '거래량' },
  { value: 'gainers', label: '등락률(상승)' },
  { value: 'losers', label: '등락률(하강)' },
];

/**
 * 탭마다 배열을 따로 들고 있지 않고, 풀 하나를 탭 기준으로 정렬해서 상위 10개만 나타냄
 * 정렬 기준이 늘어도(탭 추가) 이 함수만 늘리면 된다.
 */
function topTen(pool: RankingItem[], tab: RankingTab): RankingItem[] {
  const sorted = [...pool].sort((a, b) => {
    if (tab === 'tradingValue') return b.tradingValue - a.tradingValue;
    if (tab === 'volume') return b.volume - a.volume;
    if (tab === 'gainers') return b.change - a.change;
    return a.change - b.change;
  });
  return sorted.slice(0, 10);
}

export function RankingSection({
  status,
  pool,
  onRetry,
}: {
  status: RankingStatus;
  pool: RankingItem[];
  onRetry: () => void;
}) {
  const [tab, setTab] = useState<RankingTab>('tradingValue');

  return (
    <section className="flex flex-col gap-3">
      <SectionHead title="실시간 랭킹" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {status === 'loading' && <RankingSkeleton />}

      {status === 'error' && (
        <ErrorBox
          title="랭킹을 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status === 'empty' && (
        <Empty title="표시할 랭킹이 없습니다" description="잠시 후 다시 확인해주세요" />
      )}

      {status === 'success' && (
        <ol className="flex list-none flex-col">
          {topTen(pool, tab).map((item, i) => (
            <li key={item.code}>
              <Link
                to={`/stock/${item.code}`}
                className="border-divider text-ink flex items-center gap-3 border-b px-2 py-2.5 no-underline hover:bg-neutral-100"
              >
                <span className="num w-5 flex-none text-xs font-semibold text-neutral-500">
                  {i + 1}
                </span>
                <StockAvatar initial={item.initial} size="sm" />
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.name}</span>
                <span className="num w-20 flex-none text-right text-sm font-semibold">
                  {formatPrice(item.price)}
                </span>
                <span className="w-16 flex-none text-right">
                  <Change value={item.change} size="sm" />
                </span>
                <span className="num hidden w-24 flex-none text-right text-xs text-neutral-600 sm:block">
                  {formatPrice(item.volume)}주
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
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
