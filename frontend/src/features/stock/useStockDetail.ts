import { useEffect, useState } from 'react';
import { mockStocks } from './mock';
import type { AiReportStatus } from './components/AiReportSection';

type StockStatus = 'loading' | 'error' | 'success';

/**
 * 판단: 실제 fetch가 없어서 타이머로 상태 전이를 흉내낸다.
 * 실제 연동 시 이 useEffect 두 개를 lib/api.ts 호출로 바꾸면 StockBriefingPage의 렌더 분기는 그대로 쓸 수 있다.
 * 시세는 empty가 없다 — 종목을 못 찾는 경우는 STOCK_NOT_FOUND 에러로 처리하기로 했다(리포트와 다름).
 * mockStocks 에 없는 code 로 들어오면 "못 찾은 경우"로 인지하고 에러로 취급함.
 * error 분기를 눈으로 보려면 존재하지 않는 code(/stock/000000)로 들어가서 확인 가능
 */
export function useMockStockStatus(code: string | undefined): StockStatus {
  const [status, setStatus] = useState<StockStatus>('loading');

  // code가 바뀌면(같은 페이지에서 다른 종목으로 이동) 렌더링 중에 곧바로 loading으로 되돌려짐
  // effect 안에서 setState를 동기 호출하면 안 된다는 lint 규칙 때문에, React 공식 문서가
  // 권장하는 "prop 변화에 맞춰 렌더링 중 state 조정하기" 패턴을 사용함
  const [trackedCode, setTrackedCode] = useState(code);
  if (code !== trackedCode) {
    setTrackedCode(code);
    setStatus('loading');
  }

  useEffect(() => {
    const timer = setTimeout(() => {
      setStatus(code && mockStocks[code] ? 'success' : 'error');
    }, 400);
    return () => clearTimeout(timer);
  }, [code]);
  return status;
}

export function useMockReportStatus(code: string | undefined): [AiReportStatus, () => void] {
  const [status, setStatus] = useState<AiReportStatus>('loading');
  const [attempt, setAttempt] = useState(0);

  const [trackedCode, setTrackedCode] = useState(code);
  if (code !== trackedCode) {
    setTrackedCode(code);
    setStatus('loading');
  }

  useEffect(() => {
    const timer = setTimeout(() => setStatus('success'), 900);
    return () => clearTimeout(timer);
  }, [code, attempt]);

  // retry : 로딩으로 되돌리고 attempt 를 올려 위 effect 를 다시 태운다.
  function retry() {
    setStatus('loading');
    setAttempt((n) => n + 1);
  }

  return [status, retry];
}
