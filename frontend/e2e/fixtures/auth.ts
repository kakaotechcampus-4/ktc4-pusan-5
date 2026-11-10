/**
 * 실제 백엔드의 테스트 로그인. (@backend 테스트 전용)
 *
 * POST /api/auth/test-login 은 백엔드를 ENABLE_TEST_LOGIN=true 로 띄웠을 때만 동작하고,
 * 항상 같은 테스트 계정으로 로그인시킨다. (backend/app/routers/auth.py)
 * 응답의 httponly 쿠키 access_token 은 page.request 가 브라우저 컨텍스트와 공유하므로
 * 이후 page.goto 부터 로그인한 상태로 화면이 열린다.
 */
import { expect, type APIRequestContext } from '@playwright/test';
import type { User } from '../../src/lib/types';
import { apiEndpoints, apiUrl } from '../mocks/apiPaths';

export async function loginAsTestAccount(request: APIRequestContext): Promise<User> {
  const response = await request.post(apiUrl(apiEndpoints.testLogin));
  expect(
    response.status(),
    '테스트 로그인 실패. 백엔드를 ENABLE_TEST_LOGIN=true 로 띄웠는지, E2E_API_URL 이 맞는지 확인한다',
  ).toBe(200);
  return (await response.json()) as User;
}
