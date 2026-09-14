import { useEffect } from 'react';
import type { ReactNode } from 'react';

type Props = {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
};

/**
 * 화면 위에 뜨는 다이얼로그.
 * background : bg-ink/40 -> opacity : 0.4
 * 그림자는 shadow-md (다이얼로그·도크만 shadow-sm 이상 허용).
 */
export function Modal({ open, onClose, children }: Props) {
  useEffect(() => {
    if (!open) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="flex h-96 w-full max-w-xs flex-col overflow-y-auto rounded-lg bg-canvas p-8 shadow-md"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
