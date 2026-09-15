import { useState } from 'react';
import { ErrorBox, Modal } from '@/components/ui';
import { KakaoLoginButton } from './components/KakaoLoginButton';
import { mockKakaoLogin } from './mock';

type Status = 'idle' | 'loading' | 'error';

type Props = {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
};

/**
 * 에러 화면 ui 확인용 : 아래 mockKakaoLogin import 를 mock.ts 의 mockKakaoLoginError 로 전환
 * App에서 open 전환마다 key 를 바꿔 아래 컴포넌트를 새로 마운트 : 열릴 때마다 이전 에러 상태를 지움
 */
export function LoginModal({ open, onClose, onSuccess }: Props) {
  const [status, setStatus] = useState<Status>('idle');

  async function handleLogin() {
    setStatus('loading');
    try {
      await mockKakaoLogin();
      onSuccess();
      onClose();
    } catch {
      setStatus('error');
    }
  }

  function handleClose() {
    if (status === 'loading') return; // 로그인 진행 중엔 배경 클릭시 close
    onClose();
  }

  return (
    <Modal open={open} onClose={handleClose}>
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
          <KakaoLoginButton loading={status === 'loading'} onClick={handleLogin} />
          {status === 'error' && (
            <ErrorBox
              title="로그인에 실패했습니다"
              description="잠시 후 다시 시도해주세요"
              onRetry={handleLogin}
            />
          )}
        </div>
      </div>
    </Modal>
  );
}
