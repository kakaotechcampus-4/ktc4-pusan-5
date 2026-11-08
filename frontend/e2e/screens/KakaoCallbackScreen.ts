import type { Locator, Page } from '@playwright/test';
import { appMain } from './landmarks';

const CALLBACK_PATH = '/oauth/kakao/callback';

/**
 * 로그인 시작 때 state 를 저장하는 sessionStorage 키. src/features/auth/kakaoAuth.ts 의
 * STATE_STORAGE_KEY 와 같아야 한다. (export 되지 않아 가져올 수 없어 값을 맞춰 둔다)
 */
const STATE_STORAGE_KEY = 'kakao_oauth_state';

/** state 를 한 번만 심었는지 표시하는 키. 새로고침 때 다시 심으면 "새로고침" 시나리오가 깨진다 */
const SEEDED_MARKER_KEY = 'e2e_kakao_oauth_state_seeded';

/** 카카오 로그인 콜백 (src/features/auth/KakaoCallbackPage.tsx) */
export class KakaoCallbackScreen {
  readonly failureTitle: Locator;
  readonly missingCodeMessage: Locator;
  readonly unverifiedRequestMessage: Locator;
  /** 401 KAKAO_AUTH_FAILED 는 서버 문구 대신 화면이 정한 문구로 바꿔 보여준다 */
  readonly kakaoAuthFailedMessage: Locator;

  private readonly page: Page;

  constructor(page: Page) {
    this.page = page;
    const main = appMain(page);
    this.failureTitle = main.getByText('로그인에 실패했습니다', { exact: true });
    this.missingCodeMessage = main.getByText('카카오 인증 코드를 받지 못했습니다', {
      exact: true,
    });
    this.unverifiedRequestMessage = main.getByText(
      '로그인 요청을 확인할 수 없습니다. 처음부터 다시 시도해주세요',
      { exact: true },
    );
    this.kakaoAuthFailedMessage = main.getByText('카카오 인증에 실패했습니다', { exact: true });
  }

  /**
   * 로그인 버튼을 눌러 카카오로 떠났다가 돌아온 상태를 만든다.
   * 페이지가 처음 열릴 때 한 번만 sessionStorage 에 state 를 심는다.
   */
  async seedStoredState(state: string): Promise<void> {
    await this.page.addInitScript(
      ({ storageKey, markerKey, value }) => {
        try {
          if (window.sessionStorage.getItem(markerKey)) return;
          window.sessionStorage.setItem(storageKey, value);
          window.sessionStorage.setItem(markerKey, 'true');
        } catch {
          // about:blank 처럼 저장소를 쓸 수 없는 문서에서는 건너뛴다
        }
      },
      { storageKey: STATE_STORAGE_KEY, markerKey: SEEDED_MARKER_KEY, value: state },
    );
  }

  /** 카카오가 돌려보내는 주소로 들어온다 */
  async open(params: { code?: string; state?: string }): Promise<void> {
    const query = new URLSearchParams();
    if (params.code !== undefined) query.set('code', params.code);
    if (params.state !== undefined) query.set('state', params.state);
    const search = query.toString();
    await this.page.goto(`${CALLBACK_PATH}${search ? `?${search}` : ''}`);
  }

  /**
   * seedStoredState 로 심은 state 가 실제로 심겼고, 화면이 그 키를 읽고 지웠는지.
   * 위조 state 시나리오에서 "저장값이 없다"가 아니라 "저장값과 다르다"였음을 보이는 데 쓴다.
   */
  async storedStateWasConsumed(): Promise<boolean> {
    return this.page.evaluate(
      ({ storageKey, markerKey }) =>
        window.sessionStorage.getItem(markerKey) === 'true' &&
        window.sessionStorage.getItem(storageKey) === null,
      { storageKey: STATE_STORAGE_KEY, markerKey: SEEDED_MARKER_KEY },
    );
  }

  /**
   * 화면이 보낼 요청을 다 보낼 때까지 기다린다. "교환 요청이 (더) 나가지 않았다"를 단언하기 전에 부른다.
   * 요청이 없다는 것을 알려 주는 이벤트가 없어서 networkidle(500ms 동안 요청 없음)을 쓴다.
   * 콜백 오류 화면에는 짧은 주기의 요청이 없어 오래 걸리지 않는다. 그런 요청이 생기면 이 방식을 다시 본다.
   * 요청이 한 번 나가야 결과가 보이는 경우(401·성공)는 화면 결과만 기다리면 되므로 부르지 않는다.
   */
  async waitForRequestsToSettle(): Promise<void> {
    await this.page.waitForLoadState('networkidle');
  }
}
