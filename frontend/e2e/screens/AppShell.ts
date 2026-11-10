import type { Locator, Page } from '@playwright/test';
import { appHeader, appMain } from './landmarks';
import { LoginDialog } from './LoginDialog';

/** App.tsx 에 없는 경로. 404 화면 확인용 */
const UNKNOWN_PATH = '/no-such-path';

/** 모든 화면에 공통인 틀과 동작 (src/components/layout/PageShell.tsx, Header.tsx) */
export class AppShell {
  readonly header: Locator;
  /** 헤더를 뺀 본문 영역 */
  readonly main: Locator;
  readonly loginButton: Locator;
  readonly logoutButton: Locator;
  readonly myPageLink: Locator;
  readonly loginDialog: LoginDialog;

  private readonly page: Page;

  constructor(page: Page) {
    this.page = page;
    this.header = appHeader(page);
    this.main = appMain(page);
    this.loginButton = this.header.getByRole('button', { name: '로그인', exact: true });
    this.logoutButton = this.header.getByRole('button', { name: '로그아웃', exact: true });
    this.myPageLink = this.header.getByRole('link', { name: '마이페이지', exact: true });
    this.loginDialog = new LoginDialog(page);
  }

  async logout(): Promise<void> {
    await this.logoutButton.click();
  }

  /** 지금 주소 그대로 새로고침한다. 어느 화면이든 이것을 쓴다 */
  async reload(): Promise<void> {
    await this.page.reload();
  }

  async openUnknownPath(): Promise<void> {
    await this.page.goto(UNKNOWN_PATH);
  }
}
