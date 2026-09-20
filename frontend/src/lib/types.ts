export type User = {
  id: number;
  nickname: string;
  email: string;
};

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
  };
};

export type MarketItem = {
  code: string;
  name: string;
  source: string | null;
  unit: 'points' | 'KRW/USD' | null;
  status: 'ready' | 'stale' | 'unavailable' | 'pending' | 'notConfigured';
  value: number | null;
  change: number | null;
  asOf: string | null;
  collectedAt: string | null;
};
export type RankingKind = 'tradingValue' | 'volume' | 'gainers' | 'losers';
export type RankingItem = {
  rank: number;
  code: string;
  name: string;
  price: number;
  change: number;
  volume: number;
  tradingValue: number | null;
};
export type RankingBoard = {
  kind: RankingKind;
  source: string;
  status: 'ready' | 'stale' | 'empty' | 'pending' | 'unavailable' | 'notConfigured';
  collectedAt: string | null;
  items: RankingItem[];
};
export type FlowItem = { code: string; name: string; netVolume: number };
export type SectorItem = { name: string; change: number; asOf: string };
export type MarketBoard<T, K extends string> = {
  kind: K;
  status: 'ready' | 'stale' | 'empty' | 'pending' | 'unavailable';
  source: string;
  collectedAt: string | null;
  items: T[];
};
export type FlowBoard = MarketBoard<FlowItem, 'flowBuy' | 'flowSell'>;
export type SectorBoard = MarketBoard<SectorItem, 'sectorKospi' | 'sectorKosdaq'>;
export type MarketOverview = {
  items: MarketItem[];
  rankings: RankingBoard[];
  flows: FlowBoard[];
  sectors: SectorBoard[];
};
