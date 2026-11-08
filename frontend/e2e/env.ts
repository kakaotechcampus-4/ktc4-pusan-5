/**
 * E2E 가 붙는 주소. playwright.config.ts 와 테스트 코드가 같은 값을 쓰도록 여기서만 읽는다.
 *
 * - E2E_BASE_URL: 프론트 주소. 지정하지 않으면 playwright.config.ts 의 webServer 가 띄우는 vite(5174)
 * - E2E_API_URL: 백엔드 주소. vite 에 VITE_API_BASE_URL 로 주입되고, 목업이 가로챌 주소도 이것이다
 */

/** webServer 가 vite 를 띄우는 포트. 평소 개발 서버(5173)와 겹치지 않게 따로 둔다 */
export const E2E_DEV_SERVER_PORT = 5174;

/** 끝의 / 와 기본 포트 표기 차이로 주소 비교가 어긋나지 않게 맞춘다 */
function normalizeBaseUrl(raw: string): string {
  const url = new URL(raw);
  return `${url.origin}${url.pathname}`.replace(/\/+$/, '');
}

/** E2E_BASE_URL 을 직접 지정했는지. 지정했으면 webServer 를 띄우지 않고 그 프론트를 쓴다 */
export const E2E_EXTERNAL_FRONTEND = process.env.E2E_BASE_URL !== undefined;

export const E2E_BASE_URL = normalizeBaseUrl(
  process.env.E2E_BASE_URL ?? `http://localhost:${E2E_DEV_SERVER_PORT}`,
);

export const E2E_API_URL = normalizeBaseUrl(process.env.E2E_API_URL ?? 'http://localhost:8001');
