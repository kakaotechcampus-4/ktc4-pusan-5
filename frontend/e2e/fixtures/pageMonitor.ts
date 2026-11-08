/**
 * 콘솔·네트워크 감시. 테스트가 성공처럼 보여도 아래가 하나라도 있으면 테스트 끝에 실패시킨다.
 *   - console.error
 *   - 페이지에서 잡히지 않은 예외(pageerror)
 *   - 예상하지 못한 4xx/5xx 응답
 *
 * 의도한 오류를 알리는 방법은 두 가지다.
 *   - 목업(fixtures/apiMock.ts)이 오류를 "실제로 보낼 때" 그 요청 하나만 예상한 것으로 표시한다.
 *     목업을 등록만 해 둔 오류나, 나중에 덮어쓴 오류는 허용되지 않는다.
 *   - 목업이 없는 경우(@backend)는 테스트가 allow* 로 엔드포인트 단위로 먼저 알린다.
 */
import {
  expect,
  type ConsoleMessage,
  type Page,
  type Request,
  type Response,
} from '@playwright/test';
import { isEndpointUrl, type ApiEndpoint } from '../mocks/apiPaths';

type HttpErrorAllowance = { endpoint: ApiEndpoint; status?: number };

/** 크롬이 실패한 요청마다 남기는 콘솔 에러의 머리말 */
const RESOURCE_FAILURE_PREFIX = 'Failed to load resource';
/** 응답은 받았지만 4xx/5xx 인 경우의 문구. 이건 response 이벤트에서 따로 판정한다 */
const RESOURCE_HTTP_ERROR_TEXT = 'the server responded with a status of';

function parseUrl(raw: string): URL | null {
  try {
    return new URL(raw);
  } catch {
    return null;
  }
}

export class PageMonitor {
  private readonly problems: string[] = [];
  private readonly httpErrorAllowances: HttpErrorAllowance[] = [];
  private readonly requestFailureAllowances: ApiEndpoint[] = [];
  private readonly consoleErrorAllowances: RegExp[] = [];
  /** 목업이 일부러 4xx/5xx 로 답한 요청 */
  private readonly intendedErrorRequests = new WeakSet<Request>();
  /** 목업이 일부러 끊은 요청의 주소. 크롬 콘솔 에러에는 요청 객체가 없어 주소로 맞춘다 */
  private readonly intendedAbortedUrls = new Set<string>();

  constructor(page: Page) {
    page.on('console', (message) => this.handleConsole(message));
    page.on('pageerror', (error) => this.problems.push(`페이지 예외: ${error.message}`));
    page.on('response', (response) => this.handleResponse(response));
  }

  /** 이 엔드포인트의 4xx/5xx 응답은 예상한 것이다. status 를 빼면 모든 오류 코드를 허용한다 */
  allowHttpError(endpoint: ApiEndpoint, status?: number): void {
    this.httpErrorAllowances.push({ endpoint, status });
  }

  /** 이 엔드포인트가 응답 없이 끊기는 것(네트워크 오류)은 예상한 것이다 */
  allowRequestFailure(endpoint: ApiEndpoint): void {
    this.requestFailureAllowances.push(endpoint);
  }

  /** 이 문구의 console.error 는 예상한 것이다 */
  allowConsoleError(pattern: RegExp): void {
    this.consoleErrorAllowances.push(pattern);
  }

  /** fixtures/apiMock.ts 전용. 이 요청에 4xx/5xx 를 보내기 직전에 부른다 */
  markIntendedErrorResponse(request: Request): void {
    this.intendedErrorRequests.add(request);
  }

  /** fixtures/apiMock.ts 전용. 이 요청을 끊기 직전에 부른다 */
  markIntendedAbort(request: Request): void {
    this.intendedAbortedUrls.add(request.url());
  }

  /** 테스트가 끝난 뒤 fixture 가 부른다 */
  assertNoProblems(): void {
    expect(this.problems, '콘솔 에러·페이지 예외·예상 못한 HTTP 오류가 없어야 한다').toEqual([]);
  }

  private handleConsole(message: ConsoleMessage): void {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (this.consoleErrorAllowances.some((pattern) => pattern.test(text))) return;

    const location = message.location().url;
    if (text.startsWith(RESOURCE_FAILURE_PREFIX)) {
      if (text.includes(RESOURCE_HTTP_ERROR_TEXT)) return;
      if (this.intendedAbortedUrls.has(location)) return;
      const url = parseUrl(location);
      if (url && this.requestFailureAllowances.some((endpoint) => isEndpointUrl(endpoint, url))) {
        return;
      }
    }
    this.problems.push(`console.error: ${text}${location ? ` (${location})` : ''}`);
  }

  private handleResponse(response: Response): void {
    const status = response.status();
    if (status < 400) return;

    const request = response.request();
    if (this.intendedErrorRequests.has(request)) return;

    const method = request.method();
    const url = new URL(response.url());
    const allowed = this.httpErrorAllowances.some(
      ({ endpoint, status: allowedStatus }) =>
        endpoint.method === method &&
        isEndpointUrl(endpoint, url) &&
        (allowedStatus === undefined || allowedStatus === status),
    );
    if (allowed) return;
    this.problems.push(`예상 못한 HTTP ${status}: ${method} ${response.url()}`);
  }
}
