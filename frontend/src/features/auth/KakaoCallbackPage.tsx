import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ErrorBox, Skeleton } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useAuth } from './useAuth';
import { buildKakaoAuthUrl, clearStoredState, peekStoredState } from './kakaoAuth';

const ERROR_MESSAGES: Record<string, string> = {
  KAKAO_AUTH_FAILED: '카카오 인증에 실패했습니다',
  KAKAO_EMAIL_REQUIRED: '이메일 제공에 동의해야 로그인할 수 있습니다',
};

function retryLogin() {
  window.location.href = buildKakaoAuthUrl();
}

// 카카오 인가 코드를 백엔드로 교환하는 중간 경유 페이지
// 인가 코드는 1회용이라 StrictMode 이중 호출을 막아야 됨
// ref 가드 넣어서 같은 code로는 교환 요청 1번만 하도록 함
export function KakaoCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { loginWithKakao } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const requested = useRef(false);
  const code = searchParams.get('code');
  const state = searchParams.get('state');
  // state가 로그인 시작 시 저장해둔 값과 다르면 CSRF로 의심한다. 
  // 검증을 한 번만 하도록 변경(useState)
  // peekStoredState에는 지우는 효과 없고 아래의 effect가 지움
  const [stateValid] = useState(() => state !== null && state === peekStoredState());

  useEffect(() => {
    if (!code || requested.current) return;
    requested.current = true;
    clearStoredState();

    if (!stateValid) return; // 렌더 시점에 에러 화면으로 분기

    loginWithKakao(code)
      .then(() => navigate('/', { replace: true }))
      .catch((err: unknown) => {
        const message =
          err instanceof ApiError ? (ERROR_MESSAGES[err.code] ?? err.message) : undefined;
        setError(message ?? '로그인에 실패했습니다');
      });
  }, [code, stateValid, loginWithKakao, navigate]);

  // code가 없는 경우를 렌더 중 분기 처리
  if (!code) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <ErrorBox
          title="로그인에 실패했습니다"
          description="카카오 인증 코드를 받지 못했습니다"
          onRetry={retryLogin}
        />
      </div>
    );
  }

  if (!stateValid) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <ErrorBox
          title="로그인에 실패했습니다"
          description="로그인 요청을 확인할 수 없습니다. 처음부터 다시 시도해주세요"
          onRetry={retryLogin}
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <ErrorBox title="로그인에 실패했습니다" description={error} onRetry={retryLogin} />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-4 w-32" />
    </div>
  );
}
