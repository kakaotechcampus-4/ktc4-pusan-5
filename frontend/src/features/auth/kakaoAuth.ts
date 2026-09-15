const KAKAO_AUTH_URL = 'https://kauth.kakao.com/oauth/authorize';

export function buildKakaoAuthUrl(): string {
  const params = new URLSearchParams({
    client_id: import.meta.env.VITE_KAKAO_CLIENT_ID,
    redirect_uri: import.meta.env.VITE_KAKAO_REDIRECT_URI,
    response_type: 'code',
  });
  return `${KAKAO_AUTH_URL}?${params.toString()}`;
}
