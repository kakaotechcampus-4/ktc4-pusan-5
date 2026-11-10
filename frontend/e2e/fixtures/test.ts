/**
 * spec 은 @playwright/test 대신 여기서 test·expect 를 가져온다.
 *
 * 자동으로 켜지는 것
 *   - pageMonitor: 콘솔·네트워크 감시. 테스트 끝에 문제가 있으면 실패
 *   - api: API 목업. @backend 태그가 없으면 목업하지 않은 API 요청을 막고 실패.
 *     E2E_API_URL 이 아닌 주소로 나간 API 요청은 태그와 상관없이 막고 실패
 * 필요할 때 받는 것
 *   - testAccount: 실제 백엔드 테스트 로그인 (@backend 전용)
 *   - shell·home·stockPage·myPage·kakaoCallback·conceptPage: 화면 객체 (screens/)
 *
 * fixture 두 번째 인자 이름을 use 대신 provide 로 둔다.
 * React 의 use 훅으로 오인한 eslint-plugin-react-hooks 가 에러를 내기 때문이다.
 */
import { test as base, expect } from '@playwright/test';
import type { User } from '../../src/lib/types';
import { AppShell } from '../screens/AppShell';
import { ConceptScreen } from '../screens/ConceptScreen';
import { HomeScreen } from '../screens/HomeScreen';
import { KakaoCallbackScreen } from '../screens/KakaoCallbackScreen';
import { MyPageScreen } from '../screens/MyPageScreen';
import { StockBriefingScreen } from '../screens/StockBriefingScreen';
import { ApiMock } from './apiMock';
import { loginAsTestAccount } from './auth';
import { PageMonitor } from './pageMonitor';
import { TAG } from './tags';

type E2EFixtures = {
  pageMonitor: PageMonitor;
  api: ApiMock;
  testAccount: User;
  shell: AppShell;
  home: HomeScreen;
  stockPage: StockBriefingScreen;
  myPage: MyPageScreen;
  kakaoCallback: KakaoCallbackScreen;
  conceptPage: ConceptScreen;
};

export const test = base.extend<E2EFixtures>({
  pageMonitor: [
    async ({ page }, provide) => {
      const monitor = new PageMonitor(page);
      await provide(monitor);
      monitor.assertNoProblems();
    },
    { auto: true },
  ],

  api: [
    async ({ page, pageMonitor }, provide, testInfo) => {
      const api = new ApiMock(page, pageMonitor);
      await api.blockMisdirectedRequests();
      if (!testInfo.tags.includes(TAG.backend)) await api.blockUnmockedRequests();
      await provide(api);
      await api.finish();
    },
    { auto: true },
  ],

  testAccount: async ({ page }, provide) => {
    await provide(await loginAsTestAccount(page.request));
  },

  shell: async ({ page }, provide) => {
    await provide(new AppShell(page));
  },
  home: async ({ page }, provide) => {
    await provide(new HomeScreen(page));
  },
  stockPage: async ({ page }, provide) => {
    await provide(new StockBriefingScreen(page));
  },
  myPage: async ({ page }, provide) => {
    await provide(new MyPageScreen(page));
  },
  kakaoCallback: async ({ page }, provide) => {
    await provide(new KakaoCallbackScreen(page));
  },
  conceptPage: async ({ page }, provide) => {
    await provide(new ConceptScreen(page));
  },
});

export { expect, TAG };
