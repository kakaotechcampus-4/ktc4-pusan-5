import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Header } from './Header';

/**
 * 모든 페이지는 이걸로 감싼다. 최대 폭·좌우 여백·헤더가 여기서 한 번에 정해진다.
 * 페이지마다 헤더를 새로 만들거나 max-w 를 다시 지정하지 않는다.
 */
export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="max-w-page mx-auto flex w-full flex-col gap-8 px-6 pt-8 pb-30">
        {children}
      </main>
    </div>
  );
}

/**
 * align="start"(기본)는 각자 자기 내용 높이만큼만 차지한다.
 * align="stretch"는 lg 이상에서 두 칸 높이를 서로 맞춘다
 * 높이가 다른 층일 때 사용
 */
export function SplitLayout({
  main,
  side,
  align = 'start',
}: {
  main: ReactNode;
  side: ReactNode;
  align?: 'start' | 'stretch';
}) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_var(--container-side)]',
        align === 'start' ? 'items-start' : 'items-stretch',
      )}
    >
      <div className={cn('flex min-w-0 flex-col gap-6', align === 'stretch' && 'h-full')}>
        {main}
      </div>
      <div className={cn(align === 'stretch' && 'flex h-full flex-col')}>{side}</div>
    </div>
  );
}

/** 아래 2px 실선이 들어가는 섹션 제목 */
export function SectionHead({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="border-ink mb-4 flex flex-wrap items-end gap-3 border-b-2 pb-2">
      <h2 className="text-h2">{title}</h2>
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}
