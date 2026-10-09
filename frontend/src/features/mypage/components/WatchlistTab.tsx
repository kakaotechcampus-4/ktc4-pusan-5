import { Link } from 'react-router-dom';
import { Button, Change, Empty, ErrorBox, Skeleton, StockAvatar } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatAsOf, formatPrice } from '@/lib/format';
import type { WatchlistEntry } from '@/lib/types';
import type { MyListStatus } from '../useMyScraps';

const SKELETON_ROW_COUNT = 6;

/** 이니셜은 백엔드가 주지 않는다. 영문 대문자로 시작하면 앞 두 글자(SK, LG), 아니면 첫 글자. */
function makeInitial(name: string): string {
  const latin = name.match(/^[A-Z]{2}/);
  return latin ? latin[0] : name.slice(0, 1);
}

function RemoveIcon({ removed }: { removed: boolean }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className="size-4"
      fill={removed ? 'none' : 'currentColor'}
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path
        strokeLinejoin="round"
        d="M8 2.2l1.8 3.7 4 .5-2.9 2.8.7 4L8 11.3l-3.6 1.9.7-4L2.2 6.4l4-.5z"
      />
    </svg>
  );
}

function WatchRow({
  item,
  removed,
  onToggleRemoved,
}: {
  item: WatchlistEntry;
  removed: boolean;
  onToggleRemoved: (code: string) => void;
}) {
  return (
    <li
      className={cn(
        'border-divider relative flex items-center gap-3 border-t py-2',
        removed && 'opacity-50',
      )}
    >
      <StockAvatar initial={makeInitial(item.name)} />
      <Link
        to={`/stock/${item.code}`}
        className="text-ink min-w-0 flex-1 truncate font-semibold no-underline after:absolute after:inset-0"
      >
        {item.name}
      </Link>
      {item.quote ? (
        <>
          <span className="flex flex-none flex-col items-end">
            <span className="num text-sm font-semibold">{formatPrice(item.quote.price)}</span>
            {/* 관심 종목은 상세 화면을 열어야 시세가 갱신돼서, 오래 안 본 종목은 값이 낡을 수 있다. */}
            {item.quoteStatus === 'stale' && (
              <span className="text-xs text-neutral-700">갱신 지연</span>
            )}
          </span>
          <span className="w-20 flex-none text-right">
            <Change value={item.quote.change} />
          </span>
        </>
      ) : (
        <span className="flex-none text-sm text-neutral-600">미제공</span>
      )}
      <button
        type="button"
        aria-label={removed ? '다시 담기' : '관심 해제'}
        onClick={() => onToggleRemoved(item.code)}
        className={cn(
          'relative z-10 inline-flex size-8 flex-none items-center justify-center rounded-md',
          'hover:bg-neutral-100',
          removed ? 'text-neutral-600' : 'text-brand',
        )}
      >
        <RemoveIcon removed={removed} />
      </button>
    </li>
  );
}

function WatchRowSkeleton() {
  return (
    <li className="border-divider flex items-center gap-3 border-t py-2">
      <Skeleton className="size-8 flex-none" />
      <Skeleton className="h-4 flex-1" />
      <Skeleton className="h-4 w-20 flex-none" />
      <Skeleton className="h-4 w-20 flex-none" />
      <Skeleton className="size-8 flex-none" />
    </li>
  );
}

export function WatchlistTab({
  status,
  items,
  removedIds,
  onToggleRemoved,
  onRetry,
}: {
  status: MyListStatus;
  items: WatchlistEntry[];
  removedIds: Set<string>;
  onToggleRemoved: (code: string) => void;
  onRetry: () => void;
}) {
  if (status === 'error') {
    return (
      <ErrorBox
        title="관심 종목을 불러오지 못했습니다"
        description="잠시 후 다시 시도해주세요"
        onRetry={onRetry}
      />
    );
  }

  if (status === 'empty') {
    return (
      <Empty
        title="아직 관심 종목이 없습니다"
        description="종목 화면에서 ☆를 누르면 여기에 모입니다"
        action={
          <Link to="/">
            <Button variant="secondary" tabIndex={-1}>
              홈에서 종목 둘러보기
            </Button>
          </Link>
        }
      />
    );
  }

  if (status === 'loading') {
    return (
      <ul className="flex list-none flex-col" aria-busy>
        {Array.from({ length: SKELETON_ROW_COUNT }).map((_, i) => (
          <WatchRowSkeleton key={i} />
        ))}
      </ul>
    );
  }

  // 종목마다 시세 시각이 다를 수 있어 가장 최근 값을 기준 시각으로 보여준다.
  const latestAsOf = items
    .map((item) => item.asOf)
    .filter((asOf): asOf is string => asOf !== null)
    .sort()
    .at(-1);

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex list-none flex-col">
        {items.map((item) => (
          <WatchRow
            key={item.code}
            item={item}
            removed={removedIds.has(item.code)}
            onToggleRemoved={onToggleRemoved}
          />
        ))}
      </ul>
      {latestAsOf && <p className="text-xs text-neutral-600">{formatAsOf(new Date(latestAsOf))}</p>}
    </div>
  );
}
