/**
 * 실제 API 붙일 때 이 파일 대신 lib/api.ts + lib/types.ts 를 쓴다.
 * 판단: lib/types.ts는 아직 TODO(실제 연동 담당 몫)라 여기서는 로컬 타입으로만 둔다.
 */

export type StockQuote = {
  name: string;
  code: string;
  price: number;
  change: number;
  changeAmount: number;
  marketCap: number;
  per: number;
  pbr: number;
  volume: number;
  asOf: string;
};

/**
 * 종목 코드별 목업. features/home/mock.ts 의 시세(price·change·changeAmount)와 수치를 맞춤
 * 실제 값 아님
 */
export const mockStocks: Record<string, StockQuote> = {
  '005930': {
    name: '삼성전자',
    code: '005930',
    price: 62400,
    change: -1.08,
    changeAmount: -680,
    marketCap: 372000000000000,
    per: 11.4,
    pbr: 1.32,
    volume: 14203000,
    asOf: '2026-08-21T15:30:00+09:00',
  },
  '000660': {
    name: 'SK하이닉스',
    code: '000660',
    price: 1730000,
    change: 2.31,
    changeAmount: 39000,
    marketCap: 251000000000000,
    per: 18.7,
    pbr: 2.95,
    volume: 3120000,
    asOf: '2026-08-21T15:30:00+09:00',
  },
  '032830': {
    name: '삼성생명',
    code: '032830',
    price: 328500,
    change: 10.61,
    changeAmount: 31500,
    marketCap: 21000000000000,
    per: 9.8,
    pbr: 0.62,
    volume: 892000,
    asOf: '2026-08-21T15:30:00+09:00',
  },
  '373220': {
    name: 'LG에너지솔루션',
    code: '373220',
    price: 343500,
    change: -4.05,
    changeAmount: -14500,
    marketCap: 80000000000000,
    per: 42.3,
    pbr: 3.15,
    volume: 1450000,
    asOf: '2026-08-21T15:30:00+09:00',
  },
  '009150': {
    name: '삼성전기',
    code: '009150',
    price: 1316000,
    change: -5.73,
    changeAmount: -80000,
    marketCap: 9800000000000,
    per: 15.2,
    pbr: 1.48,
    volume: 210000,
    asOf: '2026-08-21T15:30:00+09:00',
  },
  '196170': {
    name: '알테오젠',
    code: '196170',
    price: 320000,
    change: -5.74,
    changeAmount: -19487,
    marketCap: 18500000000000,
    per: 185.0,
    pbr: 12.4,
    volume: 980000,
    asOf: '2026-08-21T15:30:00+09:00',
  },
};

/* ── 주가/거래량 캔들 (PRICE ACTION) ───────────────────────────────────── */

export type Candle = {
  /** 'YYYY-MM-DD' */
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type PricePeriod = '1M' | '3M' | '1Y' | '5Y' | 'ALL';

export const PERIOD_DAYS: Record<PricePeriod, number> = {
  '1M': 22,
  '3M': 65,
  '1Y': 252,
  '5Y': 1250,
  ALL: 1250,
};

/**
 * 종목 코드를 시드로 쓰는 결정적 의사난수. 새로고침해도 같은 모양의 캔들이 나오게 한다.
 * 실제 OHLCV를 손으로 1250×6종목 채울 수 없어서 걷는 방식으로 만든다 — 진짜 시세는 아니다.
 */
function makeRng(seed: string) {
  let s = [...seed].reduce((acc, ch) => acc + ch.charCodeAt(0), 1);
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

function generateCandles(code: string, latestClose: number, asOf: string, days: number): Candle[] {
  const rand = makeRng(code);

  const dates: Date[] = [];
  const cursor = new Date(asOf);
  while (dates.length < days) {
    if (cursor.getDay() !== 0 && cursor.getDay() !== 6) dates.unshift(new Date(cursor));
    cursor.setDate(cursor.getDate() - 1);
  }

  // 5년 전 값에서 시작해 오늘 종가로 수렴하도록 걷는다 (완전 랜덤워크면 asOf 종가와 안 맞음).
  let price = latestClose * (0.55 + rand() * 0.2);
  const candles: Candle[] = dates.map((date, i) => {
    const remaining = dates.length - i;
    const pullToTarget = (latestClose - price) / Math.max(remaining, 1) / price;
    const noise = (rand() - 0.5) * 0.03;
    const open = price;
    price = Math.max(price * (1 + pullToTarget + noise), latestClose * 0.2);
    const close = i === dates.length - 1 ? latestClose : price;
    const high = Math.max(open, close) * (1 + rand() * 0.012);
    const low = Math.min(open, close) * (1 - rand() * 0.012);
    return {
      time: date.toISOString().slice(0, 10),
      open: Math.round(open),
      high: Math.round(high),
      low: Math.round(low),
      close: Math.round(close),
      volume: Math.round(400_000 + rand() * 4_000_000),
    };
  });
  return candles;
}

export const mockPriceHistory: Record<string, Candle[]> = Object.fromEntries(
  Object.entries(mockStocks).map(([code, stock]) => [
    code,
    generateCandles(code, stock.price, stock.asOf, PERIOD_DAYS['5Y']),
  ]),
);

/* ── 주요 지표 (AT A GLANCE) ────────────────────────────────────────────── */

export type AtAGlance = {
  per: number;
  pbr: number;
  eps: number;
  bps: number;
  week52High: number;
  week52Low: number;
};

function buildAtAGlance(stock: StockQuote, history: Candle[]): AtAGlance {
  const oneYear = history.slice(-PERIOD_DAYS['1Y']);
  return {
    per: stock.per,
    pbr: stock.pbr,
    eps: Math.round(stock.price / stock.per),
    bps: Math.round(stock.price / stock.pbr),
    week52High: Math.max(...oneYear.map((c) => c.high)),
    week52Low: Math.min(...oneYear.map((c) => c.low)),
  };
}

/* ── 수급 동향 ──────────────────────────────────────────────────────────── */

export type InvestorFlow = {
  /** 순매수(+) / 순매도(−) 수량(주) */
  individual: number;
  foreign: number;
  institutional: number;
  /** 직전 기간 대비 수급(외국인+기관 합산) 변화율(%). 차트 없이 이 숫자만 보여준다. */
  periodChangePct: number;
};

/* ── 공매도 · 신용잔고 ──────────────────────────────────────────────────── */

export type ShortSelling = {
  /** 공매도 비중(%) */
  ratio: number;
  /** 전일 대비 등락(%p). 차트 없이 이 숫자만 보여준다. */
  changePct: number;
};

export type MarginBalance = {
  /** 신용잔고 수량(주) */
  quantity: number;
  /** 등락률(%). 차트 없이 이 숫자만 보여준다. */
  changePct: number;
};

/* ── 재무 실적 ──────────────────────────────────────────────────────────── */

export type FinancialSummary = {
  revenue: number;
  operatingProfit: number;
  netIncome: number;
};

/* ── 재무 추이 (5년치) / 재무 건전성 / 분기별 투자 지표 ──────────────────── */

export type FinancialTrendPoint = {
  /** 'YYYY' */
  year: string;
  revenue: number;
  operatingProfit: number;
  eps: number;
};

export type FinancialHealth = {
  /** 부채비율(%) */
  debtRatio: number;
  /** 자기자본이익률(%) */
  roe: number;
  /** 유동비율(%) */
  currentRatio: number;
};

export type QuarterlyMetric = {
  /** '2026 Q3' */
  quarter: string;
  /** 상대강도(0~100) */
  rs: number;
  /** 매출 성장률(전년 동기 대비, %) */
  revenueGrowth: number;
  operatingProfitGrowth: number;
  netIncomeGrowth: number;
  marketCap: number;
  per: number;
  pbr: number;
  roe: number;
  debtRatio: number;
  operatingProfit: number;
  netIncome: number;
  eps: number;
};

/**
 * 목표값으로 수렴하도록 걷는 시계열 생성기. candle 생성기와 같은 방식이다.
 * 시작점은 목표 근방에서 무작위로 잡고, 마지막 값은 항상 target과 정확히 같다.
 */
function walkToTarget(
  rand: () => number,
  target: number,
  steps: number,
  volatility: number,
): number[] {
  const magnitude = Math.abs(target) || 1;
  let v = target + (rand() - 0.5) * magnitude * 0.6;
  const out: number[] = [];
  for (let i = 0; i < steps; i++) {
    const remaining = steps - i;
    const pull = (target - v) / Math.max(remaining, 1);
    const noise = (rand() - 0.5) * volatility * magnitude;
    v = v + pull + noise;
    out.push(v);
  }
  out[out.length - 1] = target;
  return out;
}

function quarterLabels(count: number, endYear: number, endQuarter: number): string[] {
  const labels: string[] = [];
  let y = endYear;
  let q = endQuarter;
  for (let i = 0; i < count; i++) {
    labels.unshift(`${y} Q${q}`);
    q -= 1;
    if (q === 0) {
      q = 4;
      y -= 1;
    }
  }
  return labels;
}

function buildFinancialTrend(
  code: string,
  stock: StockQuote,
  financials: FinancialSummary,
): FinancialTrendPoint[] {
  const rand = makeRng(`${code}-trend`);
  const years = ['2022', '2023', '2024', '2025', '2026'];
  const eps = Math.round(stock.price / stock.per);

  const revenues = walkToTarget(rand, financials.revenue, years.length, 0.12);
  const profits = walkToTarget(rand, financials.operatingProfit, years.length, 0.2);
  const epsSeries = walkToTarget(rand, eps, years.length, 0.18);

  return years.map((year, i) => ({
    year,
    revenue: Math.round(revenues[i]),
    operatingProfit: Math.round(profits[i]),
    eps: Math.round(epsSeries[i]),
  }));
}

const QUARTER_COUNT = 8;

function buildQuarterlyMetrics(
  code: string,
  stock: StockQuote,
  financials: FinancialSummary,
  health: FinancialHealth,
): QuarterlyMetric[] {
  const rand = makeRng(`${code}-quarterly`);
  const labels = quarterLabels(QUARTER_COUNT, 2026, 3);
  const eps = Math.round(stock.price / stock.per);

  const marketCaps = walkToTarget(rand, stock.marketCap, QUARTER_COUNT, 0.12);
  const pers = walkToTarget(rand, stock.per, QUARTER_COUNT, 0.15);
  const pbrs = walkToTarget(rand, stock.pbr, QUARTER_COUNT, 0.15);
  const roes = walkToTarget(rand, health.roe, QUARTER_COUNT, 0.2);
  const debtRatios = walkToTarget(rand, health.debtRatio, QUARTER_COUNT, 0.1);
  const operatingProfits = walkToTarget(rand, financials.operatingProfit / 4, QUARTER_COUNT, 0.3);
  const netIncomes = walkToTarget(rand, financials.netIncome / 4, QUARTER_COUNT, 0.3);
  const epsList = walkToTarget(rand, eps / 4, QUARTER_COUNT, 0.3);

  return labels.map((quarter, i) => ({
    quarter,
    rs: Math.round(30 + rand() * 60),
    revenueGrowth: Math.round((rand() * 30 - 10) * 10) / 10,
    operatingProfitGrowth: Math.round((rand() * 40 - 15) * 10) / 10,
    netIncomeGrowth: Math.round((rand() * 40 - 15) * 10) / 10,
    marketCap: Math.round(marketCaps[i]),
    per: Math.round(pers[i] * 100) / 100,
    pbr: Math.round(pbrs[i] * 100) / 100,
    roe: Math.round(roes[i] * 10) / 10,
    debtRatio: Math.round(debtRatios[i] * 10) / 10,
    operatingProfit: Math.round(operatingProfits[i]),
    netIncome: Math.round(netIncomes[i]),
    eps: Math.round(epsList[i]),
  }));
}

export type StockDetail = {
  tradingValue: number;
  /** 외국인 보유 지분율(%) */
  foreignOwnership: number;
  atAGlance: AtAGlance;
  investorFlow: InvestorFlow;
  shortSelling: ShortSelling;
  marginBalance: MarginBalance;
  financials: FinancialSummary;
  financialTrend: FinancialTrendPoint[];
  financialHealth: FinancialHealth;
  quarterlyMetrics: QuarterlyMetric[];
};

type StockDetailInput = Omit<StockDetail, 'atAGlance' | 'financialTrend' | 'quarterlyMetrics'>;

/** atAGlance·financialTrend·quarterlyMetrics는 stock/financials/financialHealth에서 파생되므로 여기서 한 번만 계산한다. */
function buildStockDetail(code: string, input: StockDetailInput): StockDetail {
  const stock = mockStocks[code];
  return {
    ...input,
    atAGlance: buildAtAGlance(stock, mockPriceHistory[code]),
    financialTrend: buildFinancialTrend(code, stock, input.financials),
    quarterlyMetrics: buildQuarterlyMetrics(code, stock, input.financials, input.financialHealth),
  };
}

export const mockStockDetails: Record<string, StockDetail> = {
  '005930': buildStockDetail('005930', {
    tradingValue: 886_147_200_000,
    foreignOwnership: 51.2,
    investorFlow: {
      individual: -1_204_300,
      foreign: -2_680_100,
      institutional: 3_884_400,
      periodChangePct: -12.4,
    },
    shortSelling: { ratio: 1.85, changePct: 0.12 },
    marginBalance: { quantity: 24_645_000, changePct: -0.8 },
    financials: {
      revenue: 171_500_000_000_000,
      operatingProfit: 89_490_000_000_000,
      netIncome: 71_620_000_000_000,
    },
    financialHealth: { debtRatio: 27.4, roe: 9.8, currentRatio: 218.5 },
  }),
  '000660': buildStockDetail('000660', {
    tradingValue: 5_397_600_000_000,
    foreignOwnership: 54.6,
    investorFlow: {
      individual: -2_884_200,
      foreign: 3_120_500,
      institutional: 902_100,
      periodChangePct: 18.7,
    },
    shortSelling: { ratio: 2.41, changePct: -0.34 },
    marginBalance: { quantity: 3_218_400, changePct: 1.2 },
    financials: {
      revenue: 66_190_000_000_000,
      operatingProfit: 23_470_000_000_000,
      netIncome: 17_050_000_000_000,
    },
    financialHealth: { debtRatio: 41.2, roe: 15.6, currentRatio: 187.3 },
  }),
  '032830': buildStockDetail('032830', {
    tradingValue: 292_600_000_000,
    foreignOwnership: 38.4,
    investorFlow: {
      individual: -412_800,
      foreign: 218_400,
      institutional: 194_400,
      periodChangePct: 6.3,
    },
    shortSelling: { ratio: 0.62, changePct: 0.04 },
    marginBalance: { quantity: 985_200, changePct: -1.5 },
    financials: {
      revenue: 38_420_000_000_000,
      operatingProfit: 2_180_000_000_000,
      netIncome: 1_940_000_000_000,
    },
    financialHealth: { debtRatio: 892.1, roe: 8.4, currentRatio: 105.2 },
  }),
  '373220': buildStockDetail('373220', {
    tradingValue: 632_760_000_000,
    foreignOwnership: 41.7,
    investorFlow: {
      individual: 884_200,
      foreign: -1_204_600,
      institutional: -640_100,
      periodChangePct: -21.5,
    },
    shortSelling: { ratio: 3.12, changePct: 0.48 },
    marginBalance: { quantity: 1_842_900, changePct: 2.6 },
    financials: {
      revenue: 25_600_000_000_000,
      operatingProfit: -280_000_000_000,
      netIncome: -410_000_000_000,
    },
    financialHealth: { debtRatio: 118.6, roe: -3.2, currentRatio: 132.4 },
  }),
  '009150': buildStockDetail('009150', {
    tradingValue: 276_360_000_000,
    foreignOwnership: 33.9,
    investorFlow: {
      individual: 218_400,
      foreign: -184_200,
      institutional: -98_600,
      periodChangePct: -8.9,
    },
    shortSelling: { ratio: 1.24, changePct: -0.06 },
    marginBalance: { quantity: 412_600, changePct: -2.1 },
    financials: {
      revenue: 9_820_000_000_000,
      operatingProfit: 512_000_000_000,
      netIncome: 398_000_000_000,
    },
    financialHealth: { debtRatio: 68.9, roe: 7.1, currentRatio: 145.8 },
  }),
  '196170': buildStockDetail('196170', {
    tradingValue: 313_600_000_000,
    foreignOwnership: 12.8,
    investorFlow: {
      individual: 612_400,
      foreign: -412_800,
      institutional: -198_400,
      periodChangePct: -34.2,
    },
    shortSelling: { ratio: 4.86, changePct: 0.92 },
    marginBalance: { quantity: 2_146_800, changePct: 4.8 },
    financials: {
      revenue: 620_000_000_000,
      operatingProfit: 98_000_000_000,
      netIncome: 74_000_000_000,
    },
    financialHealth: { debtRatio: 32.5, roe: 4.2, currentRatio: 612.3 },
  }),
};
