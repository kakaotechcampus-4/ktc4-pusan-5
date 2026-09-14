import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'kakao';
  block?: boolean;
  children: ReactNode;
};

/**
 * 한 화면에 primary 는 하나만 둔다.
 * className 으로 색이나 여백을 덧입히지 않는다. 새 변형이 필요하면 여기에 추가한다.
 */
const VARIANT = {
  primary: 'text-sm bg-brand text-white hover:bg-brand-500 active:bg-brand-700',
  secondary: 'text-sm border border-divider hover:bg-neutral-100 active:bg-neutral-200',
  ghost: 'text-sm text-brand px-1 hover:bg-brand-100',
  /** 카카오 로그인 */
  kakao: 'h-12 text-base bg-kakao text-ink hover:brightness-95 active:brightness-90',
} as const;

export function Button({
  variant = 'secondary',
  block = false,
  children,
  className,
  ...rest
}: Props) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-md whitespace-nowrap',
        'cursor-pointer px-4 py-2 leading-tight font-semibold',
        'disabled:cursor-not-allowed disabled:opacity-45',
        VARIANT[variant],
        block && 'w-full',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
