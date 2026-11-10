import { expect, type Locator, type Page } from '@playwright/test';
import { appMain } from './landmarks';

const HOME_PATH = '/';

/**
 * 홈 (src/features/home).
 * 시세(GET /api/market/overview) 실패 시 화면은 서버 메시지를 쓰지 않고 섹션별 고정 문구를 보여준다.
 */
export class HomeScreen {
  readonly indexError: Locator;
  readonly rankingError: Locator;

  private readonly page: Page;
  private readonly main: Locator;

  constructor(page: Page) {
    this.page = page;
    this.main = appMain(page);
    this.indexError = this.main.getByText('지수 정보를 갱신하지 못했습니다', { exact: true });
    this.rankingError = this.main.getByText('랭킹을 갱신하지 못했습니다', { exact: true });
  }

  async open(): Promise<void> {
    await this.page.goto(HOME_PATH);
  }

  /** 다른 화면에서 홈으로 옮겨 왔는지 확인한다 (예: 로그인 콜백 뒤) */
  async expectOpened(): Promise<void> {
    await expect(this.page).toHaveURL((url) => url.pathname === HOME_PATH);
  }

  /** 주요 지수 타일의 지수 이름 */
  marketItem(name: string): Locator {
    return this.main.getByText(name, { exact: true });
  }
}
