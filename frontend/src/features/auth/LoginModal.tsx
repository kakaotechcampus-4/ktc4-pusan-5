import { Modal } from '@/components/ui';
import { KakaoLoginButton } from './components/KakaoLoginButton';
import { buildKakaoAuthUrl } from './kakaoAuth';

type Props = {
  open: boolean;
  onClose: () => void;
};

export function LoginModal({ open, onClose }: Props) {
  function handleLogin() {
    window.location.href = buildKakaoAuthUrl();
  }

  return (
    <Modal open={open} onClose={onClose}>
      <div className="flex h-full flex-col items-center gap-6 pt-8 text-center">
        <div className="mt-8 flex flex-col gap-3">
          <div className="tracking-brand text-5xl leading-none font-bold">MarketLit</div>
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
