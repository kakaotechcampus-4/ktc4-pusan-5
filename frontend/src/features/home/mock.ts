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

/** 판단: 삼성전자 수치는 features/stock/mock.ts 의 mockStock 과 맞췄다.
 *  홈에서 눌러 들어간 브리핑 화면과 숫자가 다르면 목업이라도 이상해 보인다. */

export const mockIndexBoard: IndexBoard = {
  asOf: AS_OF,
  indices: [
    { name: '코스피', value: 6912.95, change: 0.88 },
    { name: '코스닥', value: 801.94, change: -4.63 },
    { name: '코스피200', value: 927.44, change: 1.02 },
    { name: '원 · 달러', value: 1386.5, change: -0.44 },
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
