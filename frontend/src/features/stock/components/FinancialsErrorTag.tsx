import { useState } from 'react';
import { RetryIconButton, Tag } from '@/components/ui';

/** financials 조회 실패를 알리는 작은 표시. 영업이익 성장률·부채비율 행에서만 쓴다.
 * 재시도를 누르면 pending이 되고, error가 새로 바뀌면(성공/재실패 모두) pending을 푼다. */
export function FinancialsErrorTag({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const [pending, setPending] = useState(false);
  const [trackedError, setTrackedError] = useState(error);
  if (error !== trackedError) {
    setTrackedError(error);
    setPending(false);
  }
  return (
    <span className="inline-flex items-center gap-1">
      <Tag>조회 실패</Tag>
      <RetryIconButton
        pending={pending}
        onClick={() => {
          setPending(true);
          onRetry();
        }}
      />
    </span>
  );
}
