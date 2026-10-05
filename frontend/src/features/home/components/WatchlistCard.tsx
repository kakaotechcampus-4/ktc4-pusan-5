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
import type { WatchlistEntry } from '@/lib/types';

/** 관심 종목은 사용자가 직접 담는 목록이라 빈 상태가 실제로 존재한다. */
export type WatchlistStatus = 'loading' | 'error' | 'empty' | 'success' | 'unauthenticated';

export function WatchlistCard({
  status,
  items,
  onRetry,
  onLoginClick,
  onAddClick,
}: {
  status: WatchlistStatus;
  items: WatchlistEntry[];
  onRetry: () => void;
  onLoginClick: () => void;
  onAddClick: () => void;
}) {
  // 종목마다 시세 시각이 다를 수 있어 가장 최근 값을 기준 시각으로 보여준다.
  const latestAsOf = items
    .map((item) => item.asOf)
    .filter((asOf): asOf is string => asOf !== null)
    .sort()
    .at(-1);

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

      {status === 'unauthenticated' && (
        <Empty
          title="로그인하면 관심 종목을 볼 수 있습니다"
          description="관심 종목을 담아두고 시세를 한눈에 확인하세요"
          action={
            <Button variant="secondary" onClick={onLoginClick}>
              로그인
            </Button>
          }
        />
      )}

      {status === 'empty' && (
        <Empty
          title="아직 관심 종목이 없습니다"
          description="검색한 종목의 상세 화면에서 ☆를 눌러 추가해보세요"
          action={
            <Button variant="secondary" onClick={onAddClick}>
              ＋ 종목 추가
            </Button>
          }
        />
      )}

      {status === 'success' && (
        <>
          <ul className="flex list-none flex-col">
            {items.map((item) => (
              <li key={item.code}>
                <Link
                  to={`/stock/${item.code}`}
                  className="border-divider text-ink flex items-center gap-2 border-t py-2 no-underline hover:opacity-70"
                >
                  <StockAvatar initial={item.name.charAt(0)} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.name}</span>
                  {/* 패널 폭이 348px 이라 자리가 넉넉하다. 숫자를 이름과 같은 13px 로 맞춘다.
                      xs(11.5px)로 두면 시세를 읽으러 온 화면인데 시세가 제일 작아진다. */}
                  {item.quote ? (
                    <span className="flex flex-none flex-col items-end">
                      <span className="num text-sm font-semibold">
                        {formatPrice(item.quote.price)}
                      </span>
                      <Change value={item.quote.change} size="sm" />
                    </span>
                  ) : (
                    <span className="flex-none text-sm text-neutral-600">미제공</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>

          {/* 판단: 종목은 검색으로 골라 상세 화면에서 담는다. 그래서 이 버튼은 홈 검색창으로 안내한다. */}
          <Button variant="secondary" block onClick={onAddClick}>
            ＋ 종목 추가
          </Button>

          {latestAsOf && (
            <p className="text-xs text-neutral-600">{formatAsOf(new Date(latestAsOf))}</p>
          )}
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
