import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, ErrorBox } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { SplitLayout } from '@/components/layout/PageShell';
import type { PricePeriod } from '@/lib/types';
import { useStockDetail } from './useStockDetail';
import { useStockFinancials } from './useStockFinancials';
import { useWatchlistToggle } from './useWatchlistToggle';
import { LoginModal } from '@/features/auth/LoginModal';
import { StockHeader, StockHeaderSkeleton } from './components/StockHeader';
import { WatchlistToggleButton } from './components/WatchlistToggleButton';
import { PriceActionSection } from './components/PriceActionSection';
import { AtAGlanceCard } from './components/AtAGlanceCard';
import { StockInsightSection } from './components/StockInsightSection';

export function StockBriefingPage() {
  const { code } = useParams();
  const navigate = useNavigate();
  const [period, setPeriod] = useState<PricePeriod>('1Y');
  const {
    overview,
    overviewError,
    prices,
    priceError,
    retryOverview,
    retryPrices,
    loadEarlier,
    canLoadEarlier,
  } = useStockDetail(code, period);
  const {
    data: financials,
    error: financialsError,
    retry: retryFinancials,
  } = useStockFinancials(code);
  const [loginOpen, setLoginOpen] = useState(false);
  const watchlistToggle = useWatchlistToggle(code, () => setLoginOpen(true));

  if (overviewError instanceof ApiError && overviewError.code === 'STOCK_NOT_FOUND')
    return (
      <ErrorBox
        title="지금은 해당 종목을 서비스하지 않습니다"
        description="개별 종목 목록에서 제공 중인 종목을 확인해주세요"
        action={
          <Button variant="secondary" onClick={() => navigate('/stocks')}>
            종목 목록으로
          </Button>
        }
      />
    );
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
      <StockHeader
        stock={overview.stock}
        quote={overview.quote}
        watchlistAction={
          <WatchlistToggleButton
            watched={watchlistToggle.watched}
            disabled={!watchlistToggle.ready || watchlistToggle.pending}
            onToggle={watchlistToggle.toggle}
          />
        }
      />
      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
      <SplitLayout
        align="stretch"
        main={
          <PriceActionSection
            key={code}
            period={period}
            onLoadEarlier={loadEarlier}
            canLoadEarlier={canLoadEarlier}
            prices={prices}
            error={priceError}
            onRetry={retryPrices}
            onPeriodChange={setPeriod}
          />
        }
        side={
          <AtAGlanceCard
            quote={overview.quote}
            metrics={overview.metrics}
            financials={financials}
            financialsError={financialsError}
            onRetryFinancials={retryFinancials}
          />
        }
      />
      <StockInsightSection
        quote={overview.quote}
        metrics={overview.metrics}
        financials={financials}
        financialsError={financialsError}
        onRetryFinancials={retryFinancials}
      />
    </>
  );
}
