import { useNavigate } from 'react-router-dom';
import { Button, Empty, ErrorBox, FilterChips, Skeleton } from '@/components/ui';
import { useConceptList } from './useConceptList';
import { ALL_DOMAIN, useDomainFilter } from './useDomainFilter';
import { ConceptCard, ConceptCardSkeleton } from './components/ConceptCard';

/**
 * 대분류 필터 + 개념 카드 그리드
 * 필터 상태·파생 목록은 useDomainFilter, 여기는 상태별 렌더링만 한다
 */

const SKELETON_CARD_COUNT = 6;

export function ConceptListPage() {
  const { status, items, retry } = useConceptList();
  const { chips, selected, select, visibleItems } = useDomainFilter(items);
  const navigate = useNavigate();

  if (status === 'loading') {
    return <ConceptListSkeleton />;
  }

  if (status === 'error') {
    return (
      <ErrorBox
        title="개념 목록을 불러오지 못했습니다"
        description="잠시 후 다시 시도해주세요"
        onRetry={retry}
      />
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <PageHead />
        <Empty
          title="아직 등록된 개념이 없습니다"
          description="개념이 추가되면 여기에서 주제별로 찾아볼 수 있습니다"
          action={
            <Button variant="secondary" onClick={() => navigate('/')}>
              홈으로
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHead />
      <FilterChips
        label="대분류"
        chips={[
          { value: ALL_DOMAIN, label: '전체' },
          ...chips.map((chip) => ({ value: chip.slug, label: chip.name })),
        ]}
        value={selected}
        onChange={select}
      />
      <ul className="grid list-none gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleItems.map((item) => (
          <li key={item.slug}>
            <ConceptCard item={item} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function PageHead() {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-h1">개념</h1>
      <p className="text-base text-neutral-700">모르는 개념을 주제별로 골라 읽어보세요.</p>
    </div>
  );
}

function ConceptListSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-24" />
        <Skeleton className="h-5 w-72" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Skeleton className="h-9 w-16 rounded-full" />
        <Skeleton className="h-9 w-24 rounded-full" />
        <Skeleton className="h-9 w-24 rounded-full" />
      </div>
      <ul className="grid list-none gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: SKELETON_CARD_COUNT }).map((_, i) => (
          <li key={i}>
            <ConceptCardSkeleton />
          </li>
        ))}
      </ul>
    </div>
  );
}
