import type { StockListItem } from '@/lib/types';
import { ALL_SECTOR, buildSectorChips, filterBySector } from './stockSectorFilter';

function stock(rank: number, name: string, sector: string): StockListItem {
  return { rank, code: String(rank).padStart(6, '0'), name, market: 'KOSPI', sector };
}

const items = [
  stock(1, '삼성전자', '전기전자'),
  stock(2, '신한지주', '금융'),
  stock(3, 'SK하이닉스', '전기전자'),
  stock(4, '셀트리온', '제약'),
  stock(5, '유한양행', '제약'),
  stock(6, 'KB금융', '금융'),
  stock(7, 'LG전자', '전기전자'),
];

describe('buildSectorChips', () => {
  it('puts 전체 first with the total count', () => {
    expect(buildSectorChips(items)[0]).toEqual({ value: ALL_SECTOR, label: '전체 (7)' });
  });

  it('orders sectors by stock count, then by name', () => {
    expect(buildSectorChips(items).map((chip) => chip.label)).toEqual([
      '전체 (7)',
      '전기전자 (3)',
      '금융 (2)',
      '제약 (2)',
    ]);
  });

  it('returns only 전체 for an empty list', () => {
    expect(buildSectorChips([])).toEqual([{ value: ALL_SECTOR, label: '전체 (0)' }]);
  });
});

describe('filterBySector', () => {
  it('returns every item for 전체', () => {
    expect(filterBySector(items, ALL_SECTOR)).toHaveLength(7);
  });

  it('keeps only the selected sector and its order', () => {
    expect(filterBySector(items, '전기전자').map((item) => item.name)).toEqual([
      '삼성전자',
      'SK하이닉스',
      'LG전자',
    ]);
  });
});
