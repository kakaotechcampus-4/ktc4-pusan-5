import type { Locator, Page } from '@playwright/test';

/**
 * 모든 화면에 공통인 랜드마크 (src/components/layout/PageShell.tsx, Header.tsx).
 * 헤더는 banner, 본문은 main 역할로 찾는다. 틀이 바뀌면 여기만 고친다.
 */
export function appHeader(page: Page): Locator {
  return page.getByRole('banner');
}

/** 헤더를 뺀 본문 영역. 화면 객체는 요소를 이 안에서 찾는다 */
export function appMain(page: Page): Locator {
  return page.getByRole('main');
}
