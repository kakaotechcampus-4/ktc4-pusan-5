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

/* ── AI 생성 보고서 ─────────────────────────────────────────────────────────
 * 가드레일: 매수·매도 같은 투자의견 문구를 넣지 않는다. (DESIGN.md 7절, 루트 CLAUDE.md)
 * 목표주가를 넣는 경우 반드시 출처를 함께 둔다. */

export type AiReport = {
  summaryPoints: string[];
  conclusion: string;
  targetPrice?: { value: number; source: string };
  generatedAt: string;
  sources: string[];
};

export type StockDetail = {
  tradingValue: number;
  /** 외국인 보유 지분율(%) */
  foreignOwnership: number;
  atAGlance: AtAGlance;
  investorFlow: InvestorFlow;
  shortSelling: ShortSelling;
  marginBalance: MarginBalance;
  financials: FinancialSummary;
  aiReport: AiReport;
};

const GENERATED_AT = '2026-08-21T15:40:00+09:00';

export const mockStockDetails: Record<string, StockDetail> = {
  '005930': {
    tradingValue: 886_147_200_000,
    foreignOwnership: 51.2,
    atAGlance: buildAtAGlance(mockStocks['005930'], mockPriceHistory['005930']),
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
    aiReport: {
      summaryPoints: [
        '외국인 매도세와 반도체 업황 우려가 겹치며 최근 하락 마감했습니다.',
        'PER 11.4배·PBR 1.32배로 최근 5년 평균 대비 밸류에이션 부담은 크지 않은 수준입니다.',
        '기관 수급은 순매수를 유지하고 있어 개인·외국인 매도 물량을 일부 받아내는 모습입니다.',
        '영업이익률은 전년 대비 개선되는 추세지만, 메모리 가격 변동성은 계속 지켜봐야 할 변수입니다.',
      ],
      conclusion:
        '재무·수급·기술적 지표를 종합했을 때 단기 변동성이 확대된 구간으로 보입니다. 이 보고서는 정보 제공 목적이며, 투자 판단과 그 책임은 본인에게 있습니다.',
      targetPrice: { value: 78000, source: '한국투자증권 리서치(가상)' },
      generatedAt: GENERATED_AT,
      sources: ['한국거래소', '연합인포맥스'],
    },
  },
  '000660': {
    tradingValue: 5_397_600_000_000,
    foreignOwnership: 54.6,
    atAGlance: buildAtAGlance(mockStocks['000660'], mockPriceHistory['000660']),
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
    aiReport: {
      summaryPoints: [
        'HBM 수출 호조에 이틀 연속 오르며 반도체 업종 내 상대 강세를 보였습니다.',
        'PER 18.7배·PBR 2.95배로 고성장 기대가 밸류에이션에 일부 반영돼 있습니다.',
        '외국인 순매수가 이어지고 있어 수급 측면은 우호적인 편입니다.',
      ],
      conclusion:
        'HBM 중심 수급 개선이 확인되지만 고밸류에이션 부담도 함께 존재합니다. 이 보고서는 정보 제공 목적이며, 투자 판단과 그 책임은 본인에게 있습니다.',
      generatedAt: GENERATED_AT,
      sources: ['한국거래소', '연합인포맥스'],
    },
  },
  '032830': {
    tradingValue: 292_600_000_000,
    foreignOwnership: 38.4,
    atAGlance: buildAtAGlance(mockStocks['032830'], mockPriceHistory['032830']),
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
    aiReport: {
      summaryPoints: [
        '삼성전자 주주환원 계획 발표에 배당 기대가 몰리며 급등했습니다.',
        'PER 9.8배·PBR 0.62배로 금융주 평균 대비 낮은 밸류에이션 구간입니다.',
        '급등 이후 단기 변동성이 커질 수 있어 수급 흐름을 함께 살펴볼 필요가 있습니다.',
      ],
      conclusion:
        '배당 기대감이 주가를 밀어올린 구간으로, 이 보고서는 정보 제공 목적이며 투자 판단과 그 책임은 본인에게 있습니다.',
      generatedAt: GENERATED_AT,
      sources: ['한국거래소', '연합인포맥스'],
    },
  },
  '373220': {
    tradingValue: 632_760_000_000,
    foreignOwnership: 41.7,
    atAGlance: buildAtAGlance(mockStocks['373220'], mockPriceHistory['373220']),
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
    aiReport: {
      summaryPoints: [
        '미국 장기 국채금리 상승에 2차전지 업종 전반이 약세를 보였습니다.',
        'PER 42.3배로 이익 대비 밸류에이션 부담이 상대적으로 높은 편입니다.',
        '외국인·기관 동반 순매도가 이어지고 있어 수급 부담이 큽니다.',
      ],
      conclusion:
        '금리 민감도가 높은 업종 특성상 변동성이 큰 구간입니다. 이 보고서는 정보 제공 목적이며, 투자 판단과 그 책임은 본인에게 있습니다.',
      generatedAt: GENERATED_AT,
      sources: ['한국거래소', '연합인포맥스'],
    },
  },
  '009150': {
    tradingValue: 276_360_000_000,
    foreignOwnership: 33.9,
    atAGlance: buildAtAGlance(mockStocks['009150'], mockPriceHistory['009150']),
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
    aiReport: {
      summaryPoints: [
        '대형주 쏠림에 소외되며 낙폭이 커졌습니다.',
        'PER 15.2배·PBR 1.48배 수준으로 업종 평균과 큰 차이는 없습니다.',
      ],
      conclusion:
        '단기적으로는 수급 소외 구간으로 보입니다. 이 보고서는 정보 제공 목적이며, 투자 판단과 그 책임은 본인에게 있습니다.',
      generatedAt: GENERATED_AT,
      sources: ['한국거래소', '연합인포맥스'],
    },
  },
  '196170': {
    tradingValue: 313_600_000_000,
    foreignOwnership: 12.8,
    atAGlance: buildAtAGlance(mockStocks['196170'], mockPriceHistory['196170']),
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
    aiReport: {
      summaryPoints: [
        '위탁개발생산(CDMO) 계약 관련 불확실성이 부각되며 매도세가 유입됐습니다.',
        'PER 185배로 이익 대비 밸류에이션 부담이 매우 큰 편입니다.',
        '공매도 비중이 4.86%로 다른 종목 대비 높아 변동성이 커질 수 있습니다.',
      ],
      conclusion:
        '이벤트 민감도가 매우 높은 구간입니다. 이 보고서는 정보 제공 목적이며, 투자 판단과 그 책임은 본인에게 있습니다.',
      generatedAt: GENERATED_AT,
      sources: ['한국거래소', '연합인포맥스'],
    },
  },
};
