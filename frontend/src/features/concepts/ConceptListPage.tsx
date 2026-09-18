import { useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Empty, ErrorBox, FilterChips, Skeleton } from '@/components/ui';
import { useConceptList } from './useConceptList';
import { ConceptCard, ConceptCardSkeleton } from './components/ConceptCard';
import type { ConceptListItem } from './types';

/**
 * 대분류 필터 + 개념 카드 그리드
 * 선택된 대분류는 URL 쿼리(`?domain=`)에 둬서 뒤로가기·공유 링크에서 복원
 */

/** '전체' 칩의 내부 값 */
const ALL_DOMAIN = 'all';

const SKELETON_CARD_COUNT = 6;

type DomainChip = { slug: string; name: string };

/** 목록에 실제로 등장하는 대분류만 필터링, 가나다 순 정렬 */
function collectDomainChips(items: ConceptListItem[]): DomainChip[] {
  const domainsBySlug = new Map<string, string>();
  for (const item of items) {
    const { slug, name } = item.category.domain;
    if (!domainsBySlug.has(slug)) domainsBySlug.set(slug, name);
  }
  return Array.from(domainsBySlug, ([slug, name]) => ({ slug, name })).sort((a, b) =>
    a.name.localeCompare(b.name, 'ko'),
  );
}

export function ConceptListPage() {
  const { status, items, retry } = useConceptList();
  const [searchParams, setSearchParams] = useSearchParams();
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

  const domainChips = collectDomainChips(items);

  // 값을 읽을 땐 getAll 의 첫 값만 쓴다. (나중에 다중 선택으로 넓혀도 기존 링크가 안 깨지게)
  // 목록에 없는 slug 가 오면 조용히 전체로 취급
  const requestedDomain: string = searchParams.getAll('domain')[0] ?? ALL_DOMAIN;
  const requestedDomainExists = domainChips.some((chip) => chip.slug === requestedDomain);
  const selectedDomain: string =
    requestedDomain === ALL_DOMAIN || requestedDomainExists ? requestedDomain : ALL_DOMAIN;

  function handleDomainChange(domain: string) {
    const nextParams = new URLSearchParams(searchParams);
    if (domain === ALL_DOMAIN) {
      nextParams.delete('domain');
    } else {
      nextParams.set('domain', domain);
    }
    // 칩 누를 때마다 뒤로가기 기록이 쌓이지 않게 replace
    setSearchParams(nextParams, { replace: true });
  }

  const visibleItems =
    selectedDomain === ALL_DOMAIN
      ? items
      : items.filter((item) => item.category.domain.slug === selectedDomain);

  return (
    <div className="flex flex-col gap-6">
      <PageHead />
      <FilterChips
        label="대분류"
        chips={[
          { value: ALL_DOMAIN, label: '전체' },
          ...domainChips.map((chip) => ({ value: chip.slug, label: chip.name })),
        ]}
        value={selectedDomain}
        onChange={handleDomainChange}
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
