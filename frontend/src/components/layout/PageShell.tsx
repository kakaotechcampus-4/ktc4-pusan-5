import type { ReactNode } from 'react';
import { Header } from './Header';

/**
 * 모든 페이지는 이걸로 감싼다. 최대 폭·좌우 여백·헤더가 여기서 한 번에 정해진다.
 * 페이지마다 헤더를 새로 만들거나 max-w 를 다시 지정하지 않는다.
 */
export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="mx-auto flex w-full max-w-page flex-col gap-8 px-6 pt-8 pb-30">
        {children}
      </main>
    </div>
  );
}

/** 본문 + 우측 고정 패널 2단. 종목 브리핑의 챗 패널이 여기 들어간다. */
export function SplitLayout({ main, side }: { main: ReactNode; side: ReactNode }) {
  return (
    <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,1fr)_var(--container-side)]">
      <div className="flex min-w-0 flex-col gap-6">{main}</div>
      <div>{side}</div>
    </div>
  );
}

/** 아래 2px 실선이 들어가는 섹션 제목 */
export function SectionHead({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 border-b-2 border-ink pb-2">
      <h2 className="text-h2">{title}</h2>
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}
