import { useCallback, useEffect, useMemo, useState } from 'react';
import { listStocks } from '@/lib/api';
import type { StockListItem, StockListResponse } from '@/lib/types';
import { mockStockList } from './mockStockList';
import { ALL_SECTOR, buildSectorChips, filterBySector } from './stockSectorFilter';

/**
 * 종목 목록을 불러오고 sector 값으로 카테고리화
 */
export type StockListStatus = 'loading' | 'error' | 'success';
export type StockSortKey = 'name' | 'marketCap';

/** 목업 모드에서만 mock.ts read, 기본은 실제 API */
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

const MOCK_DELAY_MS = 500;

function loadMockStockList(): Promise<StockListResponse> {
  return new Promise((resolve) => {
    setTimeout(() => resolve({ items: mockStockList, complete: true }), MOCK_DELAY_MS);
  });
}

function loadStockList(): Promise<StockListResponse> {
  return USE_MOCK ? loadMockStockList() : listStocks();
}

/** 가나다순은 한글 로케일 비교, 시가총액순은 백엔드가 준 순위(1이 가장 큼) 오름차순 */
function sortStockList(items: StockListItem[], sortKey: StockSortKey): StockListItem[] {
  const sorted = [...items];
  if (sortKey === 'name') {
    return sorted.sort((a, b) => a.name.localeCompare(b.name, 'ko'));
  }
  return sorted.sort((a, b) => a.rank - b.rank);
}

type StockListState = { status: StockListStatus; items: StockListItem[] };

const LOADING_STATE: StockListState = { status: 'loading', items: [] };

export function useStockList() {
  const [state, setState] = useState<StockListState>(LOADING_STATE);
  const [sortKey, setSortKey] = useState<StockSortKey>('marketCap');
  const [selectedSector, setSelectedSector] = useState(ALL_SECTOR);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // 응답이 늦게 도착한 뒤 언마운트되면 그 응답 버림
    let cancelled = false;

    loadStockList()
      .then(({ items, complete }) => {
        if (cancelled) return;
        setState({ status: 'success', items });
        if (!complete) {
          alert(
            '일부 종목 정보가 로딩되지 않았습니다. 새로고침해주세요.',
          );
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error', items: [] });
      });

    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setState(LOADING_STATE);
    setAttempt((count) => count + 1);
  }, []);

  const sectorChips = useMemo(() => buildSectorChips(state.items), [state.items]);

  // 다시 받은 목록에 선택한 업종이 없으면 전체로 보여준다
  const sector = sectorChips.some((chip) => chip.value === selectedSector)
    ? selectedSector
    : ALL_SECTOR;

  // 필터 → 정렬 순서. 정렬을 바꿔도 선택한 업종은 유지된다
  const visibleItems = useMemo(
    () => sortStockList(filterBySector(state.items, sector), sortKey),
    [state.items, sector, sortKey],
  );

  return {
    status: state.status,
    items: visibleItems,
    sortKey,
    setSortKey,
    sectorChips,
    sector,
    setSector: setSelectedSector,
    retry,
  };
}
