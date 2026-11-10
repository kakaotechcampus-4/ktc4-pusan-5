/**
 * 마이페이지 API 계약 타입. GET /api/scraps 응답이다.
 * 값이 없을 수 있는 필드(이름·등락률·요약·생성 시각)는 null 로 온다.
 */

export type MyScrap = {
  scrapId: string;
  reportId: number;
  /** 지금은 'STOCK' 만. 시장 보고서가 생기면 'MARKET' */
  reportType: 'STOCK';
  stockCode: string;
  stockName: string | null;
  /** 보고서 당시 등락률(%). 현재가 기준이 아니다. */
  changePct: number | null;
  /** 보고서 기준 시각(ISO 8601) */
  asOf: string;
  /** 보고서 기준일 YYYY-MM-DD */
  targetDate: string | null;
  /** 한 줄 요약. LLM 생성물이다. */
  headline: string | null;
  generatedAt: string | null;
  sources: string[];
  scrappedAt: string;
};

export type MyScrapList = {
  /** scrappedAt 내림차순 */
  items: MyScrap[];
};
