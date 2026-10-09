/**
 * 마이페이지 목업 데이터. 실제 API 연동 시 이 파일 대신 lib/api.ts 를 쓴다.
 * 스크랩 문장은 ai/tests/fixtures/reports/*-2026-09-18-*.json 의 실제 보고서에서 가져왔다.
 *   headline = factors[0].claim, changePct = change_pct, sources = factors 출처 channel (중복 제거)
 * 숫자는 가공하지 않은 원본이다. 포맷은 화면에서 lib/format.ts 로 한다.
 */
import type { MyScrapList, MyWatchlist } from './types';

export const mockScraps: MyScrapList = {
  items: [
    {
      scrapId: 's_103',
      reportId: 'r_5530',
      reportType: 'STOCK',
      stockCode: '096770',
      stockName: 'SK이노베이션',
      changePct: -2.01,
      asOf: '2026-09-18T15:30:00+09:00',
      targetDate: '2026-09-18',
      headline: '간밤 국제 유가가 내린 것이 이 회사의 석유 사업에 부담이 됐을 수 있습니다.',
      generatedAt: '2026-09-18T16:20:00+09:00',
      sources: ['KISGregKim', 'globalmktinsight'],
      scrappedAt: '2026-09-21T09:12:00+09:00',
    },
    {
      scrapId: 's_102',
      reportId: 'r_5522',
      reportType: 'STOCK',
      stockCode: '000660',
      stockName: 'SK하이닉스',
      changePct: 4.25,
      asOf: '2026-09-18T15:30:00+09:00',
      targetDate: '2026-09-18',
      headline:
        '엔비디아 최고경영자의 칩 판매 전망 발언으로 간밤 미국 메모리 종목이 크게 올랐습니다.',
      generatedAt: '2026-09-18T16:15:00+09:00',
      sources: ['KISGregKim', 'merITz_tech', 'skitteam', 'kiwoom_semibat'],
      scrappedAt: '2026-09-20T22:31:00+09:00',
    },
    {
      scrapId: 's_101',
      reportId: 'r_5521',
      reportType: 'STOCK',
      stockCode: '005930',
      stockName: '삼성전자',
      changePct: 3.37,
      asOf: '2026-09-18T15:30:00+09:00',
      targetDate: '2026-09-18',
      headline:
        '엔비디아 최고경영자가 내년 칩 판매가 두 배로 늘 것이라고 밝히면서 메모리 종목에 기대가 모였을 수 있습니다.',
      generatedAt: '2026-09-18T16:10:00+09:00',
      sources: ['KISGregKim'],
      scrappedAt: '2026-09-20T21:04:00+09:00',
    },
  ],
};

/** 빈 상태를 눈으로 확인할 때 mockScraps 대신 이걸 쓴다. */
export const mockEmptyScraps: MyScrapList = { items: [] };

/** 홈 mockWatchlist 와 같은 6종목. initial 은 백엔드가 주지 않으므로 넣지 않는다. */
export const mockMyWatchlist: MyWatchlist = {
  asOf: '2026-10-02T15:30:00+09:00',
  items: [
    { code: '005930', name: '삼성전자', price: 62400, change: -1.08 },
    { code: '000660', name: 'SK하이닉스', price: 1730000, change: 2.31 },
    { code: '032830', name: '삼성생명', price: 328500, change: 10.61 },
    { code: '009150', name: '삼성전기', price: 1316000, change: -5.73 },
    { code: '373220', name: 'LG에너지솔루션', price: 343500, change: -4.05 },
    { code: '196170', name: '알테오젠', price: 320000, change: -5.74 },
  ],
};

/** 빈 상태를 눈으로 확인할 때 mockMyWatchlist 대신 이걸 쓴다. */
export const mockEmptyMyWatchlist: MyWatchlist = { asOf: mockMyWatchlist.asOf, items: [] };
