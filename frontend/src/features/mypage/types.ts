/**
 * 마이페이지 API 계약 타입 (frontend/MYPAGE.md §3).
 * 아직 합의 전이라 홈 mock 타입을 import 하지 않고 여기에만 둔다.
 * 실제 연동 시 lib/types.ts 로 옮긴다.
 */

export type MyScrap = {
  scrapId: string;
  reportId: string;
  /** 지금은 'STOCK' 만. 시장 보고서가 생기면 'MARKET' */
  reportType: 'STOCK';
  stockCode: string;
  stockName: string;
  /** 보고서 당시 등락률(%). 현재가 기준이 아니다. */
  changePct: number;
  /** 보고서 기준 시각(ISO 8601) */
  asOf: string;
  /** 링크 ?date= 에 쓰는 날짜 YYYY-MM-DD */
  targetDate: string;
  /** 한 줄 요약. LLM 생성물이다. */
  headline: string;
  generatedAt: string;
  sources: string[];
  scrappedAt: string;
};

export type MyScrapList = {
  /** scrappedAt 내림차순 */
  items: MyScrap[];
};

export type MyWatchItem = {
  code: string;
  name: string;
  price: number;
  /** 등락률(%) */
  change: number;
};

export type MyWatchlist = {
  asOf: string;
  items: MyWatchItem[];
};
