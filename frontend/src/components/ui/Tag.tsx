import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

/** neutral 종목코드·중립 정보 | brand 카테고리 | ai AI 생성 표시 */
type Tone = 'neutral' | 'brand' | 'ai' | 'up' | 'down' | 'outline';

const TONE = {
  neutral: 'bg-neutral-200 text-neutral-800',
  brand:   'bg-brand-100 text-brand-800',
  ai:      'bg-ai-100 text-ai-700',
  up:      'bg-up-100 text-up-700',
  down:    'bg-down-100 text-down-700',
  outline: 'border border-brand text-brand',
} as const;

export function Tag({
  tone = 'neutral',
  onClick,
  children,
}: {
  tone?: Tone;
  onClick?: () => void;
  children: ReactNode;
}) {
  const cls = cn(
    'inline-flex items-center whitespace-nowrap rounded-sm px-2.5 py-0.5 text-xs font-medium',
    TONE[tone],
  );
  if (onClick) {
    return (
      <button type="button" className={cn(cls, 'cursor-pointer')} onClick={onClick}>
        {children}
      </button>
    );
  }
  return <span className={cls}>{children}</span>;
}
