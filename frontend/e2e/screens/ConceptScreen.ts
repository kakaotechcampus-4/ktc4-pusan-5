import type { Locator, Page } from '@playwright/test';
import { appMain } from './landmarks';

/** 개념 상세 (src/features/concepts/ConceptPage.tsx, ConceptDetail.tsx) */
export class ConceptScreen {
  /** 404 CONCEPT_NOT_FOUND 일 때의 안내. 서버 메시지 대신 화면이 정한 문구다 */
  readonly notFoundTitle: Locator;
  readonly conceptListButton: Locator;

  private readonly page: Page;
  private readonly main: Locator;

  constructor(page: Page) {
    this.page = page;
    this.main = appMain(page);
    this.notFoundTitle = this.main.getByText('개념을 찾을 수 없습니다', { exact: true });
    this.conceptListButton = this.main.getByRole('button', { name: '개념 목록으로', exact: true });
  }

  async open(slug: string): Promise<void> {
    await this.page.goto(`/concepts/${encodeURIComponent(slug)}`);
  }

  /** 본문에 보이는 문구. 서버 메시지를 화면에 그대로 썼는지 확인할 때 쓴다 */
  messageInMain(message: string): Locator {
    return this.main.getByText(message, { exact: true });
  }
}
