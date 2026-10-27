import { Link } from 'react-router-dom';
import { Button, Empty, ErrorBox } from '@/components/ui';
import { GuardrailNote } from '@/components/layout/GuardrailNote';
import type { MyScrap } from '../types';
import type { MyListStatus } from '../useMyScraps';
import { ScrapCard, ScrapCardSkeleton } from './ScrapCard';

const GRID_CLASS = 'grid list-none grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3';

export function ScrapTab({
  status,
  items,
  removedIds,
  onToggleRemoved,
  onRetry,
}: {
  status: MyListStatus;
  items: MyScrap[];
  removedIds: Set<string>;
  onToggleRemoved: (scrapId: string) => void;
  onRetry: () => void;
}) {
  if (status === 'error') {
    return (
      <ErrorBox
        title="스크랩한 AI 보고서를 불러오지 못했습니다"
        description="잠시 후 다시 시도해주세요"
        onRetry={onRetry}
      />
    );
  }

  if (status === 'empty') {
    return (
      <Empty
        title="아직 스크랩한 AI 보고서가 없습니다"
        description="종목 화면의 AI 보고서에서 북마크를 누르면 여기에 모입니다"
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

  return (
    <div className="flex flex-col gap-3">
      <GuardrailNote />
      {status === 'loading' ? (
        <ul className={GRID_CLASS} aria-busy>
          {Array.from({ length: 3 }).map((_, i) => (
            <ScrapCardSkeleton key={i} />
          ))}
        </ul>
      ) : (
        <>
          <p className="text-sm text-neutral-600">{items.length}개 · 최근 스크랩 순</p>
          <ul className={GRID_CLASS}>
            {items.map((scrap) => (
              <ScrapCard
                key={scrap.scrapId}
                scrap={scrap}
                removed={removedIds.has(scrap.scrapId)}
                onToggleRemoved={onToggleRemoved}
              />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
