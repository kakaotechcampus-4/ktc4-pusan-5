import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  Change,
  Empty,
  ErrorBox,
  Kicker,
  Skeleton,
  StockAvatar,
} from '@/components/ui';
import { formatAsOf, formatPrice } from '@/lib/format';
import type { Watchlist } from '../mock';

/** 관심 종목은 사용자가 직접 담는 목록이라 빈 상태가 실제로 존재한다. */
export type WatchlistStatus = 'loading' | 'error' | 'empty' | 'success';

export function WatchlistCard({
  status,
  watchlist,
  onRetry,
}: {
  status: WatchlistStatus;
  watchlist: Watchlist;
  onRetry: () => void;
}) {
  return (
    <Card>
      <div className="flex items-baseline gap-2">
        <Kicker>관심 종목</Kicker>
        <span className="text-kicker tracking-kicker ml-auto font-semibold text-neutral-600">
          KRW
        </span>
      </div>

      {status === 'loading' && <WatchlistSkeleton />}

      {status === 'error' && (
        <ErrorBox
          title="관심 종목을 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status === 'empty' && (
        <Empty
          title="아직 관심 종목이 없습니다"
          description="검색해서 추가해보세요"
          action={
            <Button variant="secondary" disabled>
              ＋ 종목 추가
            </Button>
          }
        />
      )}

      {status === 'success' && (
        <>
          <ul className="flex list-none flex-col">
            {watchlist.items.map((item) => (
              <li key={item.code}>
                <Link
                  to={`/stock/${item.code}`}
                  className="border-divider text-ink flex items-center gap-2 border-t py-2 no-underline hover:opacity-70"
                >
                  <StockAvatar initial={item.initial} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.name}</span>
                  {/* 패널 폭이 348px 이라 자리가 넉넉하다. 숫자를 이름과 같은 13px 로 맞춘다.
                      xs(11.5px)로 두면 시세를 읽으러 온 화면인데 시세가 제일 작아진다. */}
                  <span className="flex flex-none flex-col items-end">
                    <span className="num text-sm font-semibold">{formatPrice(item.price)}</span>
                    <Change value={item.change} size="sm" />
                  </span>
                </Link>
              </li>
            ))}
          </ul>

          {/* 판단: 종목을 담으려면 먼저 검색으로 골라야 하는데 그 검색이 아직 없다.
              누를 곳이 없는 버튼을 살려두면 더 헷갈려서 검색이 붙을 때까지 disabled 로 닫아둔다. */}
          <Button variant="secondary" block disabled>
            ＋ 종목 추가
          </Button>

          <p className="text-xs text-neutral-600">{formatAsOf(new Date(watchlist.asOf))}</p>
        </>
      )}
    </Card>
  );
}

export function WatchlistSkeleton() {
  return (
    <div className="flex flex-col">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="border-divider flex items-center gap-2 border-t py-2">
          <Skeleton className="size-6 flex-none" />
          <Skeleton className="h-4 flex-1" />
          {/* 실제 행의 숫자 두 줄(13px×2)과 높이를 맞춘다. 어긋나면 로딩이 끝날 때 목록이 튄다. */}
          <Skeleton className="h-10 w-20 flex-none" />
        </div>
      ))}
    </div>
  );
}
