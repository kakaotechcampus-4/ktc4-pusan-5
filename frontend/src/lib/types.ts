export type User = {
  id: number;
  nickname: string;
  email: string;
};

export type ResourceStatus = 'pending' | 'ready' | 'stale' | 'unavailable' | 'empty';

export type Resource<T> = {
  status: ResourceStatus;
  refreshing: boolean;
  data: T | null;
  sourceAsOf: string | null;
  collectedAt: string | null;
  retryAfterSeconds: number | null;
};

export type StockIdentity = {
  code: string;
  name: string;
  market: 'KOSPI' | 'KOSDAQ';
  listingStatus: 'listed' | 'inactive';
  listedAt: string | null;
};

export type StockQuoteData = {
  price: number;
  change: number;
  changeAmount: number;
  volume: number;
  tradingValue: number;
  marketCap: number | null;
};

export type StockMetricsData = {
  per: number | null;
  pbr: number | null;
  eps: number | null;
  bps: number | null;
  foreignOwnership: number | null;
  week52High: number | null;
  week52Low: number | null;
};

export type Candle = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type PricePeriod = '1M' | '3M' | '1Y' | '5Y' | 'ALL';

export type StockPriceResource = Resource<Candle[]> & {
  code: string;
  period: PricePeriod;
  adjustment: 'raw';
  coverage: { fromDate: string; toDate: string; complete: boolean };
};

export type StockOverview = {
  stock: StockIdentity;
  quote: Resource<StockQuoteData>;
  metrics: Resource<StockMetricsData>;
};

export type FinancialIncomePoint = {
  fiscalPeriod: string;
  revenue: number | null;
  operatingProfit: number | null;
  netIncome: number | null;
};

export type FinancialEpsPoint = {
  fiscalPeriod: string;
  eps: number | null;
};

export type StockFinancials = {
  code: string;
  source: 'KIS';
  basis: 'provider';
  income: Resource<FinancialIncomePoint[]>;
  eps: Resource<FinancialEpsPoint[]>;
  health: Resource<FinancialHealthData>;
};

export type FinancialHealthData = {
  fiscalPeriod: string;
  debtRatio: number | null;
  roe: number | null;
  operatingMargin: number | null;
  currentRatio: number | null;
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
