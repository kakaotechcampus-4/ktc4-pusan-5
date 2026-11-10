import { useEffect, useState } from 'react';
import { getReports } from '@/lib/api';
import type { ReportListItem } from '@/lib/types';

export type LatestReportsStatus = 'loading' | 'error' | 'success';

const LIMIT = 6;

/** 홈의 최신 보고서 목록. 로그인과 무관하고, 서버가 미리 만들어 둔 것을 읽기만 한다. */
export function useLatestReports() {
  const [status, setStatus] = useState<LatestReportsStatus>('loading');
  const [items, setItems] = useState<ReportListItem[]>([]);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getReports(LIMIT, controller.signal)
      .then((response) => {
        setItems(response.items);
        setStatus('success');
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setStatus('error');
      });
    return () => controller.abort();
  }, [attempt]);

  function retry() {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }

  return { status, items, retry };
}
