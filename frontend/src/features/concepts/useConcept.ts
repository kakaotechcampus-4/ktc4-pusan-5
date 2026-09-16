import { useCallback, useEffect, useState } from 'react';
import { ApiError, getConcept } from '@/lib/api';
import { mockConcepts } from './mock';
import type { Concept } from './types';

/**
 * concept를 slug 로 불러옴
 * notFound는 error 와 분리
 */
export type ConceptStatus = 'loading' | 'error' | 'notFound' | 'success';

export type ConceptQuery = {
  status: ConceptStatus;
  concept: Concept | null;
  retry: () => void;
};

/** 목업 모드에서만 mock.ts read, 기본은 실제 API */
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

const MOCK_DELAY_MS = 500;

const NOT_FOUND_CODE = 'CONCEPT_NOT_FOUND';

function loadMockConcept(slug: string): Promise<Concept> {
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      const concept = mockConcepts[slug];
      if (concept) {
        resolve(concept);
        return;
      }
      reject(new ApiError(NOT_FOUND_CODE, '개념을 찾을 수 없습니다', 404));
    }, MOCK_DELAY_MS);
  });
}

function loadConcept(slug: string): Promise<Concept> {
  return USE_MOCK ? loadMockConcept(slug) : getConcept(slug);
}

type ConceptState = {
  status: ConceptStatus;
  concept: Concept | null;
};

const LOADING_STATE: ConceptState = { status: 'loading', concept: null };

export function useConcept(slug: string | undefined): ConceptQuery {
  const [state, setState] = useState<ConceptState>(LOADING_STATE);
  const [attempt, setAttempt] = useState(0);

  const [trackedSlug, setTrackedSlug] = useState(slug);
  if (slug !== trackedSlug) {
    setTrackedSlug(slug);
    setState(LOADING_STATE);
  }

  useEffect(() => {
    // slug 가 없으면 notFound
    if (!slug) return;

    // 응답이 늦게 도착한 뒤 다른 개념으로 이동해 있으면 그 응답 버림
    let cancelled = false;

    loadConcept(slug)
      .then((concept) => {
        if (cancelled) return;
        setState({ status: 'success', concept });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const notFound = error instanceof ApiError && error.code === NOT_FOUND_CODE;
        setState({ status: notFound ? 'notFound' : 'error', concept: null });
      });

    return () => {
      cancelled = true;
    };
  }, [slug, attempt]);

  // retry: 로딩으로 되돌리고 attempt 를 올려 위 effect retry
  const retry = useCallback(() => {
    setState(LOADING_STATE);
    setAttempt((count) => count + 1);
  }, []);

  // slug 가 비어 있는 건에 대해 notFound
  if (!slug) {
    return { status: 'notFound', concept: null, retry };
  }

  return { status: state.status, concept: state.concept, retry };
}
