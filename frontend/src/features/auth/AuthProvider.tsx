import { useEffect, useState, type ReactNode } from 'react';
import {
  ApiError,
  fetchMe,
  loginWithKakao as requestKakaoLogin,
  logout as requestLogout,
} from '@/lib/api';
import type { User } from '@/lib/types';
import { AuthContext, type AuthStatus } from './useAuth';

type AuthCheckFailure = 'unauthenticated' | 'serverError' | 'networkError' | 'clientError';

// GET /api/auth/me 실패를 client의 action level 기준 4가지로 분류한다.
function classifyAuthCheckFailure(err: unknown): AuthCheckFailure {
  if (!(err instanceof ApiError)) return 'clientError';
  if (err.status === 401 || err.status === 403) return 'unauthenticated';
  if (err.status === 0) return 'networkError';
  if (err.status >= 500) return 'serverError';
  return 'clientError';
}

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
      .catch((err: unknown) => {
        const failure = classifyAuthCheckFailure(err);

        // 인증 만료 or 무효(401/403): 서버가 "로그인 안 됐다"고 확정해준 경우만 로그아웃 처리
        if (failure === 'unauthenticated') {
          setUser(null);
          setStatus('unauthenticated');
          return;
        }

        // 일시적 서버 장애(5xx) / 네트워크 연결 문제 / 기타 4xx :
        // 서버가 로그인 여부를 확인해준 게 아니므로 로그인 사용자를 로그아웃된 것처럼 보이게 하지 않는다
        if (failure === 'serverError') {
          console.warn('일시적 서버 장애로 로그인 상태를 확인하지 못했습니다', err);
        } else if (failure === 'networkError') {
          console.warn('네트워크 연결 문제로 로그인 상태를 확인하지 못했습니다', err);
        } else {
          console.warn('예상치 못한 요청 오류로 로그인 상태를 확인하지 못했습니다', err);
        }
        setStatus('error');
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
