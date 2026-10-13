import { Link } from 'react-router-dom';
import { Card, Change, Skeleton, SkeletonText, StockAvatar, Tag } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatAsOf, formatDate } from '@/lib/format';
import type { MyScrap } from '../types';

function BookmarkIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className="size-4"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="1.5"
    >
      <path strokeLinejoin="round" d="M4 2.5h8v11l-4-3-4 3z" />
    </svg>
  );
}

/**
 * 카드 전체가 종목 이름 Link 하나의 stretched link 다. (a 안에 button 을 넣지 않는다)
 * 해제 버튼만 relative z-10 으로 링크 위에 올린다. 흐려진 카드도 링크는 동작한다.
 */
export function ScrapCard({
  scrap,
  removed,
  onToggleRemoved,
}: {
  scrap: MyScrap;
  removed: boolean;
  onToggleRemoved: (scrapId: string) => void;
}) {
  const reportDate = new Date(scrap.asOf);

  return (
    <li className={cn('relative grid', removed && 'opacity-50')}>
      <Card tone="plain">
        <div className="flex items-center gap-2">
          <StockAvatar initial={scrap.stockName.slice(0, 1)} />
          <Link
            to={`/stock/${scrap.stockCode}?date=${scrap.targetDate}`}
            aria-label={`${scrap.stockName} ${formatDate(reportDate)} AI 보고서`}
            className="text-ink min-w-0 truncate font-semibold no-underline after:absolute after:inset-0"
          >
            {scrap.stockName}
          </Link>
          <Tag tone="neutral">{scrap.stockCode}</Tag>
          <span className="ml-auto flex-none">
            <Change value={scrap.changePct} display="arrow" />
          </span>
        </div>

        <p className="text-xs text-neutral-600">{formatAsOf(reportDate, '장 마감 기준 보고서')}</p>
        <p className="flex-1 text-sm text-neutral-700">{scrap.headline}</p>

        <div className="flex items-end gap-2">
          <p className="min-w-0 flex-1 text-xs text-neutral-600">
            {formatDate(new Date(scrap.generatedAt))} 생성 · 출처 {scrap.sources.join(', ')}
          </p>
          <span className="flex flex-none items-center gap-1 text-xs text-neutral-600">
            {formatDate(new Date(scrap.scrappedAt))} 스크랩
            <button
              type="button"
              aria-label={removed ? '다시 스크랩' : '스크랩 해제'}
              onClick={() => onToggleRemoved(scrap.scrapId)}
              className={cn(
                'relative z-10 inline-flex size-8 items-center justify-center rounded-md',
                'hover:bg-neutral-100',
                removed ? 'text-neutral-600' : 'text-brand',
              )}
            >
              <BookmarkIcon filled={!removed} />
            </button>
          </span>
        </div>
      </Card>
    </li>
  );
}

/** 실제 카드와 같은 구조·높이로 깐다. */
export function ScrapCardSkeleton() {
  return (
    <li className="grid">
      <Card tone="plain">
        <div className="flex items-center gap-2">
          <Skeleton className="size-8 flex-none" />
          <Skeleton className="h-5 w-24" />
          <Skeleton className="ml-auto h-5 w-16" />
        </div>
        <Skeleton className="h-4 w-48" />
        <SkeletonText lines={3} />
        <Skeleton className="h-8" />
      </Card>
    </li>
  );
}
