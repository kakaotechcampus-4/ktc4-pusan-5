/**
 * Playwright E2E 설정. 테스트 코드는 e2e/ 에 있다.
 *   npm run e2e          전체 (실제 백엔드가 필요한 @backend 포함)
 *   npm run e2e:mock     @backend 를 뺀 목업 시나리오만. 백엔드 없이 돈다
 *   npm run e2e:typecheck
 *
 * 주소는 env 로 바꾼다. (e2e/env.ts)
 *   E2E_API_URL  백엔드 주소. 기본 http://localhost:8001. 목업도 이 주소로 나가는 요청을 가로챈다.
 *   E2E_BASE_URL 프론트 주소. 지정하지 않으면 아래 webServer 가 vite 를 5174 로 띄우고
 *                VITE_API_BASE_URL=E2E_API_URL 을 주입한다.
 *                지정하면 webServer 를 띄우지 않는다. 그 프론트는 VITE_API_BASE_URL=E2E_API_URL 로
 *                떠 있어야 한다(아니면 요청이 frontend/.env 의 주소로 나간다).
 *
 * 로컬에서는 이미 떠 있는 5174 서버를 재사용한다(reuseExistingServer). 그 서버가 다른 env 로 떴다면
 * 앱이 E2E_API_URL 이 아닌 곳을 부르게 되고, 그런 요청은 e2e/fixtures/apiMock.ts 가 끊고 테스트를 실패시킨다.
 */
import { defineConfig, devices } from '@playwright/test';
import { E2E_API_URL, E2E_BASE_URL, E2E_DEV_SERVER_PORT, E2E_EXTERNAL_FRONTEND } from './e2e/env';

const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: 'e2e/specs',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  reporter: isCI ? [['list'], ['html', { open: 'never' }]] : 'list',

  use: {
    baseURL: E2E_BASE_URL,
    timezoneId: 'Asia/Seoul',
    locale: 'ko-KR',
    trace: 'on-first-retry',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  webServer: E2E_EXTERNAL_FRONTEND
    ? undefined
    : {
        command: `npx vite --port ${E2E_DEV_SERVER_PORT} --strictPort`,
        url: E2E_BASE_URL,
        reuseExistingServer: !isCI,
        timeout: 120_000,
        env: {
          // 앱이 부를 백엔드 주소. 목업 시나리오도 이 주소로 나가는 요청을 가로챈다.
          VITE_API_BASE_URL: E2E_API_URL,
          // .env.local 등에 VITE_USE_MOCK=true 가 있어도 앱 내장 목업 대신 실제 API 경로를 타게 한다.
          VITE_USE_MOCK: 'false',
        },
      },
});
