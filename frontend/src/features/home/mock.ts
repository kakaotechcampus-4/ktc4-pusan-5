/**
 * 홈 화면 목업 데이터.
 * 실제 API 붙일 때 이 파일 대신 lib/api.ts + lib/types.ts 를 쓴다.
 * 판단: lib/types.ts 는 아직 TODO(실제 연동 담당 몫)라 features/stock/mock.ts 와 같이
 *       feature 안 로컬 타입으로만 둔다.
 *
 * 숫자는 전부 가공하지 않은 원본이다. 포맷은 화면에서 lib/format.ts 로 한다.
 * (루트 CLAUDE.md 의 API 규약)
 */

/* ── 주요 지수 ──────────────────────────────────────────────────────────── */

export type MarketIndex = {
  name: string;
  value: number;
  /** 등락률(%) */
  change: number;
};

export type IndexBoard = {
  indices: MarketIndex[];
  asOf: string;
};

/* ── 개별 종목 시그널 ───────────────────────────────────────────────────── */

export type StockSignal = {
  code: string;
  name: string;
  /** 로고 배지에 넣는 이니셜. 백엔드가 주는 값이 아니라 프론트에서 정한다. */
  initial: string;
  price: number;
  /** 등락률(%) */
  change: number;
  /** 등락액(원) */
  changeAmount: number;
  /** 왜 움직였는지 한 줄. LLM 생성물이다. */
  summary: string;
};

/**
 * summary 가 LLM 생성이라 generatedAt·sources 가 함께 온다.
 * 화면에서 AI 생성 표시와 생성 기준 시각을 노출해야 한다. (루트 CLAUDE.md)
 */
export type SignalBoard = {
  signals: StockSignal[];
  asOf: string;
  generatedAt: string;
  sources: string[];
};

/* ── 관심 종목 ──────────────────────────────────────────────────────────── */

export type WatchItem = {
  code: string;
  name: string;
  initial: string;
  price: number;
  /** 등락률(%) */
  change: number;
};

export type Watchlist = {
  items: WatchItem[];
  asOf: string;
};

/* ── 값 ─────────────────────────────────────────────────────────────────── */

/**
 * 홈의 기준 시각 — 가장 최근에 장이 끝난 시각. 한국 정규장은 09:00~15:30 이다.
 *
 *   평일 15:30 이후  → 오늘 15:30
 *   평일 15:30 이전  → 전 거래일 15:30   (오늘 장은 아직 안 끝났다)
 *   토·일           → 직전 금요일 15:30
 *
 * 판단: 목업 숫자는 고정인데 기준 시각만 "지금"으로 두면 실시간인 척하는 화면이 된다.
 * 값도 문구도 "마감된 어느 날"로 맞추려고 마지막 마감 시각을 쓴다.
 *
 * 이 계산은 홈 안에만 둔다. 공용으로 빼지 않는다.
 * 시세를 실시간으로 받을지 특정 시각에 한 번만 받을지가 화면마다 갈릴 수 있어서,
 * 한 함수로 묶어두면 홈 정책을 바꿀 때 다른 화면이 딸려서 바뀐다.
 *
 * 알려진 차이: features/stock/mock.ts 의 asOf 는 아직 '2026-08-21' 로 고정이라
 * 홈에서 눌러 들어가면 날짜가 어긋난다. 브리핑 화면 담당자에게 공유된 사항이다.
 *
 * 한계: 공휴일은 못 잡는다. 설·추석에도 그날을 거래일로 센다.
 * 실제 연동에서는 백엔드가 marketStatus('preOpen' | 'open' | 'closed' | 'holiday')를
 * 함께 주고 프론트는 그 값으로 문구만 고르는 쪽이 맞다. 이 함수는 그때 사라진다.
 */
function lastMarketClose(now: Date): Date {
  const close = new Date(now);
  close.setHours(15, 30, 0, 0);

  if (now < close) close.setDate(close.getDate() - 1);
  while (close.getDay() === 0 || close.getDay() === 6) {
    close.setDate(close.getDate() - 1);
  }
  return close;
}

const AS_OF = lastMarketClose(new Date()).toISOString();

/** 판단: 삼성전자 수치는 features/stock/mock.ts 의 mockStocks['005930'] 코드와 맞춤
 *  홈에서 눌러 들어간 브리핑 화면과 숫자가 다르면 목업이라도 이상해 보인다. */

/**
 * 판단: 2행×3열 카드 배치
 *   1행) 코스피 · 코스닥 · 금현물
 *   2행) S&P 500 · 나스닥 · 달러 환율
 */
export const mockIndexBoard: IndexBoard = {
  asOf: AS_OF,
  indices: [
    { name: '코스피', value: 6912.95, change: 0.88 },
    { name: '코스닥', value: 801.94, change: -4.63 },
    { name: '금현물', value: 2643.8, change: 0.42 },
    { name: 'S&P 500', value: 5878.1, change: 0.35 },
    { name: '나스닥', value: 20173.45, change: 0.61 },
    { name: '달러 환율', value: 1386.5, change: -0.44 },
  ],
};

export const mockSignalBoard: SignalBoard = {
  asOf: AS_OF,
  generatedAt: AS_OF,
  sources: ['한국거래소', '연합인포맥스'],
  signals: [
    {
      code: '032830',
      name: '삼성생명',
      initial: '생',
      price: 328500,
      change: 10.61,
      changeAmount: 31500,
      summary: '삼성전자 주주환원 계획 발표에 배당 기대가 몰렸습니다.',
    },
    {
      code: '000660',
      name: 'SK하이닉스',
      initial: 'SK',
      price: 1730000,
      change: 2.31,
      changeAmount: 39000,
      summary: 'HBM 수출 호조에 이틀 연속 올랐습니다.',
    },
    {
      code: '005930',
      name: '삼성전자',
      initial: '삼',
      price: 62400,
      change: -1.08,
      changeAmount: -680,
      summary: '외국인 순매도와 반도체 업황 우려가 겹치며 하락 마감했습니다.',
    },
    {
      code: '373220',
      name: 'LG에너지솔루션',
      initial: 'LG',
      price: 343500,
      change: -4.05,
      changeAmount: -14500,
      summary: '미국 장기 국채금리 상승에 2차전지가 함께 밀렸습니다.',
    },
    {
      code: '009150',
      name: '삼성전기',
      initial: '전',
      price: 1316000,
      change: -5.73,
      changeAmount: -80000,
      summary: '대형주 쏠림에 소외되며 AI 관련주 낙폭이 커졌습니다.',
    },
  ],
};

export const mockWatchlist: Watchlist = {
  asOf: AS_OF,
  items: [
    { code: '005930', name: '삼성전자', initial: '삼', price: 62400, change: -1.08 },
    { code: '000660', name: 'SK하이닉스', initial: 'SK', price: 1730000, change: 2.31 },
    { code: '032830', name: '삼성생명', initial: '생', price: 328500, change: 10.61 },
    { code: '009150', name: '삼성전기', initial: '전', price: 1316000, change: -5.73 },
    { code: '373220', name: 'LG에너지솔루션', initial: 'LG', price: 343500, change: -4.05 },
    { code: '196170', name: '알테오젠', initial: '알', price: 320000, change: -5.74 },
  ],
};

/** 빈 상태를 눈으로 확인할 때 mockWatchlist 대신 이걸 넘긴다. */
export const mockEmptyWatchlist: Watchlist = { asOf: AS_OF, items: [] };

/** 빈 상태를 눈으로 확인할 때 mockSignalBoard 대신 아래 내용을 넘긴다. */
export const mockEmptySignalBoard: SignalBoard = {
  ...mockSignalBoard,
  signals: [],
};

/* 검색 자동완성 */

export type SearchableStock = {
  code: string;
  name: string;
  initial: string;
};

/** 검색창 자동완성용 mock */
export const mockSearchIndex: SearchableStock[] = [
  { code: '005930', name: '삼성전자', initial: '삼' },
  { code: '000660', name: 'SK하이닉스', initial: 'SK' },
  { code: '032830', name: '삼성생명', initial: '생' },
  { code: '373220', name: 'LG에너지솔루션', initial: 'LG' },
  { code: '009150', name: '삼성전기', initial: '전' },
  { code: '196170', name: '알테오젠', initial: '알' },
  { code: '035420', name: 'NAVER', initial: 'N' },
  { code: '035720', name: '카카오', initial: '카' },
  { code: '005380', name: '현대차', initial: '현' },
  { code: '000270', name: '기아', initial: '기' },
  { code: '068270', name: '셀트리온', initial: '셀' },
  { code: '005490', name: 'POSCO홀딩스', initial: 'P' },
];

/* 실시간 랭킹 */

export type RankingItem = {
  code: string;
  name: string;
  initial: string;
  price: number;
  /** 등락률(%) */
  change: number;
  /** 거래량(주) */
  volume: number;
  /** 거래대금(원) */
  tradingValue: number;
};

/**
 * 탭(거래대금·거래량·등락률상승·등락률하강)별로 배열을 따로 두지 않고
 * 이 풀 하나를 화면에서 정렬·상위 10개
 */
export const mockRankingPool: RankingItem[] = [
  {
    code: '005930',
    name: '삼성전자',
    initial: '삼',
    price: 62400,
    change: -1.08,
    volume: 18_452_300,
    tradingValue: 1_151_223_720_000,
  },
  {
    code: '000660',
    name: 'SK하이닉스',
    initial: 'SK',
    price: 1730000,
    change: 2.31,
    volume: 3_218_900,
    tradingValue: 5_568_696_700_000,
  },
  {
    code: '032830',
    name: '삼성생명',
    initial: '생',
    price: 328500,
    change: 10.61,
    volume: 2_104_500,
    tradingValue: 691_327_650_000,
  },
  {
    code: '373220',
    name: 'LG에너지솔루션',
    initial: 'LG',
    price: 343500,
    change: -4.05,
    volume: 1_842_100,
    tradingValue: 632_760_450_000,
  },
  {
    code: '009150',
    name: '삼성전기',
    initial: '전',
    price: 1316000,
    change: -5.73,
    volume: 512_300,
    tradingValue: 674_186_800_000,
  },
  {
    code: '196170',
    name: '알테오젠',
    initial: '알',
    price: 320000,
    change: -5.74,
    volume: 987_600,
    tradingValue: 316_032_000_000,
  },
  {
    code: '035420',
    name: 'NAVER',
    initial: 'N',
    price: 218500,
    change: 1.44,
    volume: 1_326_700,
    tradingValue: 289_884_950_000,
  },
  {
    code: '035720',
    name: '카카오',
    initial: '카',
    price: 41250,
    change: -2.13,
    volume: 4_215_800,
    tradingValue: 173_901_750_000,
  },
  {
    code: '005380',
    name: '현대차',
    initial: '현',
    price: 231000,
    change: 0.65,
    volume: 981_200,
    tradingValue: 226_657_200_000,
  },
  {
    code: '000270',
    name: '기아',
    initial: '기',
    price: 118400,
    change: 3.02,
    volume: 1_654_300,
    tradingValue: 195_869_320_000,
  },
  {
    code: '068270',
    name: '셀트리온',
    initial: '셀',
    price: 187600,
    change: -0.85,
    volume: 1_102_400,
    tradingValue: 206_770_240_000,
  },
  {
    code: '005490',
    name: 'POSCO홀딩스',
    initial: 'P',
    price: 356500,
    change: 1.98,
    volume: 428_900,
    tradingValue: 152_905_850_000,
  },
];

/* 외국인·기관 매매 동향 */

export type FlowItem = {
  code: string;
  name: string;
  initial: string;
  /** 순매수(+) / 순매도(−) 수량(주) */
  netVolume: number;
};

export const mockInvestorFlow: { buy: FlowItem[]; sell: FlowItem[] } = {
  buy: [
    { code: '005930', name: '삼성전자', initial: '삼', netVolume: 3_332_528 },
    { code: '000660', name: 'SK하이닉스', initial: 'SK', netVolume: 2_406_250 },
    { code: '005380', name: '현대차', initial: '현', netVolume: 842_150 },
    { code: '005490', name: 'POSCO홀딩스', initial: 'P', netVolume: 615_400 },
    { code: '000270', name: '기아', initial: '기', netVolume: 498_720 },
  ],
  sell: [
    { code: '035420', name: 'NAVER', initial: 'N', netVolume: -7_674_481 },
    { code: '196170', name: '알테오젠', initial: '알', netVolume: -1_982_340 },
    { code: '373220', name: 'LG에너지솔루션', initial: 'LG', netVolume: -1_204_600 },
    { code: '035720', name: '카카오', initial: '카', netVolume: -932_180 },
    { code: '068270', name: '셀트리온', initial: '셀', netVolume: -541_900 },
  ],
};

/* 섹터별 순위 */

export type SectorRank = {
  name: string;
  /** 섹터 평균 등락률(%) */
  change: number;
  topStock: string;
};

export const mockSectorRanks: SectorRank[] = [
  { name: '반도체', change: 3.42, topStock: 'SK하이닉스' },
  { name: '2차전지', change: 2.15, topStock: 'LG에너지솔루션' },
  { name: '제약·바이오', change: 1.87, topStock: '삼성바이오로직스' },
  { name: '조선', change: 1.63, topStock: 'HD현대중공업' },
  { name: '방산', change: 1.24, topStock: '한화에어로스페이스' },
];

/* 마켓 인사이트 */

export type MarketInsight = {
  id: string;
  title: string;
  /** LLM 생성 요약. */
  summary: string;
};

/** 마켓 인사이트 관련 mock */
export const mockMarketInsights: {
  items: MarketInsight[];
  generatedAt: string;
  sources: string[];
} = {
  generatedAt: AS_OF,
  sources: ['연합인포맥스', '한국거래소'],
  items: [
    {
      id: 'i1',
      title: '반도체 업황 개선 기대감 지속',
      summary:
        'HBM 수요 증가와 파운드리 가동률 상승이 맞물리며 반도체 대형주 중심의 순환매가 이어지고 있습니다.',
    },
    {
      id: 'i2',
      title: '외국인 순매수 전환, 코스피 상승 견인',
      summary: '최근 3거래일 연속 외국인 순매수가 유입되며 지수 반등에 힘을 실었습니다.',
    },
    {
      id: 'i3',
      title: '2차전지주 변동성 확대',
      summary:
        '미국 금리 인상 우려와 완성차 수요 둔화 전망이 겹치며 2차전지 관련주 등락폭이 커졌습니다.',
    },
  ],
};
