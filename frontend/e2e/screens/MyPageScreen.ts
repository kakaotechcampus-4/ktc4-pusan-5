import type { Locator, Page } from '@playwright/test';
import { appMain } from './landmarks';

/** 마이페이지 (src/features/mypage/MyPage.tsx) */
export class MyPageScreen {
  /**
   * 비로그인일 때 본문에 나오는 로그인 유도 버튼. 헤더의 로그인 버튼과는 다르다.
   * 세션 확인이 "비로그인"으로 끝났을 때만 그려진다(확인 중에는 스켈레톤). 그래서 이 버튼이 보이면
   * 비로그인이 확정된 것이다. 헤더 로그인 버튼은 확인 중에도 보여 그 근거가 되지 못한다.
   */
  readonly loginPromptButton: Locator;

  private readonly page: Page;
  private readonly main: Locator;

  constructor(page: Page) {
    this.page = page;
    this.main = appMain(page);
    this.loginPromptButton = this.main.getByRole('button', { name: '로그인', exact: true });
  }

  async open(): Promise<void> {
    await this.page.goto('/mypage');
  }

  /** 프로필 띠에 보이는 닉네임 */
  nickname(name: string): Locator {
    return this.main.getByText(name, { exact: true });
  }
}
