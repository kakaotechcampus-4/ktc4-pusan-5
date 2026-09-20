import { useParams } from 'react-router-dom';
import { ErrorBox } from '@/components/ui';
import { SplitLayout } from '@/components/layout/PageShell';
import { mockPriceHistory, mockStockDetails, mockStocks } from './mock';
import { useMockStockStatus } from './useStockDetail';
import { StockHeader, StockHeaderSkeleton } from './components/StockHeader';
import { PriceActionSection } from './components/PriceActionSection';
import { AtAGlanceCard } from './components/AtAGlanceCard';
import { StockInsightSection } from './components/StockInsightSection';

/** 종목 상세 페이지. 화면 조립만 담당한다 — 로딩 상태 시뮬레이션은 useStockDetail이 맡는다. */
export function StockBriefingPage() {
  const { code } = useParams();
  const stockStatus = useMockStockStatus(code);

  if (stockStatus === 'loading') {
    return <StockHeaderSkeleton />;
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

  // stockStatus === 'success' 는 useMockStockStatus 가 code를 mockStocks에서 찾았을 때만 나옴
  const stock = mockStocks[code!];
  const detail = mockStockDetails[code!];
  const history = mockPriceHistory[code!];

  return (
    <>
      <StockHeader stock={stock} />

      <SplitLayout
        align="stretch"
        main={<PriceActionSection history={history} />}
        side={<AtAGlanceCard stock={stock} detail={detail} />}
      />

      <StockInsightSection detail={detail} code={code} />
    </>
  );
}
