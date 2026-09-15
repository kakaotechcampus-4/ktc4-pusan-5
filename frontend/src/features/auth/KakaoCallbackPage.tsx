import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ErrorBox, Skeleton } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { useAuth } from './useAuth';
import { buildKakaoAuthUrl } from './kakaoAuth';

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

  useEffect(() => {
    if (!code || requested.current) return;
    requested.current = true;

    loginWithKakao(code)
      .then(() => navigate('/', { replace: true }))
      .catch((err: unknown) => {
        const message =
          err instanceof ApiError ? (ERROR_MESSAGES[err.code] ?? err.message) : undefined;
        setError(message ?? '로그인에 실패했습니다');
      });
  }, [code, loginWithKakao, navigate]);

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
