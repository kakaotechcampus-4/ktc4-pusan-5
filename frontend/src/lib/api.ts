/**
 * 브라우저에서 fetch로 백엔드 주소를 호출
 *
 * 에러 응답 형태
 *   { "error": { "code": "CONCEPT_NOT_FOUND", "message": "개념을 찾을 수 없습니다" } }
 */
import type {
  ApiErrorBody,
  MarketOverview,
  StockOverview,
  StockPriceResource,
  StockFinancials,
  PricePeriod,
  User,
} from './types';
import type { Concept, ConceptListResponse } from '@/features/concepts/types';

/** 베이스 URL 은 .env 로만 읽는다. 코드에 URL 을 박지 않는다. */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/** 서버가 형태를 지키지 못했거나 네트워크가 끊겼을 때 쓰는 코드 */
const NETWORK_ERROR = 'NETWORK_ERROR';
const INVALID_RESPONSE = 'INVALID_RESPONSE';

/**
 * 화면이 처리하는 단일 에러.
 * status 0 은 응답을 받지 못한 경우(네트워크 실패)
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

async function readApiError(response: Response): Promise<ApiError> {
  const body: ApiErrorBody | null = await response.json().catch(() => null);
  const code = body?.error?.code ?? INVALID_RESPONSE;
  const message = body?.error?.message ?? '요청을 처리하지 못했습니다';
  return new ApiError(code, message, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(NETWORK_ERROR, '서버에 연결하지 못했습니다', 0);
  }

  if (!response.ok) {
    throw await readApiError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(INVALID_RESPONSE, '응답을 해석하지 못했습니다', response.status);
  }
}

/** 개념 상세, 없으면 CONCEPT_NOT_FOUND ApiError */
export function getConcept(slug: string): Promise<Concept> {
  return request<Concept>(`/api/concepts/${encodeURIComponent(slug)}`);
}

/** 개념 목록, 현재 미구현 */
export function listConcepts(): Promise<ConceptListResponse> {
  return request<ConceptListResponse>('/api/concepts');
}

export function fetchMe(): Promise<User> {
  return request<User>('/api/auth/me');
}

export function loginWithKakao(code: string): Promise<User> {
  return request<User>('/api/auth/kakao', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
}

export function logout(): Promise<void> {
  return request<void>('/api/auth/logout', { method: 'POST' });
}

export function getMarketOverview(signal?: AbortSignal): Promise<MarketOverview> {
  return request<MarketOverview>('/api/market/overview', { signal });
}

export function getStockOverview(code: string, signal?: AbortSignal): Promise<StockOverview> {
  return request<StockOverview>(`/api/stocks/${encodeURIComponent(code)}/overview`, { signal });
}

export function getStockPrices(
  code: string,
  period: PricePeriod,
  signal?: AbortSignal,
  fromDate?: string,
): Promise<StockPriceResource> {
  return request<StockPriceResource>(
    `/api/stocks/${encodeURIComponent(code)}/prices?period=${period}${fromDate ? `&fromDate=${encodeURIComponent(fromDate)}` : ''}`,
    { signal },
  );
}

export function getStockFinancials(code: string, signal?: AbortSignal): Promise<StockFinancials> {
  return request<StockFinancials>(`/api/stocks/${encodeURIComponent(code)}/financials`, { signal });
}
