import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost';
  block?: boolean;
  children: ReactNode;
};

/**
 * 한 화면에 primary 는 하나만 둔다.
 * className 으로 색이나 여백을 덧입히지 않는다. 새 변형이 필요하면 여기에 추가한다.
 */
const VARIANT = {
  primary:
    'bg-brand text-white hover:bg-brand-500 active:bg-brand-700',
  secondary:
    'border border-divider hover:bg-neutral-100 active:bg-neutral-200',
  ghost:
    'text-brand px-1 hover:bg-brand-100',
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
        'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md',
        'px-4 py-2 text-sm font-semibold leading-tight cursor-pointer',
        'disabled:opacity-45 disabled:cursor-not-allowed',
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
