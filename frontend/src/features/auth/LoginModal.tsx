import { useEffect, useRef } from 'react';
import { Modal } from '@/components/ui';
import { useAuth } from './useAuth';
import { KakaoLoginButton } from './components/KakaoLoginButton';
import { buildKakaoAuthUrl } from './kakaoAuth';

type Props = {
  open: boolean;
  onClose: () => void;
};

// 로컬 개발 전용 테스트 로그인 진입점. 버튼을 따로 안 만들고 로고 클릭 횟수로 진입 가능
const TEST_LOGIN_CLICK_COUNT = 7;

export function LoginModal({ open, onClose }: Props) {
  const { loginAsTestAccount } = useAuth();
  const logoClickCount = useRef(0);

  useEffect(() => {
    if (!open) logoClickCount.current = 0;
  }, [open]);

  function handleLogin() {
    window.location.href = buildKakaoAuthUrl();
  }

  function handleLogoClick() {
    if (!import.meta.env.DEV) return;

    logoClickCount.current += 1;
    if (logoClickCount.current < TEST_LOGIN_CLICK_COUNT) return;

    logoClickCount.current = 0;
    loginAsTestAccount()
      .then(onClose)
      .catch((err: unknown) => console.warn('테스트 로그인 실패(백엔드 ENABLE_TEST_LOGIN 확인)', err));
  }

  return (
    <Modal open={open} onClose={onClose}>
      <div className="flex h-full flex-col items-center gap-6 pt-8 text-center">
        <div className="mt-8 flex flex-col gap-3">
          <div
            className="tracking-brand text-5xl leading-none font-bold"
            onClick={handleLogoClick}
          >
            MarketLit
          </div>
          <p className="text-sm leading-loose text-neutral-700">
            로그인 후,
            <br />
            관심 종목과 브리핑을
            <br />
            확인하세요
          </p>
        </div>

        <div className="flex w-full flex-col gap-3">
          <KakaoLoginButton loading={false} onClick={handleLogin} />
        </div>
      </div>
    </Modal>
  );
}
