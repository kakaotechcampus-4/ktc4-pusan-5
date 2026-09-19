import { Button } from '@/components/ui';

/** 카카오 로고 */
function KakaoSymbol() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" className="shrink-0">
      <path
        fill="currentColor"
        d="M12 3.5C6.75 3.5 2.5 6.86 2.5 11c0 2.63 1.77 4.94 4.43 6.26-.2.72-.72 2.6-.83 3-.13.5.18.5.39.36.16-.11 2.6-1.76 3.65-2.48.6.09 1.22.13 1.86.13 5.25 0 9.5-3.36 9.5-7.5S17.25 3.5 12 3.5Z"
      />
    </svg>
  );
}

export function KakaoLoginButton({
  loading,
  onClick,
}: {
  loading: boolean;
  onClick: () => void;
}) {
  return (
    <Button variant="kakao" block disabled={loading} onClick={onClick}>
      <KakaoSymbol />
      {loading ? '로그인 중...' : '카카오로 로그인'}
    </Button>
  );
}
