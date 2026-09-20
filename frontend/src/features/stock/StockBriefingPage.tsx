import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { ErrorBox } from '@/components/ui';
import { SplitLayout } from '@/components/layout/PageShell';
import type { PricePeriod } from '@/lib/types';
import { useStockDetail } from './useStockDetail';
import { StockHeader, StockHeaderSkeleton } from './components/StockHeader';
import { PriceActionSection } from './components/PriceActionSection';
import { AtAGlanceCard } from './components/AtAGlanceCard';
import { StockInsightSection } from './components/StockInsightSection';

export function StockBriefingPage() {
  const { code } = useParams();
  const [period, setPeriod] = useState<PricePeriod>('1Y');
  const { overview, overviewError, prices, priceError, retryOverview, retryPrices } =
    useStockDetail(code, period);

  if (!code || (overviewError && !overview.stock))
    return (
      <ErrorBox
        title="종목을 불러오지 못했습니다"
        description={overviewError?.message ?? '종목 코드를 확인해주세요'}
        onRetry={retryOverview}
      />
    );
  if (!overview.stock) return <StockHeaderSkeleton />;

  return (
    <>
      {overviewError && (
        <ErrorBox
          title="시세 갱신에 실패했습니다"
          description="마지막으로 받은 데이터를 표시합니다."
          onRetry={retryOverview}
        />
      )}
      <StockHeader stock={overview.stock} quote={overview.quote} />
      <SplitLayout
        align="stretch"
        main={
          <PriceActionSection
            period={period}
            prices={prices}
            error={priceError}
            onRetry={retryPrices}
            onPeriodChange={setPeriod}
          />
        }
        side={<AtAGlanceCard quote={overview.quote} metrics={overview.metrics} />}
      />
      <StockInsightSection code={code} />
    </>
  );
}
