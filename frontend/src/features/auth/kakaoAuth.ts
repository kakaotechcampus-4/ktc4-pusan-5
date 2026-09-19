const KAKAO_AUTH_URL = 'https://kauth.kakao.com/oauth/authorize';
const STATE_STORAGE_KEY = 'kakao_oauth_state';

// 로그인 시작마다 새 state를 만들어 sessionStorage에 저장하고 인가 URL에 보냄
// CSRF 방지
export function buildKakaoAuthUrl(): string {
  const state = crypto.randomUUID();
  sessionStorage.setItem(STATE_STORAGE_KEY, state);

  const params = new URLSearchParams({
    client_id: import.meta.env.VITE_KAKAO_CLIENT_ID,
    redirect_uri: import.meta.env.VITE_KAKAO_REDIRECT_URI,
    response_type: 'code',
    state,
  });
  return `${KAKAO_AUTH_URL}?${params.toString()}`;
}

// 로그인 시작 시 저장해둔 state를 읽기
export function peekStoredState(): string | null {
  return sessionStorage.getItem(STATE_STORAGE_KEY);
}

// state 확인이 끝나면 지움(일회용 값)
export function clearStoredState(): void {
  sessionStorage.removeItem(STATE_STORAGE_KEY);
}
