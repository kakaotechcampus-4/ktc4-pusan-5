/**
 * 여러 목업이 함께 쓰는 값. 종목·관심 종목·랭킹 목업이 같은 종목을 가리키도록 한 곳에 둔다.
 * 종목 목업 코드를 바꾸면 관심 종목·랭킹 목업도 따라온다.
 */

/** 화면 데이터가 실제 종목과 섞이지 않게 실제로 쓰지 않는 코드를 쓴다 */
export const mockPrimaryStock = { code: '900100', name: '목업전자', market: 'KOSPI' } as const;

/** 랭킹·수급 목록의 두 번째 줄 */
export const mockSecondaryStock = { code: '900200', name: '목업화학', market: 'KOSPI' } as const;

/** 시세·지표의 기준 시각 (asOf) */
export const mockAsOf = '2026-08-21T15:30:00+09:00';

/** 수집 시각 (collectedAt) */
export const mockCollectedAt = '2026-08-21T15:31:00+09:00';
