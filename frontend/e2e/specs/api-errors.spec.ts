/**
 * API 오류 처리 (목업)
 * 홈·종목 브리핑의 주요 요청이 실패해도 화면이 깨지지 않고 오류를 알리는지 본다.
 * 404 STOCK_NOT_FOUND 를 주소로 직접 들어오는 경우는 deep-link.spec.ts 가 본다.
 */
import { expect, TAG, test } from '../fixtures/test';
import { apiFallbackMessages, mockApiErrors, mockReply, mockStockOverview } from '../mocks';

const mockServerFailure = mockApiErrors.internal('목업 서버 오류: 데이터를 만들지 못했습니다');

test.describe('API 오류 처리', { tag: TAG.core }, () => {
  test.describe('홈 시세 요청 실패', () => {
    // 홈은 시세 실패 이유(서버 메시지)를 보여주지 않고 섹션별 고정 문구만 보여준다.
    const failures = [
      { name: '500 + 고정 에러 형태', reply: mockReply.apiError(mockServerFailure) },
      { name: '500 + 깨진 본문', reply: mockReply.malformed(500) },
      { name: '200 + 깨진 본문', reply: mockReply.malformed(200) },
      { name: '네트워크 오류', reply: mockReply.networkError() },
    ];

    for (const failure of failures) {
      test(`${failure.name}이면 지수·랭킹 영역이 오류를 알린다`, async ({ api, home }) => {
        await api.guest();
        await api.homePage({ market: failure.reply });

        await home.open();

        await expect(home.indexError).toBeVisible();
        await expect(home.rankingError).toBeVisible();
      });
    }
  });

  test.describe('종목 개요 요청 실패', () => {
    const { stock } = mockStockOverview();
    const failures = [
      {
        name: '500 + 고정 에러 형태면 서버 메시지',
        reply: mockReply.apiError(mockServerFailure),
        message: mockServerFailure.body.error.message,
      },
      {
        name: '500 + 깨진 본문이면 기본 오류 문구',
        reply: mockReply.malformed(500),
        message: apiFallbackMessages.unreadableErrorBody,
      },
      {
        name: '200 + 깨진 본문이면 해석 실패 문구',
        reply: mockReply.malformed(200),
        message: apiFallbackMessages.unparsableBody,
      },
      {
        name: '네트워크 오류면 연결 실패 문구',
        reply: mockReply.networkError(),
        message: apiFallbackMessages.networkError,
      },
    ];

    for (const failure of failures) {
      test(`${failure.name}를 보여준다`, async ({ api, stockPage }) => {
        await api.guest();
        await api.stockPage(stock.code, { overview: failure.reply });

        await stockPage.open(stock.code);

        await expect(stockPage.loadError).toBeVisible();
        await expect(stockPage.messageInMain(failure.message)).toBeVisible();
      });
    }

    test('404 STOCK_NOT_FOUND 면 서버 메시지 대신 서비스하지 않는 종목이라고 안내한다', async ({
      api,
      stockPage,
    }) => {
      const notFound = mockApiErrors.stockNotFound();
      await api.guest();
      await api.stockPage(stock.code, { overview: mockReply.apiError(notFound) });

      await stockPage.open(stock.code);

      await expect(stockPage.notServicedNotice).toBeVisible();
      // 다른 실패와 달리 서버 메시지를 그대로 보여주지 않는다.
      await expect(stockPage.messageInMain(notFound.body.error.message)).toBeHidden();
    });
  });

  test.describe('종목 브리핑 일부 요청 실패', () => {
    const { stock } = mockStockOverview();

    test('주가 요청이 500 이면 차트가 오류를 알리고 종목명은 그대로 보인다', async ({
      api,
      stockPage,
    }) => {
      await api.guest();
      await api.stockPage(stock.code, { prices: mockReply.apiError(mockApiErrors.internal()) });

      await stockPage.open(stock.code);

      await expect(stockPage.title(stock.name)).toBeVisible();
      await expect(stockPage.chartError).toBeVisible();
    });

    test('재무 요청이 500 이면 재무 지표 자리에 조회 실패를 알리고 종목명은 그대로 보인다', async ({
      api,
      stockPage,
    }) => {
      await api.guest();
      await api.stockPage(stock.code, {
        financials: mockReply.apiError(mockApiErrors.internal()),
      });

      await stockPage.open(stock.code);

      await expect(stockPage.title(stock.name)).toBeVisible();
      await expect(stockPage.financialsFailedTags).not.toHaveCount(0);
    });
  });
});
