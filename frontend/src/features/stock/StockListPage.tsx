import { Link } from 'react-router-dom';
import { Empty, ErrorBox, Select, Skeleton } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatAsOf } from '@/lib/format';
import type { MockStockListItem } from './mockStockList';
import { useStockList, type StockSortKey } from './useStockList';

/**
 * 서비스 대상 종목을 리스트로 나열하고, 클릭하면 종목 브리핑으로 이동한다.
 * 정렬·로딩 상태는 useStockList, 여기는 상태별 렌더링만 한다.
 */

const SORT_OPTIONS: { value: StockSortKey; label: string }[] = [
  { value: 'marketCap', label: '시가총액순' },
  { value: 'name', label: '가나다순' },
];

const SKELETON_ROW_COUNT = 8;

const RANK_GROUP_SIZE = 10;

const LIST_CLASS = 'list-disc space-y-2 pl-6 text-h3 marker:text-neutral-500';

export function StockListPage() {
  const { status, asOf, items, sortKey, setSortKey, retry } = useStockList();

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

      {status === 'success' && asOf && sortKey === 'marketCap' && (
        <p className="num text-sm text-neutral-600">
          {formatAsOf(new Date(asOf), '시가총액 기준')}
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

type RankGroup = { title: string; items: MockStockListItem[] };

/** 시가총액 순위로 정렬된 목록을 10위 단위 구간(1~10위, 11~20위 …)으로 끊는다 */
function groupByRankRange(items: MockStockListItem[]): RankGroup[] {
  const groups = new Map<number, RankGroup>();
  for (const item of items) {
    const groupIndex = Math.floor((item.marketCapRank - 1) / RANK_GROUP_SIZE);
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

function StockListItems({ items }: { items: MockStockListItem[] }) {
  return (
    <ul className={LIST_CLASS}>
      {items.map((item) => (
        <li key={item.name}>
          <StockListRow item={item} />
        </li>
      ))}
    </ul>
  );
}

/** 코드가 있는 종목만 상세로 연결한다. 코드는 GET /api/stocks 연동 후 채워진다. */
function StockListRow({ item }: { item: MockStockListItem }) {
  if (!item.code) {
    return <span className="text-neutral-500">{item.name}</span>;
  }
  return (
    <Link to={`/stock/${item.code}`} className="text-ink hover:text-brand no-underline">
      <span className="font-semibold">{item.name}</span>
      <span className="num text-neutral-600">({item.code})</span>
    </Link>
  );
}

function StockListSkeleton() {
  return (
    <ul className={LIST_CLASS}>
      {Array.from({ length: SKELETON_ROW_COUNT }).map((_, index) => (
        <li key={index}>
          <Skeleton className="h-5 w-40" />
        </li>
      ))}
    </ul>
  );
}
