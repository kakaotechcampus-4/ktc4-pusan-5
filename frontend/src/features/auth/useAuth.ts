// context 정의 및 useAuth 훅 모아둠
import { createContext, useContext } from 'react';
import type { User } from '@/lib/types';

//'error' : /api/auth/me 확인 자체가 실패한 상태(5xx / 네트워크 오류 / 401 403 외 기타 4xx).
// 로그인 여부를 서버가 확정해준 것이 아니기 때문에 'unauthenticated'와 구분함

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'error';

export type AuthContextValue = {
  user: User | null;
  status: AuthStatus;
  loginWithKakao: (code: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth는 AuthProvider 안에서만 사용할 수 있습니다');
  }
  return ctx;
}
