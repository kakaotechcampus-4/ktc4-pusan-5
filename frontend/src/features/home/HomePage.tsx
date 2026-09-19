import { SplitLayout } from '@/components/layout/PageShell';
import {
  mockIndexBoard,
  mockInvestorFlow,
  mockMarketInsights,
  mockRankingPool,
  mockSectorRanks,
  mockSignalBoard,
  mockWatchlist,
} from './mock';
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

  return (
    <>
      <HomeHero
        asOf={sections.index.status === 'success' ? mockIndexBoard.asOf : undefined}
        loading={sections.index.status === 'loading'}
      />

      <IndexSection
        status={sections.index.status}
        indices={mockIndexBoard.indices}
        onRetry={sections.index.retry}
      />

      <SignalSection
        status={sections.signal.status}
        board={mockSignalBoard}
        onRetry={sections.signal.retry}
      />

      <SplitLayout
        main={
          <RankingSection
            status={sections.ranking.status}
            pool={mockRankingPool}
            onRetry={sections.ranking.retry}
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
        status={sections.flow.status}
        flow={mockInvestorFlow}
        sectors={mockSectorRanks}
        onRetry={sections.flow.retry}
      />

      <MarketInsightSection
        status={sections.insight.status}
        insights={mockMarketInsights}
        onRetry={sections.insight.retry}
      />
    </>
  );
}
