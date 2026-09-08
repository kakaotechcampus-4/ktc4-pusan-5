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

export const mockStock: StockQuote = {
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
};

export const mockBriefing: Briefing = {
  text: '외국인 매도세와 반도체 업황 우려가 겹치며 하락 마감했습니다. 전날 발표된 메모리 가격 전망 하향 조정이 투자심리에 영향을 준 것으로 보입니다.',
  generatedAt: '2026-08-21T15:35:00+09:00',
  sources: ['한국거래소', '연합인포맥스'],
};
