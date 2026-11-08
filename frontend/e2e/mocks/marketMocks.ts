/**
 * GET /api/market/overview 목업. 숫자는 가공하지 않은 원본 값이다. (루트 CLAUDE.md API 규약)
 * 이름에 "목업"을 넣어 실제 데이터와 화면에서 구분되게 한다.
 */
import type {
  FlowBoard,
  MarketItem,
  MarketOverview,
  RankingBoard,
  RankingItem,
  RankingKind,
  SectorBoard,
} from '../../src/lib/types';
import { mergeDeep, type DeepPartial } from './deepMerge';
import { mockAsOf, mockCollectedAt, mockPrimaryStock, mockSecondaryStock } from './sharedMocks';

/**
 * 보드 종류를 빠짐없이 적었는지 컴파일러가 검사하도록 Record 로 둔다.
 * src/lib/types.ts 에 종류가 늘면 여기서 컴파일 에러가 난다.
 */
const mockRankingKinds = {
  tradingValue: true,
  volume: true,
  gainers: true,
  losers: true,
} satisfies Record<RankingKind, true>;
const mockFlowKinds = { flowBuy: true, flowSell: true } satisfies Record<FlowBoard['kind'], true>;
const mockSectorKinds = { sectorKospi: true, sectorKosdaq: true } satisfies Record<
  SectorBoard['kind'],
  true
>;

function kindsOf<TKind extends string>(kinds: Record<TKind, true>): TKind[] {
  return Object.keys(kinds) as TKind[];
}

function mockMarketItems(): MarketItem[] {
  const base = {
    source: 'mock',
    status: 'ready',
    asOf: mockAsOf,
    collectedAt: mockCollectedAt,
  } as const;
  return [
    { ...base, code: 'KOSPI', name: '목업 코스피', unit: 'points', value: 2650.12, change: 0.85 },
    { ...base, code: 'KOSDAQ', name: '목업 코스닥', unit: 'points', value: 842.3, change: -0.42 },
    { ...base, code: 'USDKRW', name: '목업 원/달러', unit: 'KRW/USD', value: 1385.5, change: 0 },
  ];
}

function mockRankingItems(): RankingItem[] {
  return [
    {
      rank: 1,
      code: mockPrimaryStock.code,
      name: mockPrimaryStock.name,
      price: 62400,
      change: -1.08,
      volume: 14203000,
      tradingValue: 886267200000,
    },
    {
      rank: 2,
      code: mockSecondaryStock.code,
      name: mockSecondaryStock.name,
      price: 328500,
      change: 2.31,
      volume: 892000,
      tradingValue: 293022000000,
    },
  ];
}

function mockRankingBoard(kind: RankingKind): RankingBoard {
  return {
    kind,
    source: 'mock',
    status: 'ready',
    collectedAt: mockCollectedAt,
    items: mockRankingItems(),
  };
}

function mockFlowBoard(kind: FlowBoard['kind']): FlowBoard {
  const sign = kind === 'flowBuy' ? 1 : -1;
  return {
    kind,
    status: 'ready',
    source: 'mock',
    collectedAt: mockCollectedAt,
    items: [
      { code: mockPrimaryStock.code, name: mockPrimaryStock.name, netVolume: sign * 3332528 },
      { code: mockSecondaryStock.code, name: mockSecondaryStock.name, netVolume: sign * 120400 },
    ],
  };
}

function mockSectorBoard(kind: SectorBoard['kind']): SectorBoard {
  return {
    kind,
    status: 'ready',
    source: 'mock',
    collectedAt: mockCollectedAt,
    items: [
      { name: '목업 반도체 업종', change: 1.52, asOf: mockAsOf },
      { name: '목업 화학 업종', change: -0.37, asOf: mockAsOf },
    ],
  };
}

export function mockMarketOverview(overrides?: DeepPartial<MarketOverview>): MarketOverview {
  return mergeDeep<MarketOverview>(
    {
      items: mockMarketItems(),
      rankings: kindsOf(mockRankingKinds).map(mockRankingBoard),
      flows: kindsOf(mockFlowKinds).map(mockFlowBoard),
      sectors: kindsOf(mockSectorKinds).map(mockSectorBoard),
    },
    overrides,
  );
}
