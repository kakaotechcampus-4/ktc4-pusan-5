import type { Locator, Page } from '@playwright/test';
import { appMain } from './landmarks';

/** 종목 브리핑 (src/features/stock/StockBriefingPage.tsx) */
export class StockBriefingScreen {
  readonly watchlistButton: Locator;
  /** 개요를 못 불러왔을 때의 제목. 설명 자리에는 ApiError.message 가 들어간다 */
  readonly loadError: Locator;
  /** 404 STOCK_NOT_FOUND 일 때의 안내 */
  readonly notServicedNotice: Locator;
  readonly stockListButton: Locator;
  readonly chartError: Locator;
  /**
   * 재무 API 실패를 알리는 '조회 실패' 표시 중 보이는 것 전부.
   * 지금 기본 탭(AI 보고서)에서는 핵심 지표 카드의 두 행(영업이익 성장률·부채비율)에만 나온다.
   * 핵심 지표 카드는 제목이 heading 이 아니고(Kicker) 역할·이름이 없어 카드로 좁히지 못한다.
   * 그래서 본문 전체에서 찾고, 개수·순서에는 기대지 않는다. (data-testid 후보: AtAGlanceCard 루트)
   */
  readonly financialsFailedTags: Locator;
  readonly detailInfoTab: Locator;
  /** 상세 정보 탭의 재무 추이 스켈레톤. role=status 와 이름이 붙어 있다 */
  readonly financialsLoadingStatus: Locator;
  /**
   * 상세 정보 탭 재무 추이 표의 '매출액' 행 머리. 표는 연간 재무 데이터를 받았을 때만 그려진다.
   * (오류면 ErrorBox, 데이터가 없으면 Empty 로 바뀐다)
   */
  readonly financialTrendRevenueRow: Locator;

  private readonly page: Page;
  private readonly main: Locator;

  constructor(page: Page) {
    this.page = page;
    this.main = appMain(page);
    this.watchlistButton = this.main.getByRole('button', { name: '관심 종목', exact: true });
    this.loadError = this.main.getByText('종목을 불러오지 못했습니다', { exact: true });
    this.notServicedNotice = this.main.getByText('지금은 해당 종목을 서비스하지 않습니다', {
      exact: true,
    });
    this.stockListButton = this.main.getByRole('button', { name: '종목 목록으로', exact: true });
    this.chartError = this.main.getByText('주가 차트를 불러오지 못했습니다', { exact: true });
    this.financialsFailedTags = this.main
      .getByText('조회 실패', { exact: true })
      .filter({ visible: true });
    this.detailInfoTab = this.main.getByRole('tab', { name: '상세 정보', exact: true });
    this.financialsLoadingStatus = this.main.getByRole('status', {
      name: '재무 데이터 불러오는 중',
    });
    this.financialTrendRevenueRow = this.main.getByRole('rowheader', {
      name: '매출액',
      exact: true,
    });
  }

  async open(code: string): Promise<void> {
    await this.page.goto(`/stock/${encodeURIComponent(code)}`);
  }

  async openDetailInfoTab(): Promise<void> {
    await this.detailInfoTab.click();
  }

  /** 종목명 제목 */
  title(stockName: string): Locator {
    return this.main.getByRole('heading', { level: 1, name: stockName, exact: true });
  }

  /** 본문에 보이는 문구. 오류 화면이 서버 메시지(ApiError.message)를 썼는지 확인할 때 쓴다 */
  messageInMain(message: string): Locator {
    return this.main.getByText(message, { exact: true });
  }
}
