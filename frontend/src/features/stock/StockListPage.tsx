import { Link } from 'react-router-dom';
import { Empty, ErrorBox, Select, Skeleton } from '@/components/ui';
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

const ROW_CLASS = 'flex items-baseline gap-1 px-4 py-3 text-sm';

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

      {status === 'loading' && <StockListSkeleton />}
      {status === 'success' && items.length === 0 && (
        <Empty
          title="아직 등록된 종목이 없습니다"
          description="종목이 추가되면 여기에서 확인할 수 있습니다"
        />
      )}
      {status === 'success' && items.length > 0 && (
        <ul className="border-divider divide-divider flex list-none flex-col divide-y rounded-lg border">
          {items.map((item) => (
            <li key={item.name}>
              <StockListRow item={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 코드가 있는 종목만 상세로 연결한다. 코드는 GET /api/stocks 연동 후 채워진다. */
function StockListRow({ item }: { item: MockStockListItem }) {
  if (!item.code) {
    return <div className={`${ROW_CLASS} text-neutral-500`}>{item.name}</div>;
  }
  return (
    <Link
      to={`/stock/${item.code}`}
      className={`${ROW_CLASS} text-ink no-underline hover:bg-neutral-100`}
    >
      <span className="font-semibold">{item.name}</span>
      <span className="num text-neutral-600">({item.code})</span>
    </Link>
  );
}

function StockListSkeleton() {
  return (
    <ul className="border-divider divide-divider flex list-none flex-col divide-y rounded-lg border">
      {Array.from({ length: SKELETON_ROW_COUNT }).map((_, index) => (
        <li key={index} className="px-4 py-3">
          <Skeleton className="h-5 w-40" />
        </li>
      ))}
    </ul>
  );
}
