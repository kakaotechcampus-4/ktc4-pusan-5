import { Link } from 'react-router-dom';
import { Change, ErrorBox, Skeleton, StockAvatar, Tag } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import { formatAsOf, formatPrice } from '@/lib/format';
import type { SignalBoard, SignalBoardStatus } from '../useSignalBoard';

/**
 * 고정 종목 다섯 개의 실제 시세와 보고서 한 줄 요약.
 * 보고서가 아직 없는 종목은 "준비 중"으로 두고,
 * AI 표시는 실제 한 줄 요약이 하나라도 있을 때만 붙인다.
 */
export function SignalSection({
  status,
  board,
  onRetry,
}: {
  status: SignalBoardStatus;
  board: SignalBoard | null;
  onRetry: () => void;
}) {
  const hasSummary = board?.signals.some((signal) => signal.summary) ?? false;

  return (
    <section>
      <SectionHead
        title="개별 종목 시그널"
        right={hasSummary ? <Tag tone="ai">AI 요약</Tag> : undefined}
      />

      {status === 'loading' && <SignalListSkeleton />}

      {status === 'error' && (
        <ErrorBox
          title="종목 시그널을 불러오지 못했습니다"
          description="잠시 후 다시 시도해주세요"
          onRetry={onRetry}
        />
      )}

      {status === 'success' && board && (
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
                    {signal.summary ? (
                      <span className="text-sm text-neutral-600">{signal.summary}</span>
                    ) : (
                      <span className="text-sm text-neutral-500">분석 보고서 준비 중</span>
                    )}
                  </span>
                  <span className="flex w-28 flex-none flex-col items-end gap-1">
                    <span className="num text-base font-semibold">
                      {signal.price === null ? '—' : formatPrice(signal.price)}
                    </span>
                    {/* 리스트는 부호 표기. 화살표는 카드·지수 타일에만. (DESIGN.md 2절) */}
                    {signal.change !== null && <Change value={signal.change} size="sm" />}
                  </span>
                </Link>
              </li>
            ))}
          </ol>

          {/* LLM 생성 필드는 생성 기준 시각과 출처를 함께 노출한다. (루트 CLAUDE.md) */}
          {hasSummary && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-600">
              {board.generatedAt && (
                <span>{formatAsOf(new Date(board.generatedAt), 'AI 생성')}</span>
              )}
              {board.sources.length > 0 && <span>· 출처 {board.sources.join(', ')}</span>}
            </div>
          )}
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
