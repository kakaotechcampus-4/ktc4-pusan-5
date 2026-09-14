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

export type Briefing = {
  text: string;
  generatedAt: string;
  sources: string[];
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

/**
 * 브리핑 본문. 내용은 임의로 작성함
 */
export const mockBriefings: Record<string, Briefing> = {
  '005930': {
    text: '외국인 매도세와 반도체 업황 우려가 겹치며 하락 마감했습니다. 전날 발표된 메모리 가격 전망 하향 조정이 투자심리에 영향을 준 것으로 보입니다.',
    generatedAt: '2026-08-21T15:35:00+09:00',
    sources: ['한국거래소', '연합인포맥스'],
  },
  '000660': {
    text: 'HBM 수출 호조에 이틀 연속 올랐습니다. 주요 고객사向 공급 물량 확대 소식이 전해지며 반도체 업종 전반의 투자심리를 끌어올렸습니다.',
    generatedAt: '2026-08-21T15:35:00+09:00',
    sources: ['한국거래소', '연합인포맥스'],
  },
  '032830': {
    text: '삼성전자 주주환원 계획 발표에 배당 기대가 몰렸습니다. 그룹 계열사 전반의 배당 성향 강화 기대가 겹치며 금융주 매수세가 이어졌습니다.',
    generatedAt: '2026-08-21T15:35:00+09:00',
    sources: ['한국거래소', '연합인포맥스'],
  },
  '373220': {
    text: '미국 장기 국채금리 상승에 2차전지가 함께 밀렸습니다. 금리 부담이 성장주 밸류에이션에 부정적으로 작용하며 업종 전반이 약세를 보였습니다.',
    generatedAt: '2026-08-21T15:35:00+09:00',
    sources: ['한국거래소', '연합인포맥스'],
  },
  '009150': {
    text: '대형주 쏠림에 소외되며 AI 관련주 낙폭이 커졌습니다. 최근 수급이 일부 대형주로 집중되면서 상대적으로 매도 압력이 커진 것으로 보입니다.',
    generatedAt: '2026-08-21T15:35:00+09:00',
    sources: ['한국거래소', '연합인포맥스'],
  },
  '196170': {
    text: '위탁개발생산(CDMO) 계약 관련 불확실성이 부각되며 매도세가 유입돼 하락 마감했습니다. 최근 급등에 따른 차익 실현 매물도 겹친 것으로 보입니다.',
    generatedAt: '2026-08-21T15:35:00+09:00',
    sources: ['한국거래소', '연합인포맥스'],
  },
};
