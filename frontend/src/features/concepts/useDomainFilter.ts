import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ConceptListItem } from './types';

/**
 * 개념 목록의 대분류 필터
 * 선택된 대분류는 URL 쿼리(`?domain=`)에 둬서 뒤로가기·공유 링크에서 복원
 */

/** '전체' 칩의 내부 값 */
export const ALL_DOMAIN = 'all';

export type DomainChip = { slug: string; name: string };

export type DomainFilter = {
  /** 목록에 실제 등장하는 대분류만, 가나다순. '전체' 칩은 포함하지 않음 (페이지가 앞에 붙임) */
  chips: DomainChip[];
  /** ALL_DOMAIN 또는 chips 에 있는 slug. URL 의 값이 목록에 없으면 ALL_DOMAIN */
  selected: string;
  /** URL 쿼리 갱신. ALL_DOMAIN 이면 param 삭제 */
  select: (domain: string) => void;
  visibleItems: ConceptListItem[];
};

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

export function useDomainFilter(items: ConceptListItem[]): DomainFilter {
  const [searchParams, setSearchParams] = useSearchParams();

  const chips = useMemo(() => collectDomainChips(items), [items]);

  // 값을 읽을 땐 getAll 의 첫 값만(나중에 다중 선택으로 넓혀도 기존 링크가 안 깨지게)
  // 목록에 없는 slug 가 오면 조용히 전체로 취급
  const requestedDomain = searchParams.getAll('domain')[0] ?? ALL_DOMAIN;
  const requestedDomainExists = chips.some((chip) => chip.slug === requestedDomain);
  const selected =
    requestedDomain === ALL_DOMAIN || requestedDomainExists ? requestedDomain : ALL_DOMAIN;

  const select = useCallback(
    (domain: string) => {
      const nextParams = new URLSearchParams(searchParams);
      if (domain === ALL_DOMAIN) {
        nextParams.delete('domain');
      } else {
        nextParams.set('domain', domain);
      }
      // 칩 누를 때마다 뒤로가기 기록이 쌓이지 않게 replace
      setSearchParams(nextParams, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const visibleItems = useMemo(
    () =>
      selected === ALL_DOMAIN
        ? items
        : items.filter((item) => item.category.domain.slug === selected),
    [items, selected],
  );

  return { chips, selected, select, visibleItems };
}
