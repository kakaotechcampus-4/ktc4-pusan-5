import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@/features/auth/useAuth';
import { addScrap, getMyScraps, removeScrap } from '@/lib/api';

/**
 * 종목 상세에서 지금 보는 보고서를 스크랩했는지 확인하고 스크랩/해제를 한다.
 * useWatchlistToggle 과 같은 규칙이다.
 *
 * scrapped 가 null 이면 아직 모른다(인증 확인 중, 목록 조회 중·실패).
 * 비로그인이면 스크랩하지 않은 것으로 보고, 누르면 onLoginRequired 를 부른다.
 * reportId 가 undefined 이면(보고서 없음) 버튼을 쓸 수 없다.
 */
export function useReportScrap(reportId: number | undefined, onLoginRequired: () => void) {
  const { status: authStatus } = useAuth();
  const [scrapped, setScrapped] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const currentId = useRef(reportId);
  useEffect(() => {
    currentId.current = reportId;
  }, [reportId]);

  useEffect(() => {
    if (reportId === undefined || authStatus !== 'authenticated') return;

    const controller = new AbortController();
    getMyScraps(controller.signal)
      .then((response) => setScrapped(response.items.some((item) => item.reportId === reportId)))
      .catch(() => {
        // 조회 실패 시 모르는 상태로 둔다. 잘못된 상태를 보여주는 것보다 누를 수 없게 막는다.
      });
    return () => {
      controller.abort();
      setScrapped(null);
      setPending(false);
    };
  }, [reportId, authStatus]);

  async function toggle() {
    if (reportId === undefined) return;
    if (authStatus === 'unauthenticated') {
      onLoginRequired();
      return;
    }
    if (scrapped === null || pending) return;

    const target = reportId;
    const next = !scrapped;
    setScrapped(next);
    setPending(true);
    try {
      await (next ? addScrap(target) : removeScrap(target));
    } catch {
      if (currentId.current === target) setScrapped(!next);
    } finally {
      if (currentId.current === target) setPending(false);
    }
  }

  const ready =
    reportId !== undefined &&
    (authStatus === 'unauthenticated' || (authStatus === 'authenticated' && scrapped !== null));
  return { scrapped: scrapped ?? false, ready, pending, toggle };
}

export type ReportScrapState = ReturnType<typeof useReportScrap>;
