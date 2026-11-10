/**
 * 로그인·세션·권한
 * - @backend: 실제 백엔드 테스트 로그인으로 로그인 → 새로고침 유지 → 로그아웃
 * - 목업: 비로그인 사용자가 로그인이 필요한 곳에 가면 로그인으로 안내되는지
 *
 * 헤더에는 닉네임 표시가 없다(로그아웃 버튼·마이페이지 링크만 바뀐다).
 * 그래서 닉네임은 마이페이지 프로필에서 확인한다.
 * 헤더 로그인 버튼은 세션 확인 중(loading)에도 보인다. 비로그인 확정은 마이페이지 본문의
 * 로그인 유도 버튼(myPage.loginPromptButton)으로 먼저 확인한다.
 * 로그인 중 세션 만료(다른 API 의 401) 처리는 앱에 정의돼 있지 않아 테스트로 굳히지 않는다.
 */
import { expect, TAG, test } from '../fixtures/test';
import { apiEndpoints, mockStockOverview } from '../mocks';

test.describe('로그인·세션', { tag: TAG.core }, () => {
  test(
    '테스트 계정으로 로그인하면 새로고침해도 유지되고, 로그아웃하면 비로그인 화면이 된다',
    { tag: TAG.backend },
    async ({ testAccount, shell, myPage, pageMonitor }) => {
      await myPage.open();
      await expect(shell.logoutButton).toBeVisible();
      await expect(shell.myPageLink).toBeVisible();
      await expect(myPage.nickname(testAccount.nickname)).toBeVisible();

      await shell.reload();
      await expect(shell.logoutButton).toBeVisible();
      await expect(myPage.nickname(testAccount.nickname)).toBeVisible();

      await shell.logout();
      await expect(myPage.loginPromptButton).toBeVisible();
      await expect(shell.loginButton).toBeVisible();
      await expect(shell.myPageLink).toBeHidden();

      // 로그아웃 뒤 새로고침하면 세션 확인이 401 로 끝나는 것이 정상이다.
      pageMonitor.allowHttpError(apiEndpoints.authMe, 401);
      await shell.reload();
      // 세션 확인이 비로그인으로 끝나야 보이는 버튼을 먼저 기다린다. 확인 중 화면만으로 통과하지 않게 한다.
      await expect(myPage.loginPromptButton).toBeVisible();
      await expect(shell.loginButton).toBeVisible();
      await expect(myPage.nickname(testAccount.nickname)).toBeHidden();
    },
  );
});

test.describe('로그인이 필요한 기능', { tag: TAG.core }, () => {
  test('비로그인으로 마이페이지에 가면 로그인을 안내하고, 누르면 로그인 창이 열린다', async ({
    api,
    shell,
    myPage,
  }) => {
    await api.guest();

    await myPage.open();
    await myPage.loginPromptButton.click();

    await expect(shell.loginDialog.kakaoLoginButton).toBeVisible();
  });

  test('비로그인으로 종목 브리핑의 관심 종목 버튼을 누르면 로그인 창이 열린다', async ({
    api,
    shell,
    stockPage,
  }) => {
    const { code, name } = mockStockOverview().stock;
    await api.guest();
    await api.stockPage(code);

    await stockPage.open(code);
    await expect(stockPage.title(name)).toBeVisible();
    await stockPage.watchlistButton.click();

    await expect(shell.loginDialog.kakaoLoginButton).toBeVisible();
  });
});
