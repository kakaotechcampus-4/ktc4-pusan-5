/**
 * API 목업. page.route 로 앱의 API 요청을 가로채 mocks/ 의 응답을 돌려준다.
 *
 * - 같은 엔드포인트를 다시 등록하면 나중 것이 이긴다. 프리셋(guest, homePage …)을 깔고
 *   테스트에 필요한 엔드포인트만 덮어쓴다.
 * - 오류 응답을 실제로 보낼 때 그 요청을 PageMonitor 에 "예상한 오류"로 알린다.
 * - @backend 가 아닌 테스트에서는 목업하지 않은 API 요청을 501 로 막고 테스트 끝에 실패시킨다.
 * - E2E_API_URL 이 아닌 주소로 나간 API 요청은 모든 테스트에서 끊고 테스트 끝에 실패시킨다.
 *   (앱이 VITE_API_BASE_URL=E2E_API_URL 로 떠 있지 않다는 뜻이다. playwright.config.ts 머리 주석 참고)
 */
import { expect, type Page, type Request, type Route } from '@playwright/test';
import {
  apiEndpoints,
  describeRequest,
  isApiRequestUrl,
  isEndpointUrl,
  isMisdirectedApiUrl,
  type ApiEndpoint,
} from '../mocks/apiPaths';
import { mockUser } from '../mocks/authMocks';
import { mockMarketOverview } from '../mocks/marketMocks';
import { mockApiErrors, mockMalformedBody, mockReply, type MockReply } from '../mocks/replies';
import { mockStockFinancials, mockStockOverview, mockStockPrices } from '../mocks/stockMocks';
import type {
  MarketOverview,
  StockFinancials,
  StockOverview,
  StockPriceResource,
  User,
  WatchlistResponse,
} from '../../src/lib/types';
import type { PageMonitor } from './pageMonitor';

/** 앱의 API 호출로 보는 리소스 종류. 글꼴·이미지 요청은 건드리지 않는다 */
const API_RESOURCE_TYPES = new Set(['fetch', 'xhr']);

export type MockedEndpoint = {
  /** 이 목업이 받은 요청 수 */
  readonly calls: number;
  /** 받은 요청의 본문. JSON 이면 파싱한 값, 본문이 없으면 null */
  readonly requestBodies: readonly unknown[];
};

export type HeldEndpoint = MockedEndpoint & {
  /** 첫 요청이 목업에 도착할 때까지 기다린다. 도착 전에는 화면이 아직 요청을 보내지 않은 것이다 */
  waitForRequest(): Promise<void>;
  /** 붙잡아 둔 응답을 보낸다. 이후 요청은 바로 응답한다 */
  release(): void;
};

type Gate = { opened: Promise<void>; open: () => void };

function createGate(): Gate {
  let open = () => {};
  const opened = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { opened, open };
}

function readRequestBody(request: Request): unknown {
  try {
    return request.postDataJSON();
  } catch {
    return request.postData();
  }
}

async function sendReply<TResponse>(route: Route, reply: MockReply<TResponse>): Promise<void> {
  switch (reply.kind) {
    case 'json':
    case 'apiError':
      await route.fulfill({ status: reply.status, json: reply.body });
      return;
    case 'malformed':
      await route.fulfill({
        status: reply.status,
        contentType: 'application/json',
        body: mockMalformedBody,
      });
      return;
    case 'networkError':
      await route.abort('connectionrefused');
      return;
  }
}

/**
 * 관심 종목(GET /api/watchlist)은 로그인했을 때만 불린다. 그래서 프리셋은 watchlist 를 넘겼을 때만 목업한다.
 * 비로그인 테스트에서 관심 종목을 조회하면 목업이 없어 "목업하지 않은 요청"으로 실패한다.
 */
type HomePageReplies = {
  market?: MockReply<MarketOverview>;
  watchlist?: MockReply<WatchlistResponse>;
};

type StockPageReplies = {
  overview?: MockReply<StockOverview>;
  prices?: MockReply<StockPriceResource>;
  financials?: MockReply<StockFinancials>;
  watchlist?: MockReply<WatchlistResponse>;
};

export class ApiMock {
  private readonly page: Page;
  private readonly monitor: PageMonitor;
  private readonly unmockedRequests: string[] = [];
  private readonly misdirectedRequests: string[] = [];
  private readonly gates: Gate[] = [];

  constructor(page: Page, monitor: PageMonitor) {
    this.page = page;
    this.monitor = monitor;
  }

  /** E2E_API_URL 이 아닌 주소로 나간 API 요청(fetch/xhr)을 끊는다. 실서버를 몰래 부르지 않게 한다 */
  async blockMisdirectedRequests(): Promise<void> {
    await this.page.route(isMisdirectedApiUrl, async (route) => {
      const request = route.request();
      if (!API_RESOURCE_TYPES.has(request.resourceType())) {
        await route.fallback();
        return;
      }
      this.misdirectedRequests.push(`${request.method()} ${request.url()}`);
      // 같은 요청을 콘솔 에러로 한 번 더 보고하지 않게 한다. 실패는 finish() 가 낸다.
      this.monitor.markIntendedAbort(request);
      await route.abort('blockedbyclient');
    });
  }

  /** 목업하지 않은 API 요청을 막는다. 개별 목업보다 먼저 등록해야 우선순위가 낮다 */
  async blockUnmockedRequests(): Promise<void> {
    await this.page.route(isApiRequestUrl, async (route) => {
      const request = route.request();
      const description = describeRequest(request.method(), new URL(request.url()));
      const failure = mockApiErrors.unmocked(description);
      this.unmockedRequests.push(description);
      // 같은 요청을 "예상 못한 HTTP 오류"로 한 번 더 보고하지 않게 한다. 실패는 finish() 가 낸다.
      this.monitor.markIntendedErrorResponse(request);
      await route.fulfill({ status: failure.status, json: failure.body });
    });
  }

  /** 이 엔드포인트에 reply 를 돌려준다 */
  async reply<TResponse>(
    endpoint: ApiEndpoint<TResponse>,
    reply: MockReply<NoInfer<TResponse>>,
  ): Promise<MockedEndpoint> {
    return this.register(endpoint, reply, null);
  }

  /**
   * 응답을 붙잡아 둔다. 테스트가 release() 를 부르기 전까지 화면은 응답을 받지 못한다.
   * 타이머로 늦추지 않으므로 "로딩 중" 상태를 원하는 만큼 확인할 수 있다.
   */
  async hold<TResponse>(
    endpoint: ApiEndpoint<TResponse>,
    reply: MockReply<NoInfer<TResponse>>,
  ): Promise<HeldEndpoint> {
    const gate = createGate();
    this.gates.push(gate);
    return this.register(endpoint, reply, gate);
  }

  /** 비로그인 방문자. GET /api/auth/me 가 401 UNAUTHORIZED */
  async guest(): Promise<MockedEndpoint> {
    return this.reply(apiEndpoints.authMe, mockReply.apiError(mockApiErrors.unauthorized()));
  }

  /** 로그인한 사용자. GET /api/auth/me 가 user 를 돌려준다 */
  async signedIn(user: User = mockUser()): Promise<MockedEndpoint> {
    return this.reply(apiEndpoints.authMe, mockReply.ok(user));
  }

  /** 홈 화면이 부르는 API 의 기본 목업. 관심 종목은 replies.watchlist 를 넘길 때만 (HomePageReplies 참고) */
  async homePage(replies: HomePageReplies = {}): Promise<void> {
    await this.reply(
      apiEndpoints.marketOverview,
      replies.market ?? mockReply.ok(mockMarketOverview()),
    );
    if (replies.watchlist) await this.reply(apiEndpoints.watchlist, replies.watchlist);
  }

  /** 종목 브리핑 화면이 부르는 API 의 기본 목업. 관심 종목은 replies.watchlist 를 넘길 때만 */
  async stockPage(code: string, replies: StockPageReplies = {}): Promise<void> {
    await this.reply(
      apiEndpoints.stockOverview(code),
      replies.overview ?? mockReply.ok(mockStockOverview({ stock: { code } })),
    );
    await this.reply(
      apiEndpoints.stockPrices(code),
      replies.prices ?? mockReply.ok(mockStockPrices({ code })),
    );
    await this.reply(
      apiEndpoints.stockFinancials(code),
      replies.financials ?? mockReply.ok(mockStockFinancials({ code })),
    );
    if (replies.watchlist) await this.reply(apiEndpoints.watchlist, replies.watchlist);
  }

  /** 테스트가 끝난 뒤 fixture 가 부른다 */
  async finish(): Promise<void> {
    // 풀지 않은 응답을 풀고, 이미 닫힌 요청에 응답하다 나는 오류는 버린다.
    for (const gate of this.gates) gate.open();
    await this.page.unrouteAll({ behavior: 'ignoreErrors' });
    expect(
      this.misdirectedRequests,
      'E2E_API_URL 이 아닌 주소로 API 요청이 나갔다. 앱이 VITE_API_BASE_URL=E2E_API_URL 로 떠 있는지 ' +
        '(재사용한 5174 dev 서버, E2E_BASE_URL 로 가리킨 프론트) 확인한다',
    ).toEqual([]);
    expect(
      this.unmockedRequests,
      '목업하지 않은 API 요청이 나갔다. 테스트에서 api.reply 등으로 목업을 추가한다',
    ).toEqual([]);
  }

  private async register<TResponse>(
    endpoint: ApiEndpoint<TResponse>,
    reply: MockReply<TResponse>,
    gate: Gate | null,
  ): Promise<HeldEndpoint> {
    const requestBodies: unknown[] = [];
    const firstRequest = createGate();
    await this.page.route(
      (url) => isEndpointUrl(endpoint, url),
      async (route) => {
        const request = route.request();
        if (request.method() !== endpoint.method) {
          await route.fallback();
          return;
        }
        requestBodies.push(readRequestBody(request));
        firstRequest.open();
        if (gate) await gate.opened;
        this.markIntendedFailure(request, reply);
        await sendReply(route, reply);
      },
    );

    return {
      get calls() {
        return requestBodies.length;
      },
      requestBodies,
      waitForRequest: () => firstRequest.opened,
      release: () => gate?.open(),
    };
  }

  /** 지금 보낼 응답이 오류면 이 요청 하나만 "예상한 오류"로 감시에 알린다 */
  private markIntendedFailure<TResponse>(request: Request, reply: MockReply<TResponse>): void {
    if (reply.kind === 'networkError') {
      this.monitor.markIntendedAbort(request);
      return;
    }
    if (reply.status >= 400) this.monitor.markIntendedErrorResponse(request);
  }
}
