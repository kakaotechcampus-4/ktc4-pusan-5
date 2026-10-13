import type { StockListItem } from '@/lib/types';

/**
 * 업종(sector) 필터. 칩은 응답의 sector 값으로 만들고, 별도 분류 표를 두지 않는다.
 */
export const ALL_SECTOR = '전체';

export type SectorChip = { value: string; label: string };

/** 종목 수 많은 순, 같으면 가나다순. 개수는 항상 전체 목록 기준이다. */
export function buildSectorChips(items: StockListItem[]): SectorChip[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    counts.set(item.sector, (counts.get(item.sector) ?? 0) + 1);
  }
  const sectorChips = [...counts.entries()]
    .sort(([nameA, countA], [nameB, countB]) => countB - countA || nameA.localeCompare(nameB, 'ko'))
    .map(([sector, count]) => ({ value: sector, label: `${sector} (${count})` }));
  return [{ value: ALL_SECTOR, label: `${ALL_SECTOR} (${items.length})` }, ...sectorChips];
}

export function filterBySector(items: StockListItem[], sector: string): StockListItem[] {
  if (sector === ALL_SECTOR) return items;
  return items.filter((item) => item.sector === sector);
}
