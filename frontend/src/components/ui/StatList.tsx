import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

/** 라벨-값을 세로로 나열하는 리스트. 박스형 StatGrid보다 좁은 영역에 적합하다. */
export function StatList({ children, className }: { children: ReactNode; className?: string }) {
  return <dl className={cn('flex flex-col', className)}>{children}</dl>;
}

export function StatListItem({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="border-divider flex items-center justify-between border-b py-2 last:border-b-0">
      <dt className="flex items-center gap-1 text-sm text-neutral-600">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
