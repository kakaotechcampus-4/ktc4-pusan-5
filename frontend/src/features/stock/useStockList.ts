import { useCallback, useEffect, useMemo, useState } from 'react';
import { mockStockList, type MockStockListItem } from './mockStockList';

/**
 * 종목 목록을 불러오고 정렬한다.
 * 판단: GET /api/stocks 가 준비되기 전까지는 mock 만 쓴다. 연동 시 loadStockList 만 바꾸면 된다.
 */
export type StockListStatus = 'loading' | 'error' | 'success';
export type StockSortKey = 'name' | 'marketCap';

const MOCK_DELAY_MS = 500;

function loadStockList(): Promise<MockStockListItem[]> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(mockStockList), MOCK_DELAY_MS);
  });
}

/** 가나다순은 한글 로케일 비교, 시가총액순은 백엔드가 준 순위(1이 가장 큼) 오름차순 */
function sortStockList(items: MockStockListItem[], sortKey: StockSortKey): MockStockListItem[] {
  const sorted = [...items];
  if (sortKey === 'name') {
    return sorted.sort((a, b) => a.name.localeCompare(b.name, 'ko'));
  }
  return sorted.sort((a, b) => a.marketCapRank - b.marketCapRank);
}

type StockListState = { status: StockListStatus; items: MockStockListItem[] };

const LOADING_STATE: StockListState = { status: 'loading', items: [] };

export function useStockList() {
  const [state, setState] = useState<StockListState>(LOADING_STATE);
  const [sortKey, setSortKey] = useState<StockSortKey>('marketCap');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // 응답이 늦게 도착한 뒤 언마운트되면 그 응답 버림
    let cancelled = false;

    loadStockList()
      .then((items) => {
        if (!cancelled) setState({ status: 'success', items });
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

  const sortedItems = useMemo(() => sortStockList(state.items, sortKey), [state.items, sortKey]);

  return { status: state.status, items: sortedItems, sortKey, setSortKey, retry };
}
