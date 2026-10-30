import { useEffect, useState } from 'react';
import { searchAll } from '@/lib/api';
import type { SearchConceptItem, SearchStockItem } from '@/lib/types';

export type SearchStatus = 'idle' | 'loading' | 'error' | 'success';

/** 종류별 최대 개수. 드롭다운이 넘치면 안에서 스크롤된다. */
const RESULT_LIMIT_PER_KIND = 20;

type SearchResult = {
  query: string;
  failed: boolean;
  stocks: SearchStockItem[];
  concepts: SearchConceptItem[];
};

/**
 * 입력이 멈춘 뒤(delayMs)에 한 번만 검색한다. 입력이 바뀌면 이전 요청은 취소한다.
 * 상태는 "지금 입력한 값에 대한 응답이 왔는가"로 계산해서, 이전 입력의 결과가 잠깐 보이지 않는다.
 */
export function useSearch(query: string, delayMs = 250) {
  const trimmed = query.trim();
  const [result, setResult] = useState<SearchResult | null>(null);

  useEffect(() => {
    if (!trimmed) return;

    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchAll(trimmed, controller.signal, RESULT_LIMIT_PER_KIND)
        .then((response) =>
          setResult({
            query: trimmed,
            failed: false,
            stocks: response.stocks,
            concepts: response.concepts,
          }),
        )
        .catch(() => {
          if (controller.signal.aborted) return;
          setResult({ query: trimmed, failed: true, stocks: [], concepts: [] });
        });
    }, delayMs);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, delayMs]);

  const answered = result !== null && result.query === trimmed;
  const status: SearchStatus = !trimmed
    ? 'idle'
    : !answered
      ? 'loading'
      : result.failed
        ? 'error'
        : 'success';

  return {
    status,
    stocks: answered ? result.stocks : [],
    concepts: answered ? result.concepts : [],
  };
}
