import { Link } from 'react-router-dom';
import { Empty, ErrorBox, Select, Skeleton } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { cn } from '@/lib/cn';
import { formatAsOf } from '@/lib/format';
import type { StockListItem } from '@/lib/types';
import { mockStockListAsOf } from './mockStockList';
import { useStockList, type StockSortKey } from './useStockList';

/**
 * 서비스 대상 종목을 리스트로 나열하고, 클릭하면 종목 브리핑으로 이동한다.
 * 정렬·로딩 상태는 useStockList, 여기는 상태별 렌더링만 한다.
 */

const SORT_OPTIONS: { value: StockSortKey; label: string }[] = [
  { value: 'marketCap', label: '시가총액순' },
  { value: 'name', label: '가나다순' },
];

const SKELETON_ITEM_COUNT = 6;

const RANK_GROUP_SIZE = 10;

const GRID_CLASS = 'grid list-none gap-3 md:grid-cols-2 lg:grid-cols-3';

const ITEM_CLASS = cn(
  'flex min-h-16 items-center justify-between gap-3 rounded-md px-4 py-3',
  'border-divider text-ink border no-underline',
  'hover:border-brand hover:bg-brand-100',
);

export function StockListPage() {
  const { status, items, sortKey, setSortKey, retry } = useStockList();

  if (status === 'error') {
    return (
      <ErrorBox
        title="종목 목록을 불러오지 못했습니다"
        description="잠시 후 다시 시도해주세요"
        onRetry={retry}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-h1">개별 종목</h1>
          <p className="text-base text-neutral-700">종목을 골라 브리핑을 확인하세요.</p>
        </div>
        <Select
          id="stock-sort"
          label="정렬"
          options={SORT_OPTIONS}
          value={sortKey}
          onChange={setSortKey}
        />
      </div>

      {status === 'success' && sortKey === 'marketCap' && (
        <p className="num text-sm text-neutral-600">
          {formatAsOf(new Date(mockStockListAsOf), '시가총액 기준')}
        </p>
      )}
      {status === 'loading' && <StockListSkeleton />}
      {status === 'success' && items.length === 0 && (
        <Empty
          title="아직 등록된 종목이 없습니다"
          description="종목이 추가되면 여기에서 확인할 수 있습니다"
        />
      )}
      {status === 'success' && items.length > 0 && sortKey === 'marketCap' && (
        <div className="flex flex-col gap-8">
          {groupByRankRange(items).map((group) => (
            <section key={group.title}>
              <SectionHead title={group.title} tone="muted" />
              <StockListItems items={group.items} />
            </section>
          ))}
        </div>
      )}
      {status === 'success' && items.length > 0 && sortKey === 'name' && (
        <StockListItems items={items} />
      )}
    </div>
  );
}

type RankGroup = { title: string; items: StockListItem[] };

/** 시가총액 순위로 정렬된 목록을 10위 단위 구간(1~10위, 11~20위 …)으로 끊는다 */
function groupByRankRange(items: StockListItem[]): RankGroup[] {
  const groups = new Map<number, RankGroup>();
  for (const item of items) {
    const groupIndex = Math.floor((item.rank - 1) / RANK_GROUP_SIZE);
    const start = groupIndex * RANK_GROUP_SIZE + 1;
    const group = groups.get(groupIndex) ?? {
      title: `${start}~${start + RANK_GROUP_SIZE - 1}위`,
      items: [],
    };
    group.items.push(item);
    groups.set(groupIndex, group);
  }
  return [...groups.values()];
}

function StockListItems({ items }: { items: StockListItem[] }) {
  return (
    <ul className={GRID_CLASS}>
      {items.map((item) => (
        <li key={item.code}>
          <StockListCard item={item} />
        </li>
      ))}
    </ul>
  );
}

/** 클릭 가능한 카드형 항목. */
function StockListCard({ item }: { item: StockListItem }) {
  return (
    <Link to={`/stock/${item.code}`} className={ITEM_CLASS}>
      <span className="flex flex-col">
        <span className="text-base font-semibold">{item.name}</span>
        <span className="num text-sm text-neutral-600">{item.code}</span>
      </span>
      <span aria-hidden className="text-h3 text-neutral-500">
        ›
      </span>
    </Link>
  );
}

function StockListSkeleton() {
  return (
    <ul className={GRID_CLASS}>
      {Array.from({ length: SKELETON_ITEM_COUNT }).map((_, index) => (
        <li key={index}>
          <Skeleton className="h-16" />
        </li>
      ))}
    </ul>
  );
}
