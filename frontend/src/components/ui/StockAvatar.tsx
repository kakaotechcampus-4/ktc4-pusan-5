import { cn } from '@/lib/cn';

/**
 * 종목 로고 자리에 들어가는 이니셜 배지.
 */
export function StockAvatar({ initial, size = 'md' }: { initial: string; size?: 'sm' | 'md' }) {
  return (
    <div
      aria-hidden
      className={cn(
        'flex flex-none items-center justify-center rounded-sm',
        'text-canvas bg-neutral-800 font-semibold',
        size === 'sm' ? 'text-micro size-6' : 'size-8 text-xs',
      )}
    >
      {initial}
    </div>
  );
}
