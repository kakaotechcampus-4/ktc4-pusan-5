/**
 * 마이페이지 API 계약 타입. GET /api/scraps 응답이다.
 * 값이 없을 수 있는 필드(이름·등락률·요약·생성 시각)는 null 로 온다.
 */

type MyScrapBase = {
  scrapId: string;
  reportId: number;
  /** 지금은 'STOCK' 만. 시장 보고서가 생기면 'MARKET' */
  reportType: 'STOCK';
  scrappedAt: string;
};

/**
 * 보고서가 지워졌거나 읽을 수 없거나 서비스 종목에서 빠졌다.
 * 종목·기준 시각 등은 비어 있어 카드를 채울 수 없고, 스크랩 해제만 할 수 있다.
 */
export type UnavailableScrap = MyScrapBase & {
  available: false;
  stockCode: null;
  stockName: null;
  changePct: null;
  asOf: null;
  targetDate: null;
  headline: null;
  generatedAt: null;
  sources: string[];
};

export type AvailableScrap = MyScrapBase & {
  available: true;
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
};

export type MyScrap = AvailableScrap | UnavailableScrap;

export type MyScrapList = {
  /** scrappedAt 내림차순 */
  items: MyScrap[];
};
