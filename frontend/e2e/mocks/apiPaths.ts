/**
 * 앱이 부르는 API 경로 모음. 경로가 바뀌면 이 파일만 고친다. (원본: src/lib/api.ts)
 *
 * 엔드포인트마다 응답 타입을 붙여 둔다. 목업 응답을 엉뚱한 엔드포인트에 넣거나
 * src/lib/types.ts 계약이 바뀌면 e2e:typecheck 가 실패한다.
 * 쿼리스트링은 매칭에서 무시한다. (예: /prices?period=1Y 는 /prices 로 본다)
 *
 * 로그아웃(POST /api/auth/logout)은 목업 시나리오가 없어 두지 않는다. 생기면 응답이 없는(void)
 * 엔드포인트로 추가한다. (src/lib/api.ts logout 은 응답 본문을 쓰지 않는다)
 */
import type {
  MarketOverview,
  StockFinancials,
  StockOverview,
  StockPriceResource,
  User,
  WatchlistResponse,
} from '../../src/lib/types';
import type { Concept } from '../../src/features/concepts/types';
import { E2E_API_URL, E2E_BASE_URL } from '../env';

export type ApiEndpoint<TResponse = unknown> = {
  readonly method: string;
  /** E2E_API_URL 뒤에 붙는 경로. 쿼리스트링 없이 쓴다 */
  readonly path: string;
  /** 응답 타입 표시용. 값은 넣지 않는다 */
  readonly responseType?: TResponse;
};

function endpoint<TResponse>(method: string, path: string): ApiEndpoint<TResponse> {
  return { method, path };
}

function pathSegment(value: string): string {
  return encodeURIComponent(value);
}

export const apiEndpoints = {
  authMe: endpoint<User>('GET', '/api/auth/me'),
  kakaoLogin: endpoint<User>('POST', '/api/auth/kakao'),
  testLogin: endpoint<User>('POST', '/api/auth/test-login'),
  marketOverview: endpoint<MarketOverview>('GET', '/api/market/overview'),
  watchlist: endpoint<WatchlistResponse>('GET', '/api/watchlist'),
  stockOverview: (code: string) =>
    endpoint<StockOverview>('GET', `/api/stocks/${pathSegment(code)}/overview`),
  stockPrices: (code: string) =>
    endpoint<StockPriceResource>('GET', `/api/stocks/${pathSegment(code)}/prices`),
  stockFinancials: (code: string) =>
    endpoint<StockFinancials>('GET', `/api/stocks/${pathSegment(code)}/financials`),
  concept: (slug: string) => endpoint<Concept>('GET', `/api/concepts/${pathSegment(slug)}`),
} as const;

/** 요청이 실제로 가는 주소 */
export function apiUrl(target: ApiEndpoint): string {
  return `${E2E_API_URL}${target.path}`;
}

function withoutQuery(url: URL): string {
  return `${url.origin}${url.pathname}`;
}

/** 이 앱의 API 요청인지. 목업 시나리오에서 가로채지 않은 요청을 잡는 데 쓴다 */
export function isApiRequestUrl(url: URL): boolean {
  return withoutQuery(url).startsWith(`${E2E_API_URL}/api/`);
}

const APP_ORIGIN = new URL(E2E_BASE_URL).origin;
const API_ORIGIN = new URL(E2E_API_URL).origin;

/**
 * E2E_API_URL 이 아닌 곳으로 나갔을 수 있는 API 요청.
 * 앱이 VITE_API_BASE_URL=E2E_API_URL 을 주입받지 못하면(재사용한 dev 서버, E2E_BASE_URL 로 가리킨
 * 다른 프론트) 요청이 frontend/.env 의 주소나 상대경로로 나가 목업과 가드를 모두 비켜 간다.
 *   - 앱 출처도 E2E_API_URL 출처도 아닌 곳
 *   - 앱 출처의 /api/ 경로 (VITE_API_BASE_URL 이 비어 상대경로로 나간 경우)
 * 글꼴·이미지 같은 리소스도 여기 걸리므로 fetch/xhr 인지는 fixtures/apiMock.ts 가 다시 거른다.
 */
export function isMisdirectedApiUrl(url: URL): boolean {
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
  if (url.origin === API_ORIGIN) return false;
  return url.origin !== APP_ORIGIN || url.pathname.includes('/api/');
}

/** 쿼리스트링을 뺀 주소가 같으면 같은 엔드포인트로 본다. 메서드는 따로 비교한다 */
export function isEndpointUrl(target: ApiEndpoint, url: URL): boolean {
  return withoutQuery(url) === apiUrl(target);
}

/** 실패 메시지에 쓰는 사람이 읽을 이름. 예: "GET /api/watchlist?x=1" */
export function describeRequest(method: string, url: URL): string {
  return `${method} ${url.pathname}${url.search}`;
}
