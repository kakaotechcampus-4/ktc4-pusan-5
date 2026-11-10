import { Link } from 'react-router-dom';
import { Card, Change, Skeleton, SkeletonText, StockAvatar, Tag } from '@/components/ui';
import { cn } from '@/lib/cn';
import { formatAsOf, formatDate } from '@/lib/format';
import type { AvailableScrap, MyScrap, UnavailableScrap } from '../types';

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

function ScrapToggleButton({ removed, onClick }: { removed: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={removed ? '다시 스크랩' : '스크랩 해제'}
      onClick={onClick}
      className={cn(
        'relative z-10 inline-flex size-8 items-center justify-center rounded-md',
        'hover:bg-neutral-100',
        removed ? 'text-neutral-600' : 'text-brand',
      )}
    >
      <BookmarkIcon filled={!removed} />
    </button>
  );
}

/**
 * 카드 전체가 종목 이름 Link 하나의 stretched link 다. (a 안에 button 을 넣지 않는다)
 * 해제 버튼만 relative z-10 으로 링크 위에 올린다. 흐려진 카드도 링크는 동작한다.
 */
type ScrapCardProps<Scrap extends MyScrap> = {
  scrap: Scrap;
  removed: boolean;
  onToggleRemoved: (scrapId: string) => void;
};

export function ScrapCard({ scrap, removed, onToggleRemoved }: ScrapCardProps<MyScrap>) {
  if (!scrap.available) {
    return (
      <UnavailableScrapCard scrap={scrap} removed={removed} onToggleRemoved={onToggleRemoved} />
    );
  }
  return <AvailableScrapCard scrap={scrap} removed={removed} onToggleRemoved={onToggleRemoved} />;
}

/** 보고서를 읽을 수 없는 스크랩. 종목을 알 수 없어 링크 없이 안내와 해제 버튼만 둔다. */
function UnavailableScrapCard({
  scrap,
  removed,
  onToggleRemoved,
}: ScrapCardProps<UnavailableScrap>) {
  return (
    <li className={cn('grid', removed && 'opacity-50')}>
      <Card tone="plain">
        <p className="text-ink font-semibold">보고서를 찾을 수 없습니다</p>
        <p className="flex-1 text-sm text-neutral-700">
          보고서가 갱신되었거나 삭제되었습니다. 종목 화면에서 최신 보고서를 확인해보세요.
        </p>
        <div className="flex items-center justify-end gap-1 text-xs text-neutral-600">
          {formatDate(new Date(scrap.scrappedAt))} 스크랩
          <ScrapToggleButton removed={removed} onClick={() => onToggleRemoved(scrap.scrapId)} />
        </div>
      </Card>
    </li>
  );
}

function AvailableScrapCard({ scrap, removed, onToggleRemoved }: ScrapCardProps<AvailableScrap>) {
  const reportDate = new Date(scrap.asOf);

  return (
    <li className={cn('relative grid', removed && 'opacity-50')}>
      <Card tone="plain">
        <div className="flex items-center gap-2">
          <StockAvatar initial={(scrap.stockName ?? scrap.stockCode).slice(0, 1)} />
          <Link
            to={`/stock/${scrap.stockCode}`}
            aria-label={`${scrap.stockName ?? scrap.stockCode} ${formatDate(reportDate)} AI 보고서`}
            className="text-ink min-w-0 truncate font-semibold no-underline after:absolute after:inset-0"
          >
            {scrap.stockName ?? scrap.stockCode}
          </Link>
          <Tag tone="neutral">{scrap.stockCode}</Tag>
          {scrap.changePct !== null && (
            <span className="ml-auto flex-none">
              <Change value={scrap.changePct} display="arrow" />
            </span>
          )}
        </div>

        <p className="text-xs text-neutral-600">{formatAsOf(reportDate, '장 마감 기준 보고서')}</p>
        <p className="flex-1 text-sm text-neutral-700">{scrap.headline ?? ''}</p>

        <div className="flex items-end gap-2">
          <p className="min-w-0 flex-1 text-xs text-neutral-600">
            {scrap.generatedAt && `${formatDate(new Date(scrap.generatedAt))} 생성`}
            {scrap.sources.length > 0 && ` · 출처 ${scrap.sources.join(', ')}`}
          </p>
          <span className="flex flex-none items-center gap-1 text-xs text-neutral-600">
            {formatDate(new Date(scrap.scrappedAt))} 스크랩
            <ScrapToggleButton removed={removed} onClick={() => onToggleRemoved(scrap.scrapId)} />
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
