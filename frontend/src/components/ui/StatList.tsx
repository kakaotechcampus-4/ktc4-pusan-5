import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

/** 라벨-값을 세로로 나열하는 리스트. 박스형 StatGrid보다 좁은 영역에 적합하다. */
export function StatList({ children, className }: { children: ReactNode; className?: string }) {
  return <dl className={cn('flex flex-col', className)}>{children}</dl>;
}

export function StatListItem({
  label,
  value,
  layout = 'row',
}: {
  label: ReactNode;
  value: ReactNode;
  /** 'row' 라벨·값 한 줄 좌우 배치 | 'stack' 라벨 아래 값. 값이 길어 비좁을 때 쓴다. */
  layout?: 'row' | 'stack';
}) {
  if (layout === 'stack') {
    return (
      <div className="border-divider flex flex-col gap-1 border-b py-2 last:border-b-0">
        <dt className="flex items-center gap-1 text-sm text-neutral-600">{label}</dt>
        <dd>{value}</dd>
      </div>
    );
  }
  return (
    <div className="border-divider flex items-center justify-between border-b py-2 last:border-b-0">
      <dt className="flex items-center gap-1 text-sm text-neutral-600">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
