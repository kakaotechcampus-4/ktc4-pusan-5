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
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-divider px-4 py-8 text-center">
      <div className="font-semibold">{title}</div>
      {description && <p className="text-sm text-neutral-600">{description}</p>}
      {action}
    </div>
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
    <div className="flex flex-col items-center gap-2 rounded-lg border border-up-200 bg-up-100 px-4 py-8 text-center">
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
