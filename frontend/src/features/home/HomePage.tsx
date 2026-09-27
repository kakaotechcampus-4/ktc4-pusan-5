import { SplitLayout } from '@/components/layout/PageShell';
import { mockMarketInsights, mockSignalBoard, mockWatchlist } from './mock';
import { useMarketOverview } from './useMarketOverview';
import { useHomeSections } from './useHomeSections';
import { HomeHero } from './components/HomeHero';
import { IndexSection } from './components/IndexTiles';
import { SignalSection } from './components/SignalList';
import { WatchlistCard } from './components/WatchlistCard';
import { RankingSection } from './components/RankingSection';
import { MarketFlowSection } from './components/MarketFlowSection';
import { MarketInsightSection } from './components/MarketInsightSection';

/**
 * 홈 화면. 화면 조립만 담당한다.
 * 섹션별 로딩 상태 관리는 useHomeSections가, 그리는 일은 components/가 맡는다.
 */
export function HomePage() {
  const sections = useHomeSections();
  const market = useMarketOverview();

  return (
    <>
      <HomeHero />

      <IndexSection
        loading={market.loading}
        failed={market.failed}
        items={market.data?.items ?? []}
        onRetry={market.retry}
      />

      <SignalSection
        status={sections.signal.status}
        board={mockSignalBoard}
        onRetry={sections.signal.retry}
      />

      <SplitLayout
        main={
          <RankingSection
            loading={market.loading}
            failed={market.failed}
            rankings={market.data?.rankings ?? []}
            onRetry={market.retry}
          />
        }
        side={
          <WatchlistCard
            status={sections.watchlist.status}
            watchlist={mockWatchlist}
            onRetry={sections.watchlist.retry}
          />
        }
      />

      <MarketFlowSection
        loading={market.loading}
        failed={market.failed}
        flows={market.data?.flows ?? []}
        sectors={market.data?.sectors ?? []}
        onRetry={market.retry}
      />

      <MarketInsightSection
        status={sections.insight.status}
        insights={mockMarketInsights}
        onRetry={sections.insight.retry}
      />
    </>
  );
}
