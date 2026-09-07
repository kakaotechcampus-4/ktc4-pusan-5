import type { ReactNode } from 'react';

/** 시총·PER 같은 수치 나열. 데스크톱 4열, 모바일 2열. */
export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{children}</div>;
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-md bg-surface p-3">
      <div className="text-kicker font-semibold uppercase tracking-kicker text-neutral-600">
        {label}
      </div>
      <div className="num text-base font-semibold">{value}</div>
    </div>
  );
}
