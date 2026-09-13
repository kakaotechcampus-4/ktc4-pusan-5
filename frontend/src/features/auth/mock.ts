/**
 * 카카오 로그인 목업.(로그인 버튼 동작만 확인)
 * 실제 연동 : 카카오 인가 코드를 받아 백엔드로 넘기고 세션을 발급받는 흐름
 */

export function mockKakaoLogin(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 800));
}

/** 에러 화면을 눈으로 확인하기 위해 LoginPage 에서 mockKakaoLogin 대신 사용 */
export function mockKakaoLoginError(): Promise<void> {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error('카카오 로그인 실패')), 800);
  });
}
