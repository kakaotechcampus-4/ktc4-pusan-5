/**
 * 로딩 상태 (목업)
 * 응답을 테스트가 붙잡아 두는 동안에는 본문도 오류도 없고, 풀어 주면 본문이 보이는지 본다.
 * 타이머로 늦추지 않으므로 로딩 화면을 원하는 만큼 확인할 수 있다.
 *
 * 홈 지수·종목 헤더 스켈레톤에는 접근 가능한 표식(role·이름)이 없어 스켈레톤 자체는 확인하지 않는다.
 * 대신 대기 중에 오류 화면이 먼저 뜨지 않는지를 함께 본다. 재무 추이 스켈레톤만 role=status 이름이 있어
 * 그것을 확인한다.
 */
import { expect, TAG, test } from '../fixtures/test';
import {
  apiEndpoints,
  mockMarketOverview,
  mockReply,
  mockStockFinancials,
  mockStockOverview,
} from '../mocks';

test.describe('로딩 상태', { tag: TAG.core }, () => {
  test('홈: 시세 응답 전에는 지수가 없고, 응답이 오면 지수가 보인다', async ({ api, home }) => {
    const market = mockMarketOverview();
    const indexName = market.items[0].name;
    await api.guest();
    await api.homePage();
    const heldMarket = await api.hold(apiEndpoints.marketOverview, mockReply.ok(market));

    await home.open();
    await heldMarket.waitForRequest();
    await expect(home.marketItem(indexName)).toBeHidden();
    await expect(home.indexError).toBeHidden();

    heldMarket.release();
    await expect(home.marketItem(indexName)).toBeVisible();
  });

  test('종목 브리핑: 개요 응답 전에는 종목명이 없고, 응답이 오면 보인다', async ({
    api,
    stockPage,
  }) => {
    const overview = mockStockOverview();
    const { code, name } = overview.stock;
    await api.guest();
    await api.stockPage(code);
    const heldOverview = await api.hold(apiEndpoints.stockOverview(code), mockReply.ok(overview));

    await stockPage.open(code);
    await heldOverview.waitForRequest();
    await expect(stockPage.title(name)).toBeHidden();
    await expect(stockPage.loadError).toBeHidden();

    heldOverview.release();
    await expect(stockPage.title(name)).toBeVisible();
  });

  test('종목 브리핑: 재무 응답 전에는 재무 추이가 불러오는 중이고, 응답이 오면 표가 보인다', async ({
    api,
    stockPage,
  }) => {
    const { code, name } = mockStockOverview().stock;
    await api.guest();
    await api.stockPage(code);
    const heldFinancials = await api.hold(
      apiEndpoints.stockFinancials(code),
      mockReply.ok(mockStockFinancials({ code })),
    );

    await stockPage.open(code);
    await expect(stockPage.title(name)).toBeVisible();
    await heldFinancials.waitForRequest();
    await stockPage.openDetailInfoTab();
    await expect(stockPage.financialsLoadingStatus).toBeVisible();

    heldFinancials.release();
    await expect(stockPage.financialTrendRevenueRow).toBeVisible();
    await expect(stockPage.financialsLoadingStatus).toBeHidden();
  });
});
