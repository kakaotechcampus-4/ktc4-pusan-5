import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

type Props = {
  /** 'surface' 회색 면 | 'plain' 흰 면 + 테두리. 이 둘 외의 카드는 만들지 않는다. */
  tone?: 'surface' | 'plain';
  elevated?: boolean;
  className?: string;
  children: ReactNode;
};

export function Card({ tone = 'surface', elevated = false, className, children }: Props) {
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg p-4',
        tone === 'plain' ? 'bg-canvas border border-divider' : 'bg-surface',
        elevated && 'shadow-sm',
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <div className="text-h3 font-bold leading-tight">{children}</div>;
}

export function CardBody({ children }: { children: ReactNode }) {
  return <p className="flex-1 text-sm text-neutral-700">{children}</p>;
}

export function CardMeta({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-1.5 text-xs text-neutral-600">{children}</div>;
}

/** 섹션·카드 위 작은 라벨 */
export function Kicker({ children }: { children: ReactNode }) {
  return (
    <div className="text-kicker font-semibold uppercase tracking-kicker text-brand whitespace-nowrap">
      {children}
    </div>
  );
}
