import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Button } from './Button';

/**
 * 데이터를 부르는 화면은 로딩·빈 상태·에러 3종을 반드시 함께 만든다.
 * 스피너는 쓰지 않는다. 실제 콘텐츠와 같은 자리·같은 높이의 스켈레톤을 깐다.
 */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse-soft rounded-sm bg-neutral-200', className)} />;
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={cn('h-3', i === lines - 1 && 'w-3/5')} />
      ))}
    </div>
  );
}

/** 빈 상태는 다음 행동을 알려준다. "데이터 없음"만 쓰지 않는다. */
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="border-divider flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center">
      <div className="font-semibold">{title}</div>
      {description && <p className="text-sm text-neutral-600">{description}</p>}
      {action}
    </div>
  );
}

/** 좁은 영역(행·인라인)에서 쓰는 작은 재시도 아이콘 버튼. 큰 재시도 UI는 ErrorBox를 쓴다.
 * 스피너는 쓰지 않는다는 원칙을 따라, pending 동안은 회전 대신 기존 pulse-soft로 흐려진다. */
export function RetryIconButton({
  onClick,
  pending = false,
  label = '다시 시도',
}: {
  onClick: () => void;
  pending?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={pending}
      className={cn(
        'inline-flex h-5 w-5 items-center justify-center rounded-sm text-neutral-600',
        'hover:text-neutral-800 disabled:cursor-not-allowed',
        pending && 'animate-pulse-soft',
      )}
    >
      <svg
        viewBox="0 0 16 16"
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M13.5 8a5.5 5.5 0 1 1-1.6-3.89M13.5 2.5v3.11h-3.11"
        />
      </svg>
    </button>
  );
}

/** 에러는 무엇이 실패했고 무엇을 하면 되는지 적는다. 사과하지 않는다. */
export function ErrorBox({
  title = '불러오지 못했습니다',
  description = '잠시 후 다시 시도해주세요',
  onRetry,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="border-up-200 bg-up-100 flex flex-col items-center gap-2 rounded-lg border px-4 py-8 text-center">
      <div className="font-semibold">{title}</div>
      <p className="text-sm text-neutral-700">{description}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          다시 시도
        </Button>
      )}
    </div>
  );
}
