/**
 * 테스트 태그. package.json 의 e2e:mock 스크립트가 '@backend' 를 문자열로 거르므로 값을 바꾸면 거기도 고친다.
 *
 * - core: 1단계 핵심 시나리오
 * - backend: 실제 백엔드가 떠 있어야 하는 테스트. 이 태그가 없으면 API 요청은 전부 목업이어야 한다
 */
export const TAG = {
  core: '@core',
  backend: '@backend',
} as const;
