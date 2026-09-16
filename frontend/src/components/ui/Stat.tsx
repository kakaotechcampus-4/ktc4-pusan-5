import type { ReactNode } from 'react';

/** 시총·PER 같은 수치 나열. 데스크톱 4열, 모바일 2열. */
export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{children}</div>;
}

export function Stat({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="bg-surface flex flex-col gap-1 rounded-md p-3">
      <div className="text-kicker tracking-kicker flex items-center gap-1 font-semibold text-neutral-600 uppercase">
        {label}
      </div>
      <div className="num text-base font-semibold">{value}</div>
    </div>
  );
}
