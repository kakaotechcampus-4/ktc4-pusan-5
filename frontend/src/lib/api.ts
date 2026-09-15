import type { ApiErrorBody, User } from './types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!res.ok) {
    // 실패 응답 ApiError 인스턴스로 변환
    const body: ApiErrorBody | null = await res.json().catch(() => null);
    throw new ApiError(
      body?.error.code ?? 'UNKNOWN_ERROR',
      body?.error.message ?? '요청에 실패했습니다',
    );
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
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
