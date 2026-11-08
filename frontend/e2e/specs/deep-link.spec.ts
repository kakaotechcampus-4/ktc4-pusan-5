/**
 * 딥링크·404 (목업)
 * 주소를 직접 입력하거나 새로고침해도 화면이 제대로 열리는지, 없는 대상은 오류를 보여주는지 본다.
 */
import { expect, TAG, test } from '../fixtures/test';
import {
  apiEndpoints,
  mockApiErrors,
  mockReply,
  mockStockOverview,
  mockUnknownConceptSlug,
  mockUnknownStockCode,
} from '../mocks';

test.describe('딥링크·404', { tag: TAG.core }, () => {
  test('종목 브리핑 주소로 바로 들어와도 종목이 보이고, 새로고침해도 유지된다', async ({
    api,
    shell,
    stockPage,
  }) => {
    const { code, name } = mockStockOverview().stock;
    await api.guest();
    await api.stockPage(code);

    await stockPage.open(code);
    await expect(stockPage.title(name)).toBeVisible();

    await shell.reload();
    await expect(stockPage.title(name)).toBeVisible();
  });

  test('서비스하지 않는 종목 코드로 들어오면 오류 화면과 종목 목록 버튼을 보여준다', async ({
    api,
    stockPage,
  }) => {
    await api.guest();
    await api.stockPage(mockUnknownStockCode, {
      overview: mockReply.apiError(mockApiErrors.stockNotFound()),
      prices: mockReply.apiError(mockApiErrors.stockNotFound()),
      financials: mockReply.apiError(mockApiErrors.stockNotFound()),
    });

    await stockPage.open(mockUnknownStockCode);

    await expect(stockPage.notServicedNotice).toBeVisible();
    await expect(stockPage.stockListButton).toBeVisible();
  });

  test('없는 개념 주소로 들어오면 찾을 수 없다고 안내한다', async ({ api, conceptPage }) => {
    const notFound = mockApiErrors.conceptNotFound();
    await api.guest();
    await api.reply(apiEndpoints.concept(mockUnknownConceptSlug), mockReply.apiError(notFound));

    await conceptPage.open(mockUnknownConceptSlug);

    await expect(conceptPage.notFoundTitle).toBeVisible();
    await expect(conceptPage.conceptListButton).toBeVisible();
    // 안내는 화면이 정한 문구다. 서버 메시지를 그대로 쓰지 않는다.
    await expect(conceptPage.messageInMain(notFound.body.error.message)).toBeHidden();
  });

  test('없는 경로로 들어와도 본문이 비어 있지 않다', async ({ api, shell }) => {
    // 404 라우트가 생기면 아래 test.fail(...) 줄을 지운다.
    // 주의: test.fail 은 단언 실패만이 아니라 감시 fixture 의 실패(console.error, 예상 못한 HTTP 오류,
    // 목업하지 않은 요청)도 "예상한 실패"로 받아 가린다. 표시를 지우기 전까지 이 테스트의 초록은
    // "본문이 비어 있다"는 뜻일 뿐 다른 회귀가 없다는 뜻이 아니다.
    test.fail(true, 'App.tsx 에 404 라우트(path="*")가 없어 본문(main)이 비어 있다');
    await api.guest();

    await shell.openUnknownPath();

    // 정적 화면이라 오래 기다릴 이유가 없다. 실패가 정상인 동안 매번 기본 5초를 쓰지 않게 줄인다.
    await expect(shell.main).toHaveText(/\S/, { useInnerText: true, timeout: 2_000 });
  });
});
