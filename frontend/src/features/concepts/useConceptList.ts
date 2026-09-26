import { useCallback, useEffect, useState } from 'react';
import { listConcepts } from '@/lib/api';
import { mockConceptList } from './mock';
import type { ConceptListItem } from './types';

/**
 * 개념 목록을 불러옴
 */
export type ConceptListStatus = 'loading' | 'error' | 'success';

export type ConceptListQuery = {
  status: ConceptListStatus;
  items: ConceptListItem[];
  retry: () => void;
};

/** 목업 모드에서만 mock.ts read, 기본은 실제 API */
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

const MOCK_DELAY_MS = 500;

function loadMockConceptList(): Promise<ConceptListItem[]> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(mockConceptList), MOCK_DELAY_MS);
  });
}

function loadConceptList(): Promise<ConceptListItem[]> {
  return USE_MOCK ? loadMockConceptList() : listConcepts().then((response) => response.items);
}

type ConceptListState = {
  status: ConceptListStatus;
  items: ConceptListItem[];
};

const LOADING_STATE: ConceptListState = { status: 'loading', items: [] };

export function useConceptList(): ConceptListQuery {
  const [state, setState] = useState<ConceptListState>(LOADING_STATE);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // 응답이 늦게 도착한 뒤 언마운트되면 그 응답 버림
    let cancelled = false;

    loadConceptList()
      .then((items) => {
        if (cancelled) return;
        setState({ status: 'success', items });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ status: 'error', items: [] });
      });

    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // retry: 로딩으로 되돌리고 attempt 를 올려 위 effect retry
  const retry = useCallback(() => {
    setState(LOADING_STATE);
    setAttempt((count) => count + 1);
  }, []);

  return { status: state.status, items: state.items, retry };
}
