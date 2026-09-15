import { useEffect, useState, type ReactNode } from 'react';
import { fetchMe, loginWithKakao as requestKakaoLogin, logout as requestLogout } from '@/lib/api';
import type { User } from '@/lib/types';
import { AuthContext, type AuthStatus } from './useAuth';

// 앱 진입 시 GET /api/auth/me 로 세션을 복원
// 새로고침해도 로그인 상태가 유지
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');

  useEffect(() => {
    fetchMe()
      .then((me) => {
        setUser(me);
        setStatus('authenticated');
      })
      .catch(() => {
        setUser(null);
        setStatus('unauthenticated');
      });
  }, []);

  // 백엔드 호출 후 user status 갱신
  async function loginWithKakao(code: string) {
    const me = await requestKakaoLogin(code);
    setUser(me);
    setStatus('authenticated');
  }

  async function logout() {
    await requestLogout();
    setUser(null);
    setStatus('unauthenticated');
  }

  return (
    <AuthContext.Provider value={{ user, status, loginWithKakao, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
