/**
 * 카카오 로그인 콜백 (목업)
 * 카카오가 돌려보낸 주소의 code·state 를 화면이 어떻게 다루는지 본다.
 * 인가 코드는 1회용이라 같은 code 로 교환 요청(POST /api/auth/kakao)이 두 번 나가면 안 된다.
 * 교환 요청은 횟수만이 아니라 본문(URL 의 code 를 그대로 보냈는지)까지 확인한다.
 */
import { expect, TAG, test } from '../fixtures/test';
import {
  apiEndpoints,
  mockApiErrors,
  mockForgedOAuthState,
  mockKakaoCode,
  mockKakaoExchangeBody,
  mockOAuthState,
  mockReply,
  mockUser,
  mockWatchlist,
} from '../mocks';

test.describe('카카오 로그인 콜백', { tag: TAG.core }, () => {
  test('code 없이 돌아오면 오류를 보여주고 교환 요청을 보내지 않는다', async ({
    api,
    kakaoCallback,
  }) => {
    await api.guest();
    const kakaoLogin = await api.reply(apiEndpoints.kakaoLogin, mockReply.ok(mockUser()));
    await kakaoCallback.seedStoredState(mockOAuthState);

    await kakaoCallback.open({ state: mockOAuthState });

    await expect(kakaoCallback.failureTitle).toBeVisible();
    await expect(kakaoCallback.missingCodeMessage).toBeVisible();
    await kakaoCallback.waitForRequestsToSettle();
    expect(kakaoLogin.calls).toBe(0);
  });

  test('state 가 저장한 값과 다르면 오류를 보여주고 교환 요청을 보내지 않는다', async ({
    api,
    kakaoCallback,
  }) => {
    await api.guest();
    const kakaoLogin = await api.reply(apiEndpoints.kakaoLogin, mockReply.ok(mockUser()));
    await kakaoCallback.seedStoredState(mockOAuthState);

    await kakaoCallback.open({ code: mockKakaoCode, state: mockForgedOAuthState });

    await expect(kakaoCallback.unverifiedRequestMessage).toBeVisible();
    // 저장값이 "없어서"가 아니라 "달라서" 거절했는지: 심은 값이 있었고 화면이 그것을 읽고 지웠다.
    expect(await kakaoCallback.storedStateWasConsumed()).toBe(true);
    await kakaoCallback.waitForRequestsToSettle();
    expect(kakaoLogin.calls).toBe(0);
  });

  test('state 가 맞아도 교환이 401 KAKAO_AUTH_FAILED 면 카카오 인증 실패를 보여준다', async ({
    api,
    kakaoCallback,
  }) => {
    await api.guest();
    const kakaoLogin = await api.reply(
      apiEndpoints.kakaoLogin,
      mockReply.apiError(mockApiErrors.kakaoAuthFailed()),
    );
    await kakaoCallback.seedStoredState(mockOAuthState);

    await kakaoCallback.open({ code: mockKakaoCode, state: mockOAuthState });

    await expect(kakaoCallback.kakaoAuthFailedMessage).toBeVisible();
    expect(kakaoLogin.requestBodies).toEqual([mockKakaoExchangeBody()]);
  });

  test('교환에 성공하면 홈으로 이동한다', async ({ api, home, kakaoCallback }) => {
    // 로그인 상태(헤더 로그아웃 버튼)는 확인하지 않는다. 앱의 AuthProvider 가 첫 GET /api/auth/me 의
    // 늦은 401 로 교환 성공을 덮어써 비로그인으로 끝날 수 있다(경쟁 조건). 앱이 고쳐지면 단언을 더한다.
    await api.guest();
    // 로그인 상태로 홈에 도착하면 관심 종목을 부른다. 위 경쟁 조건이 고쳐져도 깨지지 않게 넣어 둔다.
    await api.homePage({ watchlist: mockReply.ok(mockWatchlist()) });
    const kakaoLogin = await api.reply(apiEndpoints.kakaoLogin, mockReply.ok(mockUser()));
    await kakaoCallback.seedStoredState(mockOAuthState);

    await kakaoCallback.open({ code: mockKakaoCode, state: mockOAuthState });

    await home.expectOpened();
    expect(kakaoLogin.requestBodies).toEqual([mockKakaoExchangeBody()]);
  });

  test('콜백을 같은 code 로 새로고침하면 오류를 보여주고 교환 요청은 처음 한 번뿐이다', async ({
    api,
    shell,
    kakaoCallback,
  }) => {
    await api.guest();
    const kakaoLogin = await api.reply(
      apiEndpoints.kakaoLogin,
      mockReply.apiError(mockApiErrors.kakaoAuthFailed()),
    );
    await kakaoCallback.seedStoredState(mockOAuthState);
    await kakaoCallback.open({ code: mockKakaoCode, state: mockOAuthState });
    await expect(kakaoCallback.kakaoAuthFailedMessage).toBeVisible();

    await shell.reload();

    // 저장해 둔 state 는 첫 진입에서 지워졌으므로 같은 주소로 다시 와도 교환하지 않는다.
    await expect(kakaoCallback.unverifiedRequestMessage).toBeVisible();
    await kakaoCallback.waitForRequestsToSettle();
    expect(kakaoLogin.requestBodies).toEqual([mockKakaoExchangeBody()]);
  });
});
