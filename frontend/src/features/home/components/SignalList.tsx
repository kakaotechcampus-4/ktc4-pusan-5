import { Link } from 'react-router-dom';
import { Change, ErrorBox, Skeleton, StockAvatar, Tag } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatAsOf, formatPrice } from '@/lib/format';
import type { SignalBoard } from '../mock';

export type SignalStatus = 'loading' | 'error' | 'success';

/**
 * 오늘 이야기가 몰린 종목 리스트.
 * 판단: 빈 상태는 두지 않았다. 장이 열린 날이면 상위 종목은 항상 존재하고,
 * 목록을 못 가져오는 경우는 빈 상태가 아니라 에러다.
 */
export function SignalSection({
  status,
  board,
  onRetry,
}: {
  status: SignalStatus;
  board: SignalBoard;
  onRetry: () => void;
}) {
  return (
    <section>
      <SectionHead title="개별 종목 시그널" right={<Tag tone="ai">AI 요약</Tag>} />

      {status === 'loading' && <SignalListSkeleton />}

      {status === 'error' && (
        <ErrorBox
          title="종목 시그널을 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status === 'success' && (
        <>
          <ol className="flex list-none flex-col">
            {board.signals.map((signal, i) => (
              <li key={signal.code}>
                <Link
                  to={`/stock/${signal.code}`}
                  className="border-divider text-ink flex items-center gap-3 border-b px-2 py-3 no-underline hover:bg-neutral-100"
                >
                  <span className="num w-6 flex-none text-xs font-semibold text-neutral-500">
                    {i + 1}
                  </span>
                  <StockAvatar initial={signal.initial} />
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="text-base font-semibold">{signal.name}</span>
                    <span className="text-sm text-neutral-600">{signal.summary}</span>
                  </span>
                  <span className="flex w-28 flex-none flex-col items-end gap-1">
                    <span className="num text-base font-semibold">{formatPrice(signal.price)}</span>
                    {/* 리스트는 부호 표기. 화살표는 카드·지수 타일에만. (DESIGN.md 2절) */}
                    <Change value={signal.change} size="sm" />
                  </span>
                </Link>
              </li>
            ))}
          </ol>

          {/* LLM 생성 필드는 생성 기준 시각과 출처를 함께 노출한다. (루트 CLAUDE.md) */}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-600">
            <span>{formatAsOf(new Date(board.generatedAt), 'AI 생성')}</span>
            <span>· 출처 {board.sources.join(', ')}</span>
          </div>
        </>
      )}
    </section>
  );
}

export function SignalListSkeleton() {
  return (
    <div className="flex flex-col">
      {Array.from({ length: 5 }).map((_, i) => (
        // 실제 행 높이(이름 15px + 한 줄 요약 13px, 두 줄)에 맞춘다.
        // 어긋나면 로딩이 끝나는 순간 목록 전체가 위아래로 튄다. (DESIGN.md 6절)
        <div key={i} className="border-divider flex items-center gap-3 border-b px-2 py-3">
          <Skeleton className="size-8 flex-none" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-5 w-3/5" />
          </div>
          <Skeleton className="h-12 w-28 flex-none" />
        </div>
      ))}
    </div>
  );
}
