import type { Locator, Page } from '@playwright/test';

/** 로그인 모달 (src/features/auth/LoginModal.tsx). 헤더·마이페이지·관심 종목 버튼이 연다 */
export class LoginDialog {
  readonly dialog: Locator;
  readonly kakaoLoginButton: Locator;

  constructor(page: Page) {
    this.dialog = page.getByRole('dialog');
    this.kakaoLoginButton = this.dialog.getByRole('button', { name: '카카오로 로그인' });
  }
}
