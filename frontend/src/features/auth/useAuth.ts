// context 정의 및 useAuth 훅 모아둠
import { createContext, useContext } from 'react';
import type { User } from '@/lib/types';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

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
