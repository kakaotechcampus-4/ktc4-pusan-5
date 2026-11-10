/** 로그인 관련 목업. 타입은 src/lib/types.ts 를 그대로 쓴다 */
import type { User } from '../../src/lib/types';

export function mockUser(overrides: Partial<User> = {}): User {
  return { id: 1, nickname: '목업 사용자', ...overrides };
}

/** 카카오가 콜백 주소로 넘겨주는 인가 코드 자리 */
export const mockKakaoCode = 'mock-kakao-authorization-code';

/** 로그인 시작 때 저장해 두는 CSRF state 자리 */
export const mockOAuthState = 'mock-oauth-state';

/** 저장해 둔 state 와 다른 값. 위조된 콜백을 흉내낸다 */
export const mockForgedOAuthState = 'mock-forged-oauth-state';

/**
 * 앱이 교환 요청(POST /api/auth/kakao)에 담아야 하는 본문. src/lib/api.ts 의 loginWithKakao 와 같은 모양.
 * 요청 본문 타입은 src 에서 export 되지 않아 여기서 모양을 맞춘다.
 */
export function mockKakaoExchangeBody(code: string = mockKakaoCode): { code: string } {
  return { code };
}
