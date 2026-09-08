import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { ErrorBox } from '@/components/ui';
import { SplitLayout } from '@/components/layout/PageShell';
import { mockStock, mockBriefing } from './mock';
import { StockHeader, StockHeaderSkeleton } from './components/StockHeader';
import { StockStats, StockStatsSkeleton } from './components/StockStats';
import { BriefingSection, type BriefingStatus } from './components/BriefingSection';
import { ConceptChatPanel } from './components/ConceptChatPanel';

type StockStatus = 'loading' | 'error' | 'success';

// 판단: 실제 fetch가 없어서 타이머로 상태 전이를 흉내낸다.
// 실제 연동 시 이 useEffect 두 개를 lib/api.ts 호출로 바꾸면 아래 렌더 분기는 그대로 쓸 수 있다.
// 시세는 empty가 없다 — 종목을 못 찾는 경우는 STOCK_NOT_FOUND 에러로 처리하기로 했다(브리핑과 다름).
// error 분기를 눈으로 보려면 setTimeout 안의 'success'를 잠깐 'error'로 바꿔서 확인한다.
function useMockStockStatus(): StockStatus {
  const [status, setStatus] = useState<StockStatus>('loading');
  useEffect(() => {
    const timer = setTimeout(() => setStatus('success'), 400);
    return () => clearTimeout(timer);
  }, []);
  return status;
}

function useMockBriefingStatus(): [BriefingStatus, () => void] {
  const [status, setStatus] = useState<BriefingStatus>('loading');
  useEffect(() => {
    const timer = setTimeout(() => setStatus('success'), 900);
    return () => clearTimeout(timer);
  }, []);
  return [status, () => setStatus('loading')];
}

export function StockBriefingPage() {
  const { code } = useParams();
  const stockStatus = useMockStockStatus();
  const [briefingStatus, retryBriefing] = useMockBriefingStatus();

  if (stockStatus === 'loading') {
    return (
      <SplitLayout
        main={
          <>
            <StockHeaderSkeleton />
            <StockStatsSkeleton />
          </>
        }
        side={<ConceptChatPanel />}
      />
    );
  }

  if (stockStatus === 'error') {
    return (
      <ErrorBox
        title="시세를 불러오지 못했습니다"
        description="잠시 후 다시 시도해주세요"
        onRetry={() => window.location.reload()}
      />
    );
  }

  return (
    <SplitLayout
      main={
        <>
          <StockHeader stock={mockStock} code={code} />
          <StockStats stock={mockStock} />
          <BriefingSection
            status={briefingStatus}
            briefing={mockBriefing}
            onRetry={retryBriefing}
          />
        </>
      }
      side={<ConceptChatPanel />}
    />
  );
}
